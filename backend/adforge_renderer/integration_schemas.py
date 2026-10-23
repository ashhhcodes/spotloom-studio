"""Typed, side-effect-free schemas for a future frontend/backend contract.

These models validate structure and bounds only. They do not verify claims,
authorize review decisions, fetch URLs, or perform generation/rendering work.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Sequence
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)


ReviewStatus = Literal["unreviewed", "approved", "rejected"]
SourceKind = Literal["illustrative-placeholder", "manual", "website", "model_suggestion"]
CampaignObjective = Literal["awareness", "engagement", "traffic", "conversions"]
CampaignPlatform = Literal["instagram", "tiktok", "youtube", "other"]
BriefAspectRatio = Literal["9:16", "1:1", "16:9"]
BriefDurationValue = Literal[15, 30, 60]
_FACT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")


class _ContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        use_enum_values=True,
    )


class ClaimSource(_ContractModel):
    """Provenance description mapped from the frontend source placeholder."""

    kind: SourceKind
    reference: StrictStr = Field(min_length=1, max_length=2048)
    pageOrSection: StrictStr = Field(min_length=1, max_length=240)
    excerpt: StrictStr | None = Field(max_length=240)

    @model_validator(mode="after")
    def validate_website_reference(self) -> ClaimSource:
        if not self.reference.strip() or not self.pageOrSection.strip():
            raise ValueError("source reference and page/section must contain non-whitespace text")
        if self.kind == "website":
            try:
                parsed = urlsplit(self.reference)
                valid = (
                    parsed.scheme.lower() in {"http", "https"}
                    and bool(parsed.hostname)
                    and parsed.username is None
                    and parsed.password is None
                    and (parsed.port is None or 1 <= parsed.port <= 65535)
                    and "\\" not in parsed.netloc
                    and not any(character.isspace() or ord(character) < 33 for character in self.reference)
                    and bool(parsed.hostname.encode("idna"))
                )
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("website source reference must be an absolute HTTP(S) URL without credentials")
        return self


class BusinessClaim(_ContractModel):
    """Frontend-shaped claim; status records review state, not factual truth."""

    id: StrictStr = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    category: StrictStr = Field(min_length=1, max_length=80)
    claim: StrictStr = Field(min_length=1, max_length=240)
    originalClaim: StrictStr = Field(min_length=1, max_length=240)
    revisions: list[StrictStr] = Field(max_length=20)
    status: ReviewStatus
    source: ClaimSource

    @field_validator("category", "claim", "originalClaim")
    @classmethod
    def require_nonblank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must contain non-whitespace text")
        return value

    @field_validator("revisions")
    @classmethod
    def validate_revisions(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 240 for value in values):
            raise ValueError("revision text must be nonblank and at most 240 characters")
        return values


class BusinessClaims(_ContractModel):
    facts: list[BusinessClaim] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_fact_ids(self) -> BusinessClaims:
        ids = [fact.id for fact in self.facts]
        if len(ids) != len(set(ids)):
            raise ValueError("fact IDs must be unique")
        return self


class CreativeBrief(_ContractModel):
    objective: CampaignObjective
    targetAudience: StrictStr = Field(min_length=1, max_length=500)
    productOrOffer: StrictStr = Field(min_length=1, max_length=500)
    keyMessage: StrictStr = Field(min_length=1, max_length=500)
    valueProposition: StrictStr = Field(max_length=500)
    platform: CampaignPlatform
    aspectRatio: BriefAspectRatio
    duration: BriefDurationValue
    tone: StrictStr = Field(min_length=1, max_length=500)
    callToAction: StrictStr = Field(min_length=1, max_length=500)
    reliedUponFactIds: list[StrictStr] = Field(max_length=32)
    requirementsConfirmed: StrictBool

    @field_validator("targetAudience", "productOrOffer", "keyMessage", "tone", "callToAction")
    @classmethod
    def require_nonblank_required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("required text must contain non-whitespace characters")
        return value

    @field_validator("reliedUponFactIds")
    @classmethod
    def validate_fact_references(cls, values: list[str]) -> list[str]:
        if any(not _FACT_ID.fullmatch(value) for value in values):
            raise ValueError("fact references must use the supported fact ID format")
        if len(values) != len(set(values)):
            raise ValueError("fact references must be unique")
        return values


class StoryboardScene(_ContractModel):
    id: StrictStr = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    title: StrictStr = Field(min_length=1, max_length=120)
    narrativePurpose: StrictStr = Field(max_length=500)
    visualDirection: StrictStr = Field(max_length=1000)
    onScreenText: StrictStr = Field(max_length=500)
    narration: StrictStr = Field(max_length=1000)
    durationSeconds: StrictInt = Field(ge=1, le=60)
    transitionNote: StrictStr = Field(max_length=500)

    @field_validator("title")
    @classmethod
    def require_nonblank_title(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("scene title must contain non-whitespace text")
        return value


class StoryboardInput(_ContractModel):
    scenes: list[StoryboardScene] = Field(max_length=32)

    @model_validator(mode="after")
    def unique_scene_ids(self) -> StoryboardInput:
        ids = [scene.id for scene in self.scenes]
        if len(ids) != len(set(ids)):
            raise ValueError("scene IDs must be unique")
        return self


class PreproductionValidationRequest(_ContractModel):
    """Strict request envelope; nested contracts are validated by the pure helper."""

    facts: dict[str, object]
    brief: dict[str, object]
    storyboard: dict[str, object]


@dataclass(frozen=True)
class ValidationIssue:
    """Sanitized, deterministic validation issue without rejected input values."""

    path: str
    code: str
    message: str


@dataclass(frozen=True)
class ContractValidationResult:
    valid: bool
    issues: tuple[ValidationIssue, ...]
    plannedRuntimeSeconds: int | None


_ALLOWED_ERROR_FIELDS = {
    "facts", "id", "category", "claim", "originalClaim", "revisions", "status", "source",
    "kind", "reference", "pageOrSection", "excerpt", "objective", "targetAudience",
    "productOrOffer", "keyMessage", "valueProposition", "platform", "aspectRatio", "duration",
    "tone", "callToAction", "reliedUponFactIds", "requirementsConfirmed", "scenes",
    "title", "narrativePurpose", "visualDirection", "onScreenText", "narration",
    "durationSeconds", "transitionNote",
}


def _schema_issues(error: ValidationError, prefix: str) -> tuple[ValidationIssue, ...]:
    issues = []
    for item in error.errors():
        safe_location = [
            str(part) if isinstance(part, int) else (part if part in _ALLOWED_ERROR_FIELDS else "extra_field")
            for part in item["loc"]
        ]
        location = ".".join(safe_location)
        issues.append(ValidationIssue(
            path=f"{prefix}.{location}" if location else prefix,
            code=str(item["type"]),
            message="Value does not match the supported contract.",
        ))
    return tuple(issues)


def calculate_storyboard_runtime(scenes: Sequence[object]) -> int | None:
    """Return a complete runtime, or None for empty/invalid scene collections."""
    try:
        validated = StoryboardInput.model_validate({"scenes": list(scenes)})
    except (ValidationError, TypeError):
        return None
    if not validated.scenes:
        return None
    return sum(scene.durationSeconds for scene in validated.scenes)


def validate_contract_input(*, facts: object, brief: object, storyboard: object) -> ContractValidationResult:
    """Validate caller-supplied Python/JSON-shaped data without I/O or side effects.

    An empty storyboard is structurally valid, but its runtime is unavailable.
    The brief's requirementsConfirmed value is validated as a boolean and retained
    as a separate human signal; this function does not treat it as fact verification.
    """
    issues: list[ValidationIssue] = []
    try:
        BusinessClaims.model_validate(facts)
    except ValidationError as error:
        issues.extend(_schema_issues(error, "facts"))
    try:
        CreativeBrief.model_validate(brief)
    except ValidationError as error:
        issues.extend(_schema_issues(error, "brief"))
    try:
        validated_storyboard = StoryboardInput.model_validate(storyboard)
        runtime = calculate_storyboard_runtime(validated_storyboard.scenes)
    except ValidationError as error:
        issues.extend(_schema_issues(error, "storyboard"))
        runtime = None
    return ContractValidationResult(not issues, tuple(issues), runtime)
