"""Pure schema and cross-reference validation for production packages.

This module validates submitted structure only. It never reads assets or files,
contacts the network, launches a process, or invokes the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .integration_schemas import BusinessClaim


CONTRACT_VERSION = "spotloom.production-package.v1"
CONTRACT_VERSION_V2 = "spotloom.production-package.v2"
PROFILE_ID = "spotloom.storyboard.vertical-1080x1920-h264-aac-15s.v1"
FPS = 24
TARGET_FRAMES = 15 * FPS
MAX_PACKAGE_BYTES = 64 * 1024

_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_ID_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
_ASSET_ID_RE = re.compile(r"^ast_[A-Za-z0-9_-]{8,80}$")
_ASSET_VERSION_ID_RE = re.compile(r"^ver_[A-Za-z0-9_-]{8,80}$")
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ClaimText(_StrictModel):
    """Literal claim text linked to one caller-marked approved fact."""

    kind: Literal["claim"]
    text: StrictStr = Field(min_length=1, max_length=500)
    factId: StrictStr = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must be nonblank")
        return value


class CreativeText(_StrictModel):
    """Declared non-claim copy; structural validation cannot infer factuality."""

    kind: Literal["creative"]
    text: StrictStr = Field(min_length=1, max_length=500)

    @field_validator("text")
    @classmethod
    def nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must be nonblank")
        return value


TextContent = Annotated[Union[ClaimText, CreativeText], Field(discriminator="kind")]


class ProductionBrief(_StrictModel):
    """Profile brief requiring explicit claim/creative classification for copy."""

    objective: Literal["awareness", "engagement", "traffic", "conversions"]
    targetAudience: TextContent
    productOrOffer: TextContent
    keyMessage: TextContent
    valueProposition: TextContent | None
    platform: Literal["instagram", "tiktok", "youtube", "other"]
    aspectRatio: Literal["9:16", "1:1", "16:9"]
    duration: Literal[15, 30, 60]
    tone: TextContent
    callToAction: TextContent
    reliedUponFactIds: list[StrictStr] = Field(max_length=32)
    requirementsConfirmed: bool

    @field_validator("reliedUponFactIds")
    @classmethod
    def unique_fact_references(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("fact references must be unique")
        return values


class TextElement(_StrictModel):
    type: Literal["text"]
    id: StrictStr = Field(pattern=_ID_RE.pattern)
    x: StrictInt = Field(ge=0, le=10_000)
    y: StrictInt = Field(ge=0, le=10_000)
    width: StrictInt = Field(gt=0, le=10_000)
    height: StrictInt = Field(gt=0, le=10_000)
    style: Literal["heading", "body", "caption"]
    align: Literal["left", "center", "right"]
    content: TextContent


class ShapeElement(_StrictModel):
    type: Literal["shape"]
    id: StrictStr = Field(pattern=_ID_RE.pattern)
    x: StrictInt = Field(ge=0, le=10_000)
    y: StrictInt = Field(ge=0, le=10_000)
    width: StrictInt = Field(gt=0, le=10_000)
    height: StrictInt = Field(gt=0, le=10_000)
    shape: Literal["circle", "rounded_rectangle", "line"]
    color: StrictStr = Field(pattern=_COLOR_RE.pattern)


VisualElement = Annotated[Union[TextElement, ShapeElement], Field(discriminator="type")]


class StoryboardScene(_StrictModel):
    id: StrictStr = Field(pattern=_ID_RE.pattern)
    order: StrictInt = Field(ge=1, le=32)
    title: TextContent
    narrativePurpose: TextContent
    durationFrames: StrictInt = Field(ge=1, le=TARGET_FRAMES)
    transitionFromPrevious: Literal["none", "cut"]
    backgroundColor: StrictStr = Field(pattern=_COLOR_RE.pattern)
    elements: list[VisualElement] = Field(max_length=12)

    @model_validator(mode="after")
    def title_length(self) -> StoryboardScene:
        if len(self.title.text) > 120:
            raise ValueError("title must be at most 120 characters")
        return self


class ManagedAudioAsset(_StrictModel):
    """Declared audio metadata; the opaque ID is never resolved in this module."""

    id: StrictStr = Field(pattern=_ASSET_ID_RE.pattern)
    kind: Literal["audio"]
    format: Literal["wav-pcm-s16le-48000-stereo"]
    declaredDurationFrames: StrictInt = Field(ge=1, le=86_400)


class AudioSegment(_StrictModel):
    id: StrictStr = Field(pattern=_ID_RE.pattern)
    kind: Literal["narration", "music", "sound_effect"]
    assetId: StrictStr = Field(pattern=_ASSET_ID_RE.pattern)
    sceneId: StrictStr | None = Field(default=None, pattern=_ID_RE.pattern)
    startFrame: StrictInt = Field(ge=0, lt=TARGET_FRAMES)
    endFrame: StrictInt = Field(ge=1, le=TARGET_FRAMES)
    sourceStartFrame: StrictInt = Field(ge=0)
    transcript: TextContent | None = None


class ProductionPackage(_StrictModel):
    contractVersion: Literal["spotloom.production-package.v1"]
    correlationId: StrictStr
    rendererProfileId: Literal[
        "spotloom.storyboard.vertical-1080x1920-h264-aac-15s.v1"
    ]
    brief: ProductionBrief
    facts: list[BusinessClaim] = Field(max_length=32)
    scenes: list[StoryboardScene] = Field(min_length=1, max_length=32)
    assets: list[ManagedAudioAsset] = Field(min_length=1, max_length=16)
    audioSegments: list[AudioSegment] = Field(min_length=1, max_length=64)

    @field_validator("correlationId")
    @classmethod
    def canonical_uuid(cls, value: str) -> str:
        try:
            if not _UUID_RE.fullmatch(value) or str(UUID(value)) != value:
                raise ValueError
        except ValueError as exc:
            raise ValueError("correlationId must be a canonical lowercase UUID") from exc
        return value


class VersionedManagedAudioAsset(ManagedAudioAsset):
    """V2 asset declaration pinned to one immutable version identity."""

    assetVersionId: StrictStr = Field(pattern=_ASSET_VERSION_ID_RE.pattern)


class ProductionPackageV2(ProductionPackage):
    """Strict v2 package with project-scoped immutable asset references."""

    contractVersion: Literal["spotloom.production-package.v2"]
    projectId: StrictStr = Field(pattern=_PROJECT_ID_RE.pattern)
    assets: list[VersionedManagedAudioAsset] = Field(min_length=1, max_length=16)


@dataclass(frozen=True)
class PackageIssue:
    code: str
    path: str
    message: str
    severity: Literal["error"] = "error"


@dataclass(frozen=True)
class ProductionPackageValidation:
    valid: bool
    issues: tuple[PackageIssue, ...]
    package: ProductionPackage | None = None
    correlation_id: str | None = None
    contract_version: str | None = None


@dataclass(frozen=True)
class ProductionPackageV2Validation:
    """Separate result type keeps v2 packages outside the legacy plan compiler."""

    valid: bool
    issues: tuple[PackageIssue, ...]
    package: ProductionPackageV2 | None = None
    correlation_id: str | None = None
    contract_version: str | None = None


def _issue(code: str, path: str, message: str) -> PackageIssue:
    return PackageIssue(code=code, path=path, message=message)


def _unique(values: list[str]) -> bool:
    return len(values) == len(set(values))


def _canonical_correlation_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        if not _UUID_RE.fullmatch(value) or str(UUID(value)) != value:
            return None
    except ValueError:
        return None
    return value


def _correlation_id_from_value(value: object) -> str | None:
    if isinstance(value, dict):
        return _canonical_correlation_id(value.get("correlationId"))
    return None


def _explicit_contract_version(value: object, expected: str) -> str | None:
    if isinstance(value, dict) and value.get("contractVersion") == expected:
        return expected
    return None


def _cross_reference_issues(package: ProductionPackage | ProductionPackageV2) -> tuple[PackageIssue, ...]:
    issues: list[PackageIssue] = []
    if package.brief.duration != 15:
        issues.append(_issue(
            "profile_duration_mismatch", "brief.duration",
            "This profile requires a 15-second brief target.",
        ))
    if package.brief.aspectRatio != "9:16":
        issues.append(_issue(
            "profile_aspect_ratio_mismatch", "brief.aspectRatio",
            "This profile requires a 9:16 brief aspect ratio.",
        ))

    fact_ids = [fact.id for fact in package.facts]
    scene_ids = [scene.id for scene in package.scenes]
    asset_ids = [asset.id for asset in package.assets]
    segment_ids = [segment.id for segment in package.audioSegments]
    for values, path, code in (
        (fact_ids, "facts", "duplicate_fact_id"),
        (scene_ids, "scenes", "duplicate_scene_id"),
        (asset_ids, "assets", "duplicate_asset_id"),
        (segment_ids, "audioSegments", "duplicate_segment_id"),
    ):
        if not _unique(values):
            issues.append(_issue(code, path, "Identifiers must be unique."))

    scene_spans: dict[str, tuple[int, int]] = {}
    cursor = 0
    for index, scene in enumerate(package.scenes):
        path = f"scenes.{index}"
        if scene.order != index + 1:
            issues.append(_issue("scene_order_invalid", f"{path}.order", "Scenes must be ordered consecutively from 1."))
        expected_transition = "none" if index == 0 else "cut"
        if scene.transitionFromPrevious != expected_transition:
            issues.append(_issue("transition_unsupported", f"{path}.transitionFromPrevious", "Only no initial transition and hard cuts are supported."))
        end = cursor + scene.durationFrames
        scene_spans.setdefault(scene.id, (cursor, end))
        cursor = end
        element_ids = [element.id for element in scene.elements]
        if not _unique(element_ids):
            issues.append(_issue("duplicate_visual_element_id", f"{path}.elements", "Visual element identifiers must be unique within a scene."))
        for element_index, element in enumerate(scene.elements):
            if element.x + element.width > 10_000 or element.y + element.height > 10_000:
                issues.append(_issue("visual_bounds_out_of_range", f"{path}.elements.{element_index}", "Visual elements must fit within normalized canvas bounds."))
    if cursor != TARGET_FRAMES:
        issues.append(_issue("scene_duration_total_mismatch", "scenes", "Ordered scene durations must total exactly 360 frames (15 seconds)."))

    facts_by_id = {fact.id: fact for fact in package.facts}

    def check_text(content: TextContent, path: str) -> None:
        if not isinstance(content, ClaimText):
            return
        fact = facts_by_id.get(content.factId)
        if fact is None:
            issues.append(_issue("fact_reference_missing", f"{path}.factId", "The referenced fact is not included in the package."))
        elif fact.status != "approved":
            issues.append(_issue("fact_not_caller_approved", f"{path}.factId", "Claim text may reference only a fact marked approved by the caller."))
        elif fact.claim != content.text:
            issues.append(_issue("claim_text_mismatch", path, "Claim text must exactly match its referenced current fact text."))

    for field_name in (
        "targetAudience", "productOrOffer", "keyMessage", "valueProposition", "tone", "callToAction",
    ):
        content = getattr(package.brief, field_name)
        if content is not None:
            check_text(content, f"brief.{field_name}")

    for scene_index, scene in enumerate(package.scenes):
        check_text(scene.title, f"scenes.{scene_index}.title")
        check_text(scene.narrativePurpose, f"scenes.{scene_index}.narrativePurpose")
        for element_index, element in enumerate(scene.elements):
            if isinstance(element, TextElement):
                check_text(element.content, f"scenes.{scene_index}.elements.{element_index}.content")

    assets_by_id = {asset.id: asset for asset in package.assets}
    used_asset_ids: set[str] = set()
    narration_spans: dict[str, list[tuple[int, int, int]]] = {}
    for index, segment in enumerate(package.audioSegments):
        path = f"audioSegments.{index}"
        if segment.startFrame >= segment.endFrame:
            issues.append(_issue("audio_interval_invalid", path, "Audio segment endFrame must be after startFrame."))
        asset = assets_by_id.get(segment.assetId)
        if asset is None:
            issues.append(_issue("asset_reference_missing", f"{path}.assetId", "The referenced managed asset is not declared in the package."))
        else:
            used_asset_ids.add(asset.id)
            segment_duration = segment.endFrame - segment.startFrame
            if segment.sourceStartFrame + segment_duration > asset.declaredDurationFrames:
                issues.append(_issue("audio_exceeds_declared_asset", path, "Audio segment exceeds its declared asset duration."))
        if segment.kind == "narration":
            if segment.sceneId is None or segment.transcript is None:
                issues.append(_issue("narration_fields_required", path, "Narration requires a scene and transcript."))
            elif segment.sceneId not in scene_spans:
                issues.append(_issue("scene_reference_missing", f"{path}.sceneId", "The narration scene is not included in the package."))
            else:
                start, end = scene_spans[segment.sceneId]
                if segment.startFrame < start or segment.endFrame > end:
                    issues.append(_issue("narration_outside_scene", path, "Narration timing must fit within its associated scene."))
                narration_spans.setdefault(segment.sceneId, []).append((segment.startFrame, segment.endFrame, index))
            if segment.transcript is not None:
                check_text(segment.transcript, f"{path}.transcript")
        elif segment.transcript is not None:
            issues.append(_issue("non_narration_transcript_unsupported", f"{path}.transcript", "Only narration segments may include transcript text."))
        if segment.sceneId is not None and segment.sceneId not in scene_spans:
            issues.append(_issue("scene_reference_missing", f"{path}.sceneId", "The audio scene is not included in the package."))
        elif segment.sceneId is not None:
            scene_start, scene_end = scene_spans[segment.sceneId]
            if segment.startFrame < scene_start or segment.endFrame > scene_end:
                issues.append(_issue("audio_outside_scene", path, "Scene-associated audio must fit within its scene."))

    for scene_id, spans in narration_spans.items():
        ordered = sorted(spans)
        for previous, current in zip(ordered, ordered[1:]):
            if current[0] < previous[1]:
                issues.append(_issue("narration_overlap", f"audioSegments.{current[2]}", "Narration segments in one scene must not overlap."))
    for index, asset in enumerate(package.assets):
        if asset.id not in used_asset_ids:
            issues.append(_issue("asset_unused", f"assets.{index}", "Every declared asset must be referenced by an audio segment."))

    return tuple(sorted(issues, key=lambda item: (item.path, item.code, item.message)))


_SAFE_FIELDS = {
    "contractVersion", "correlationId", "rendererProfileId", "projectId", "brief", "facts", "id",
    "category", "claim", "originalClaim", "revisions", "status", "source", "kind",
    "reference", "pageOrSection", "excerpt", "objective", "targetAudience", "productOrOffer",
    "keyMessage", "valueProposition", "platform", "aspectRatio", "duration", "tone",
    "callToAction", "reliedUponFactIds", "requirementsConfirmed", "scenes", "order", "title",
    "narrativePurpose", "durationFrames", "transitionFromPrevious", "backgroundColor", "elements",
    "type", "x", "y", "width", "height", "style", "align", "content", "text", "factId",
    "shape", "color", "assets", "format", "declaredDurationFrames", "assetVersionId", "audioSegments", "assetId",
    "sceneId", "startFrame", "endFrame", "sourceStartFrame", "transcript", "field",
}


def _safe_error_path(location: tuple[object, ...]) -> str:
    return ".".join(str(part) if isinstance(part, int) else (part if part in _SAFE_FIELDS else "field") for part in location)


def _schema_issues(error: ValidationError) -> tuple[PackageIssue, ...]:
    issues = []
    for item in error.errors():
        location = tuple(item.get("loc", ()))
        first = location[0] if location else None
        code = (
            "unsupported_contract_version" if first == "contractVersion"
            else "unsupported_profile" if first == "rendererProfileId"
            else "invalid_correlation_id" if first == "correlationId"
            else "package_schema_invalid"
        )
        issues.append(_issue(code, _safe_error_path(location), "Value does not match the supported production package contract."))
    return tuple(sorted(issues, key=lambda item: (item.path, item.code, item.message)))


class _DuplicateJsonKey(ValueError):
    pass


def _object_without_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey
        result[key] = value
    return result


def _validate_production_package_v1(value: object) -> ProductionPackageValidation:
    """Validate an already-decoded v1 value without I/O or side effects."""
    correlation_id = _correlation_id_from_value(value)
    contract_version = _explicit_contract_version(value, CONTRACT_VERSION)
    try:
        package = ProductionPackage.model_validate(value)
    except ValidationError as error:
        issues = _schema_issues(error)
        return ProductionPackageValidation(
            False, issues, correlation_id=correlation_id, contract_version=contract_version,
        )
    issues = _cross_reference_issues(package)
    return ProductionPackageValidation(
        not issues,
        issues,
        package if not issues else None,
        package.correlationId,
        contract_version,
    )


def validate_production_package_v2(value: object) -> ProductionPackageV2Validation:
    """Validate a decoded v2 package without I/O or side effects."""
    correlation_id = _correlation_id_from_value(value)
    contract_version = _explicit_contract_version(value, CONTRACT_VERSION_V2)
    try:
        package = ProductionPackageV2.model_validate(value)
    except ValidationError as error:
        issues = _schema_issues(error)
        return ProductionPackageV2Validation(
            False, issues, correlation_id=correlation_id,
            contract_version=contract_version,
        )
    issues = _cross_reference_issues(package)
    return ProductionPackageV2Validation(
        not issues,
        issues,
        package if not issues else None,
        package.correlationId,
        contract_version,
    )


ProductionPackageValidationResult = ProductionPackageValidation | ProductionPackageV2Validation


def validate_production_package(value: object) -> ProductionPackageValidationResult:
    """Dispatch decoded packages by their explicit contract version."""
    if isinstance(value, dict) and value.get("contractVersion") == CONTRACT_VERSION_V2:
        return validate_production_package_v2(value)
    return _validate_production_package_v1(value)


def _validate_decoded_package(value: object) -> ProductionPackageValidationResult:
    return validate_production_package(value)


def validate_production_package_json(raw: str | bytes) -> ProductionPackageValidationResult:
    """Validate bounded JSON bytes/text; callers must enforce ingress limits before buffering."""
    if not isinstance(raw, (str, bytes)):
        return ProductionPackageValidation(False, (_issue("invalid_input_type", "", "The package must be supplied as UTF-8 JSON text or bytes."),))
    try:
        encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    except UnicodeEncodeError:
        return ProductionPackageValidation(False, (_issue("invalid_json", "", "The package is not valid UTF-8 JSON."),))
    if len(encoded) > MAX_PACKAGE_BYTES:
        return ProductionPackageValidation(False, (_issue("payload_too_large", "", "The package exceeds the 65536-byte schema limit."),))
    try:
        decoded = encoded.decode("utf-8")
        value = json.loads(
            decoded,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateJsonKey, ValueError, RecursionError):
        return ProductionPackageValidation(False, (_issue("invalid_json", "", "The package is not valid JSON or contains duplicate keys."),))
    try:
        if _contains_surrogate(value):
            return ProductionPackageValidation(False, (_issue("invalid_unicode", "", "The package contains unsupported Unicode surrogate data."),))
        return _validate_decoded_package(value)
    except RecursionError:
        return ProductionPackageValidation(False, (_issue("invalid_json", "", "The package exceeds the supported validation nesting depth."),))


def _contains_surrogate(value: object) -> bool:
    pending = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, str):
            if any(0xD800 <= ord(character) <= 0xDFFF for character in current):
                return True
        elif isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, dict):
            for key, item in current.items():
                pending.append(key)
                pending.append(item)
    return False
