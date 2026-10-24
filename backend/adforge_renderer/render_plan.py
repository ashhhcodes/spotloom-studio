"""Pure compilation from a validated production package to frame-based instructions.

Compilation preserves the package's declared semantics. It does not resolve assets,
verify claim truth, establish render readiness, or invoke a media renderer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .production_package import (
    CONTRACT_VERSION,
    FPS,
    PROFILE_ID,
    TARGET_FRAMES,
    CONTRACT_VERSION_V2,
    ClaimText,
    CreativeText,
    PackageIssue,
    ProductionPackage,
    ProductionPackageV2,
    ProductionPackageV2Validation,
    ProductionPackageValidation,
    ShapeElement,
    TextElement,
    TextContent,
    validate_production_package,
    validate_production_package_v2,
)


@dataclass(frozen=True)
class RenderProfile:
    profile_id: str
    width: int
    height: int
    frame_rate: int
    total_frames: int
    container: str
    video_codec: str
    pixel_format: str
    audio_codec: str
    audio_sample_rate: int
    audio_channels: int


@dataclass(frozen=True)
class PlannedText:
    classification: Literal["claim", "creative"]
    text: str
    fact_id: str | None


@dataclass(frozen=True)
class TextOperation:
    operation: Literal["text"]
    element_id: str
    x: int
    y: int
    width: int
    height: int
    style: Literal["heading", "body", "caption"]
    align: Literal["left", "center", "right"]
    content: PlannedText


@dataclass(frozen=True)
class ShapeOperation:
    operation: Literal["shape"]
    element_id: str
    x: int
    y: int
    width: int
    height: int
    shape: Literal["circle", "rounded_rectangle", "line"]
    color: str


VisualOperation = TextOperation | ShapeOperation


@dataclass(frozen=True)
class PlannedScene:
    scene_id: str
    order: int
    start_frame: int
    end_frame: int
    duration_frames: int
    title: PlannedText
    narrative_purpose: PlannedText
    transition_from_previous: Literal["none", "cut"]
    background_color: str
    operations: tuple[VisualOperation, ...]


@dataclass(frozen=True)
class PlannedAudioSegment:
    segment_id: str
    role: Literal["narration", "music", "sound_effect"]
    asset_id: str
    scene_id: str | None
    start_frame: int
    end_frame: int
    duration_frames: int
    scene_relative_start_frame: int | None
    scene_relative_end_frame: int | None
    source_start_frame: int
    source_end_frame: int
    transcript: PlannedText | None


@dataclass(frozen=True)
class VersionedPlannedAudioSegment(PlannedAudioSegment):
    """Audio instructions with the immutable package version pin attached."""

    asset_version_id: str


@dataclass(frozen=True)
class PlannedAsset:
    """Package-local asset declaration; identifiers are not resolved here."""

    asset_id: str
    asset_version_id: str
    kind: Literal["audio"]
    format: str
    declared_duration_frames: int


@dataclass(frozen=True)
class PlannedBrief:
    objective: str
    target_audience: PlannedText
    product_or_offer: PlannedText
    key_message: PlannedText
    value_proposition: PlannedText | None
    platform: str
    aspect_ratio: str
    target_duration_seconds: int
    tone: PlannedText
    call_to_action: PlannedText
    relied_upon_fact_ids: tuple[str, ...]
    requirements_confirmed: bool


@dataclass(frozen=True)
class RenderPlan:
    profile: RenderProfile
    brief: PlannedBrief
    scenes: tuple[PlannedScene, ...]
    audio_segments: tuple[PlannedAudioSegment, ...]


@dataclass(frozen=True)
class VersionedRenderPlan:
    project_id: str
    profile: RenderProfile
    brief: PlannedBrief
    assets: tuple[PlannedAsset, ...]
    scenes: tuple[PlannedScene, ...]
    audio_segments: tuple[VersionedPlannedAudioSegment, ...]


@dataclass(frozen=True)
class CompilationDiagnostic:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class RenderPlanCompilation:
    """A complete plan or a failure; never a partial plan."""

    plan: RenderPlan | None
    diagnostics: tuple[CompilationDiagnostic, ...] = ()
    package_issues: tuple[PackageIssue, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.plan is not None and not self.diagnostics and not self.package_issues


@dataclass(frozen=True)
class VersionedRenderPlanCompilation:
    """A complete v2 plan or a failure; never a partial plan."""

    plan: VersionedRenderPlan | None
    diagnostics: tuple[CompilationDiagnostic, ...] = ()
    package_issues: tuple[PackageIssue, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.plan is not None and not self.diagnostics and not self.package_issues


PROFILE = RenderProfile(
    profile_id=PROFILE_ID,
    width=1080,
    height=1920,
    frame_rate=FPS,
    total_frames=TARGET_FRAMES,
    container="mp4",
    video_codec="h264",
    pixel_format="yuv420p",
    audio_codec="aac-lc",
    audio_sample_rate=48_000,
    audio_channels=2,
)


def _planned_text(value: TextContent) -> PlannedText:
    if isinstance(value, ClaimText):
        return PlannedText("claim", value.text, value.factId)
    if isinstance(value, CreativeText):
        return PlannedText("creative", value.text, None)
    raise TypeError("unsupported text classification")


def _compile_visual(element: object, path: str) -> tuple[VisualOperation | None, CompilationDiagnostic | None]:
    if isinstance(element, TextElement):
        try:
            return TextOperation(
                operation="text",
                element_id=element.id,
                x=element.x,
                y=element.y,
                width=element.width,
                height=element.height,
                style=element.style,
                align=element.align,
                content=_planned_text(element.content),
            ), None
        except TypeError:
            return None, CompilationDiagnostic(
                code="unsupported_text_classification",
                path=f"{path}.content",
                message="The text classification is not supported by this render-plan compiler.",
            )
    if isinstance(element, ShapeElement):
        return ShapeOperation(
            operation="shape",
            element_id=element.id,
            x=element.x,
            y=element.y,
            width=element.width,
            height=element.height,
            shape=element.shape,
            color=element.color,
        ), None
    return None, CompilationDiagnostic(
        code="unsupported_visual_instruction",
        path=path,
        message="The visual instruction is not supported by this render-plan compiler.",
    )


def compile_render_plan(validation: ProductionPackageValidation) -> RenderPlanCompilation:
    """Compile a successful package-validation result without side effects.

    Package/schema/cross-reference issues are returned separately in
    ``package_issues``. Compiler-only failures use ``diagnostics``.
    """
    if not isinstance(validation, ProductionPackageValidation):
        return RenderPlanCompilation(
            None,
            (CompilationDiagnostic(
                "invalid_validation_result", "",
                "A production-package validation result is required.",
            ),),
        )
    if not validation.valid:
        if validation.issues:
            return RenderPlanCompilation(None, package_issues=validation.issues)
        return RenderPlanCompilation(None, (CompilationDiagnostic(
            "inconsistent_validation_result", "",
            "A failed package-validation result must contain validation issues.",
        ),))
    if validation.package is None:
        return RenderPlanCompilation(None, (CompilationDiagnostic(
            "inconsistent_validation_result", "",
            "A successful package-validation result must contain a validated package.",
        ),))
    if validation.contract_version != CONTRACT_VERSION or type(validation.package) is not ProductionPackage:
        return RenderPlanCompilation(None, (CompilationDiagnostic(
            "unsupported_contract_version", "contractVersion",
            "The legacy render-plan compiler accepts only explicitly validated v1 packages.",
        ),))

    # Pydantic's frozen models contain mutable lists. Reuse the package validator
    # so a caller-mutated validation result cannot bypass schema/cross-reference checks.
    current_validation = validate_production_package(
        validation.package.model_dump(mode="python")
    )
    if not current_validation.valid or current_validation.package is None:
        return RenderPlanCompilation(None, package_issues=current_validation.issues)
    if (
        not isinstance(current_validation, ProductionPackageValidation)
        or current_validation.contract_version != CONTRACT_VERSION
        or type(current_validation.package) is not ProductionPackage
    ):
        return RenderPlanCompilation(None, (CompilationDiagnostic(
            "unsupported_contract_version", "contractVersion",
            "The legacy render-plan compiler accepts only explicitly validated v1 packages.",
        ),))

    return _compile_package_contents(current_validation.package)


def _compile_package_contents(package: ProductionPackage | ProductionPackageV2) -> RenderPlanCompilation:
    """Compile common v1/v2 package content after version-specific validation."""
    diagnostics: list[CompilationDiagnostic] = []
    scenes: list[PlannedScene] = []
    scene_bounds: dict[str, tuple[int, int]] = {}
    cursor = 0
    for index, scene in enumerate(package.scenes):
        start = cursor
        end = start + scene.durationFrames
        path = f"scenes.{index}"
        if scene.durationFrames <= 0 or start < 0 or end > PROFILE.total_frames:
            diagnostics.append(CompilationDiagnostic(
                "scene_timing_out_of_bounds", f"{path}.durationFrames",
                "Scene timing must be positive and remain within the profile timeline.",
            ))
        operations: list[VisualOperation] = []
        for element_index, element in enumerate(scene.elements):
            operation, issue = _compile_visual(element, f"{path}.elements.{element_index}")
            if issue is not None:
                diagnostics.append(issue)
            elif operation is not None:
                operations.append(operation)
        scene_bounds.setdefault(scene.id, (start, end))
        try:
            title = _planned_text(scene.title)
            narrative_purpose = _planned_text(scene.narrativePurpose)
        except TypeError:
            diagnostics.append(CompilationDiagnostic(
                "unsupported_text_classification", path,
                "A scene text classification is not supported by this compiler.",
            ))
        else:
            scenes.append(PlannedScene(
                scene_id=scene.id,
                order=scene.order,
                start_frame=start,
                end_frame=end,
                duration_frames=scene.durationFrames,
                title=title,
                narrative_purpose=narrative_purpose,
                transition_from_previous=scene.transitionFromPrevious,
                background_color=scene.backgroundColor,
                operations=tuple(operations),
            ))
        cursor = end
    if cursor != PROFILE.total_frames:
        diagnostics.append(CompilationDiagnostic(
            "timeline_total_mismatch", "scenes",
            "Compiled scene intervals must cover exactly 360 frames.",
        ))

    audio_segments: list[PlannedAudioSegment] = []
    for index, segment in enumerate(package.audioSegments):
        duration = segment.endFrame - segment.startFrame
        scene_start: int | None = None
        relative_start: int | None = None
        relative_end: int | None = None
        if segment.sceneId is not None:
            bounds = scene_bounds.get(segment.sceneId)
            if bounds is None:
                diagnostics.append(CompilationDiagnostic(
                    "audio_scene_missing", f"audioSegments.{index}.sceneId",
                    "Scene-associated audio must reference a compiled scene.",
                ))
            else:
                scene_start, scene_end = bounds
                if segment.startFrame < scene_start or segment.endFrame > scene_end:
                    diagnostics.append(CompilationDiagnostic(
                        "audio_outside_scene", f"audioSegments.{index}",
                        "Scene-associated audio must fit within its scene interval.",
                    ))
                relative_start = segment.startFrame - scene_start
                relative_end = segment.endFrame - scene_start
        if segment.startFrame < 0 or segment.endFrame > PROFILE.total_frames or duration <= 0:
            diagnostics.append(CompilationDiagnostic(
                "audio_timing_out_of_bounds", f"audioSegments.{index}",
                "Audio timing must be positive and remain within the profile timeline.",
            ))
        try:
            transcript = _planned_text(segment.transcript) if segment.transcript is not None else None
        except TypeError:
            transcript = None
            diagnostics.append(CompilationDiagnostic(
                "unsupported_text_classification", f"audioSegments.{index}.transcript",
                "The transcript classification is not supported by this compiler.",
            ))
        audio_segments.append(PlannedAudioSegment(
            segment_id=segment.id,
            role=segment.kind,
            asset_id=segment.assetId,
            scene_id=segment.sceneId,
            start_frame=segment.startFrame,
            end_frame=segment.endFrame,
            duration_frames=duration,
            scene_relative_start_frame=relative_start,
            scene_relative_end_frame=relative_end,
            source_start_frame=segment.sourceStartFrame,
            source_end_frame=segment.sourceStartFrame + duration,
            transcript=transcript,
        ))

    if diagnostics:
        ordered = tuple(sorted(diagnostics, key=lambda item: (item.path, item.code, item.message)))
        return RenderPlanCompilation(None, ordered)

    brief = package.brief
    try:
        planned_brief = PlannedBrief(
            objective=brief.objective,
            target_audience=_planned_text(brief.targetAudience),
            product_or_offer=_planned_text(brief.productOrOffer),
            key_message=_planned_text(brief.keyMessage),
            value_proposition=_planned_text(brief.valueProposition) if brief.valueProposition is not None else None,
            platform=brief.platform,
            aspect_ratio=brief.aspectRatio,
            target_duration_seconds=brief.duration,
            tone=_planned_text(brief.tone),
            call_to_action=_planned_text(brief.callToAction),
            relied_upon_fact_ids=tuple(brief.reliedUponFactIds),
            requirements_confirmed=brief.requirementsConfirmed,
        )
    except TypeError:
        return RenderPlanCompilation(None, (CompilationDiagnostic(
            "unsupported_text_classification", "brief",
            "A brief text classification is not supported by this compiler.",
        ),))

    return RenderPlanCompilation(
        RenderPlan(
            profile=PROFILE,
            brief=planned_brief,
            scenes=tuple(scenes),
            audio_segments=tuple(audio_segments),
        )
    )


def compile_versioned_render_plan(
    validation: ProductionPackageV2Validation,
) -> VersionedRenderPlanCompilation:
    """Compile a successful v2 validation result while preserving asset pins.

    The compiler revalidates the package because Pydantic's frozen models still
    contain mutable lists. It performs no asset lookup or other I/O.
    """
    if not isinstance(validation, ProductionPackageV2Validation):
        return VersionedRenderPlanCompilation(None, (CompilationDiagnostic(
            "invalid_validation_result", "",
            "A v2 production-package validation result is required.",
        ),))
    if validation.contract_version != CONTRACT_VERSION_V2:
        return VersionedRenderPlanCompilation(None, (CompilationDiagnostic(
            "unsupported_contract_version", "contractVersion",
            "The validation result does not identify the supported v2 contract.",
        ),))
    if not validation.valid:
        if validation.issues:
            return VersionedRenderPlanCompilation(None, package_issues=validation.issues)
        return VersionedRenderPlanCompilation(None, (CompilationDiagnostic(
            "inconsistent_validation_result", "",
            "A failed package-validation result must contain validation issues.",
        ),))
    if validation.issues or not isinstance(validation.package, ProductionPackageV2):
        return VersionedRenderPlanCompilation(None, (CompilationDiagnostic(
            "inconsistent_validation_result", "",
            "A successful v2 validation result must contain a validated package without issues.",
        ),))

    current_validation = validate_production_package_v2(
        validation.package.model_dump(mode="python")
    )
    if not current_validation.valid or current_validation.package is None:
        return VersionedRenderPlanCompilation(None, package_issues=current_validation.issues)
    package = current_validation.package
    if current_validation.contract_version != CONTRACT_VERSION_V2:
        return VersionedRenderPlanCompilation(None, (CompilationDiagnostic(
            "unsupported_contract_version", "contractVersion",
            "The package does not select the supported v2 contract.",
        ),))

    common = _compile_package_contents(package)
    if not common.succeeded or common.plan is None:
        return VersionedRenderPlanCompilation(
            None, diagnostics=common.diagnostics, package_issues=common.package_issues,
        )

    assets_by_id = {asset.id: asset for asset in package.assets}
    if len(assets_by_id) != len(package.assets):
        return VersionedRenderPlanCompilation(None, (CompilationDiagnostic(
            "asset_reference_inconsistent", "assets",
            "Asset declarations must have unique package-local identifiers.",
        ),))

    versioned_audio: list[VersionedPlannedAudioSegment] = []
    for index, segment in enumerate(common.plan.audio_segments):
        asset = assets_by_id.get(segment.asset_id)
        if asset is None:
            return VersionedRenderPlanCompilation(None, (CompilationDiagnostic(
                "asset_reference_inconsistent", f"audioSegments.{index}.assetId",
                "Audio segment must reference exactly one declared package asset.",
            ),))
        versioned_audio.append(VersionedPlannedAudioSegment(
            segment_id=segment.segment_id,
            role=segment.role,
            asset_id=segment.asset_id,
            scene_id=segment.scene_id,
            start_frame=segment.start_frame,
            end_frame=segment.end_frame,
            duration_frames=segment.duration_frames,
            scene_relative_start_frame=segment.scene_relative_start_frame,
            scene_relative_end_frame=segment.scene_relative_end_frame,
            source_start_frame=segment.source_start_frame,
            source_end_frame=segment.source_end_frame,
            transcript=segment.transcript,
            asset_version_id=asset.assetVersionId,
        ))

    planned_assets = tuple(PlannedAsset(
        asset_id=asset.id,
        asset_version_id=asset.assetVersionId,
        kind=asset.kind,
        format=asset.format,
        declared_duration_frames=asset.declaredDurationFrames,
    ) for asset in package.assets)
    common_plan = common.plan
    return VersionedRenderPlanCompilation(VersionedRenderPlan(
        project_id=package.projectId,
        profile=common_plan.profile,
        brief=common_plan.brief,
        assets=planned_assets,
        scenes=common_plan.scenes,
        audio_segments=tuple(versioned_audio),
    ))
