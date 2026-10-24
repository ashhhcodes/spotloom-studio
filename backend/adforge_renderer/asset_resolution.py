"""Pure matching of version-pinned render plans to caller-supplied asset values.

This module is deliberately not a trust boundary. ``VersionedRenderPlan`` and
``AssetVersionRecord`` instances can be constructed by ordinary application
code. Matching their fields does not prove compiler provenance, authorization,
storage availability, or that a digest was computed from media bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from pydantic import ValidationError

from .asset_contract import (
    ASSET_FORMAT,
    AssetDeclaration,
    AssetLeaseRequest,
    LeaseAssetPin,
    AssetValidationEvidence,
    ManagedAsset,
    ObservedAudioMetadata,
    PrivateObjectVersionReference,
    _evidence_matches_asset,
    validate_asset_declaration,
    validate_asset_validation_evidence,
    validate_observed_audio_metadata,
)
from .production_package import PROFILE_ID
from .render_plan import (
    PROFILE,
    PlannedAsset,
    RenderPlan,
    RenderProfile,
    VersionedPlannedAudioSegment,
    VersionedRenderPlan,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class AssetVersionRecord:
    """Caller-supplied immutable values for one managed asset version.

    ``content_digest`` is intentionally separate from the evidence's observed
    digest so the matcher can detect disagreement between supplied fields. It
    is still only caller-supplied data, not a trusted observation.
    """

    asset: ManagedAsset
    content_digest: str
    object_version: PrivateObjectVersionReference | None = None


@dataclass(frozen=True)
class ResolvedAsset:
    asset_id: str
    asset_version_id: str
    sha256: str
    profile_id: str
    declared_duration_frames: int
    object_version: PrivateObjectVersionReference | None = None


@dataclass(frozen=True)
class AssetResolutionSnapshot:
    project_id: str
    profile_id: str
    assets: tuple[ResolvedAsset, ...]


@dataclass(frozen=True)
class AssetResolutionIssue:
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class AssetResolutionResult:
    snapshot: AssetResolutionSnapshot | None
    issues: tuple[AssetResolutionIssue, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.snapshot is not None and not self.issues


@dataclass(frozen=True)
class LeaseResolutionBindingResult:
    """Pure equality result; never proves authorization or a real lease."""

    matches: bool
    issues: tuple[AssetResolutionIssue, ...] = ()


def _issue(code: str, path: str, message: str) -> AssetResolutionIssue:
    return AssetResolutionIssue(code, path, message)


def _ordered(issues: list[AssetResolutionIssue]) -> tuple[AssetResolutionIssue, ...]:
    return tuple(sorted(set(issues), key=lambda item: (item.path, item.code, item.message)))


def bind_lease_request_to_resolution(
    snapshot: AssetResolutionSnapshot,
    request: AssetLeaseRequest,
) -> LeaseResolutionBindingResult:
    """Require a complete, exact pin-set match with a caller-supplied snapshot.

    The comparison does not establish snapshot provenance, project
    authorization, object availability, or that a lease has been acquired.
    """
    if type(snapshot) is not AssetResolutionSnapshot or type(request) is not AssetLeaseRequest:
        return LeaseResolutionBindingResult(False, (_issue(
            "invalid_lease_binding", "", "Lease request or resolution snapshot is invalid.",
        ),))
    try:
        request = AssetLeaseRequest.model_validate(request.model_dump(mode="python", warnings=False))
    except (ValidationError, TypeError, ValueError):
        return LeaseResolutionBindingResult(False, (_issue(
            "invalid_lease_binding", "request", "Lease request or resolution snapshot is invalid.",
        ),))
    if type(snapshot.assets) is not tuple or not isinstance(snapshot.project_id, str):
        return LeaseResolutionBindingResult(False, (_issue(
            "invalid_lease_binding", "snapshot", "Lease request or resolution snapshot is invalid.",
        ),))
    if snapshot.profile_id != PROFILE_ID:
        return LeaseResolutionBindingResult(False, (_issue(
            "unsupported_resolution_profile", "profile_id", "Resolution profile is not supported for a lease.",
        ),))
    if request.project_id != snapshot.project_id:
        return LeaseResolutionBindingResult(False, (_issue(
            "lease_project_mismatch", "project_id", "Lease and resolution project identifiers must match.",
        ),))

    snapshot_by_id: dict[str, ResolvedAsset] = {}
    issues: list[AssetResolutionIssue] = []
    for index, resolved in enumerate(snapshot.assets):
        if type(resolved) is not ResolvedAsset:
            issues.append(_issue("invalid_resolution_asset", f"snapshot.assets.{index}", "Resolution asset is invalid."))
            continue
        if not isinstance(resolved.asset_id, str) or not resolved.asset_id:
            issues.append(_issue("invalid_resolution_asset", f"snapshot.assets.{index}", "Resolution asset is invalid."))
            continue
        if resolved.asset_id in snapshot_by_id:
            issues.append(_issue("duplicate_resolution_asset", f"snapshot.assets.{index}", "Resolution asset identifiers must be unique."))
            continue
        if resolved.object_version is None or type(resolved.object_version) is not PrivateObjectVersionReference:
            issues.append(_issue("resolution_object_version_missing", f"snapshot.assets.{index}", "Every lease pin requires a complete resolution binding."))
            continue
        try:
            object_version = PrivateObjectVersionReference.model_validate(
                resolved.object_version.model_dump(mode="python", warnings=False),
            )
            LeaseAssetPin.model_validate({
                "asset_id": resolved.asset_id,
                "asset_version_id": resolved.asset_version_id,
                "object_version": object_version.model_dump(mode="python", warnings=False),
                "sha256": resolved.sha256,
                "profile_id": resolved.profile_id,
                "declared_duration_frames": resolved.declared_duration_frames,
            })
        except (ValidationError, TypeError, ValueError):
            issues.append(_issue("invalid_resolution_asset", f"snapshot.assets.{index}", "Resolution asset is invalid."))
            continue
        if object_version != resolved.object_version:
            issues.append(_issue("invalid_resolution_asset", f"snapshot.assets.{index}", "Resolution asset is invalid."))
            continue
        snapshot_by_id[resolved.asset_id] = resolved

    request_by_id = {pin.asset_id: pin for pin in request.assets}
    for asset_id in snapshot_by_id.keys() - request_by_id.keys():
        issues.append(_issue("lease_pin_missing", "assets", "The lease request is missing a resolved asset pin."))
    for asset_id in request_by_id.keys() - snapshot_by_id.keys():
        issues.append(_issue("lease_pin_extra", "assets", "The lease request contains an undeclared asset pin."))
    for index, pin in enumerate(request.assets):
        resolved = snapshot_by_id.get(pin.asset_id)
        if resolved is None:
            continue
        if (
            pin.asset_version_id != resolved.asset_version_id
            or pin.object_version != resolved.object_version
            or pin.sha256 != resolved.sha256
            or pin.profile_id != resolved.profile_id
            or pin.declared_duration_frames != resolved.declared_duration_frames
        ):
            issues.append(_issue("lease_pin_mismatch", f"assets.{index}", "Lease pin does not match the resolved asset version."))
    return LeaseResolutionBindingResult(not issues, _ordered(issues))


def _revalidate_asset(record: AssetVersionRecord) -> tuple[ManagedAsset | None, str | None]:
    """Rebuild supplied nested values through the existing strict validators."""
    if type(record) is not AssetVersionRecord or type(record.asset) is not ManagedAsset:
        return None, "invalid_asset_record"
    source = record.asset
    if type(source.declaration) is not AssetDeclaration:
        return None, "invalid_asset_record"
    if record.object_version is not None:
        if type(record.object_version) is not PrivateObjectVersionReference:
            return None, "invalid_object_version"
        try:
            PrivateObjectVersionReference.model_validate(record.object_version.model_dump(mode="python"))
        except (ValidationError, TypeError, ValueError):
            return None, "invalid_object_version"

    declaration_result = validate_asset_declaration(source.declaration.model_dump(mode="python"))
    if not declaration_result.valid or declaration_result.value is None:
        return None, "invalid_asset_metadata"

    evidence: AssetValidationEvidence | None = None
    if source.validation is not None:
        if type(source.validation) is not AssetValidationEvidence or type(source.validation.observed) is not ObservedAudioMetadata:
            return None, "invalid_validation_evidence"
        observed_result = validate_observed_audio_metadata(source.validation.observed.model_dump(mode="python"))
        evidence_result = validate_asset_validation_evidence(source.validation.model_dump(mode="python"))
        if not observed_result.valid or not evidence_result.valid or evidence_result.value is None:
            return None, "invalid_validation_evidence"
        evidence = evidence_result.value

    if source.state not in {
        "uploading", "quarantined", "validating", "ready", "failed", "rejected",
        "deletion_pending", "deleted", "expired",
    }:
        return None, "invalid_asset_state"
    try:
        rebuilt = ManagedAsset(
            declaration_result.value,
            source.asset_version_id,
            state=source.state,
            validation=evidence,
        )
    except (TypeError, ValueError):
        return None, "invalid_asset_record"
    if not isinstance(record.content_digest, str) or not _SHA256.fullmatch(record.content_digest):
        return None, "invalid_asset_digest"
    if evidence is None:
        return rebuilt, "validation_evidence_missing"
    if evidence.observed.sha256 != record.content_digest:
        return rebuilt, "asset_digest_mismatch"
    if not _evidence_matches_asset(rebuilt.declaration, rebuilt.asset_version_id, evidence):
        return rebuilt, "validation_evidence_mismatch"
    return rebuilt, None


def resolve_versioned_assets(
    plan: VersionedRenderPlan,
    records: tuple[AssetVersionRecord, ...],
) -> AssetResolutionResult:
    """Match every plan pin to exactly one ready supplied version record.

    This checks policy-consistent caller values only. The result is not safe to
    use as authorization or proof of storage availability for a render job.
    """
    if type(plan) is not VersionedRenderPlan:
        code = "legacy_plan_unsupported" if type(plan) is RenderPlan else "invalid_plan_type"
        return AssetResolutionResult(None, (_issue(
            code, "plan", "A version-pinned v2 render plan is required.",
        ),))
    if type(records) is not tuple:
        return AssetResolutionResult(None, (_issue(
            "invalid_records_type", "records", "Asset version records must be provided as an immutable tuple.",
        ),))

    issues: list[AssetResolutionIssue] = []
    if type(plan.profile) is not RenderProfile or plan.profile != PROFILE or plan.profile.profile_id != PROFILE_ID:
        issues.append(_issue("unsupported_profile", "profile", "The render plan profile is not supported."))
    project_check = validate_asset_declaration({
        "asset_id": "ast_validation_0001",
        "project_id": plan.project_id,
        "kind": "audio",
        "declared_format": ASSET_FORMAT,
        "declared_duration_frames": 1,
    }) if isinstance(plan.project_id, str) else None
    if project_check is None or not project_check.valid:
        issues.append(_issue("invalid_plan_project", "project_id", "The render plan project identifier is invalid."))
    if type(plan.assets) is not tuple or type(plan.audio_segments) is not tuple:
        issues.append(_issue("invalid_plan_structure", "", "The render plan collections are invalid."))
        return AssetResolutionResult(None, _ordered(issues))
    if any(type(asset) is not PlannedAsset for asset in plan.assets):
        issues.append(_issue("invalid_plan_asset", "assets", "The render plan asset declarations are invalid."))
    if any(type(segment) is not VersionedPlannedAudioSegment for segment in plan.audio_segments):
        issues.append(_issue("invalid_plan_segment", "audio_segments", "The render plan audio references are invalid."))

    assets_by_id: dict[str, PlannedAsset] = {}
    for index, asset in enumerate(plan.assets):
        if type(asset) is not PlannedAsset:
            continue
        if not isinstance(asset.asset_id, str) or not asset.asset_id or not isinstance(asset.asset_version_id, str) or not asset.asset_version_id:
            issues.append(_issue("invalid_plan_asset", f"assets.{index}", "The render plan asset declaration is invalid."))
            continue
        if asset.asset_id in assets_by_id:
            issues.append(_issue("duplicate_plan_asset", f"assets.{index}", "Render plan asset identifiers must be unique."))
        else:
            assets_by_id[asset.asset_id] = asset

    records_by_id: dict[str, ManagedAsset] = {}
    digest_by_id: dict[str, str] = {}
    object_version_by_id: dict[str, PrivateObjectVersionReference | None] = {}
    for index, record in enumerate(records):
        if type(record) is not AssetVersionRecord:
            issues.append(_issue("invalid_asset_record", f"records.{index}", "An asset version record is invalid."))
            continue
        if type(record.asset) is not ManagedAsset:
            issues.append(_issue("invalid_asset_record", f"records.{index}", "An asset version record is invalid."))
            continue
        asset_id = getattr(getattr(record.asset, "declaration", None), "asset_id", None)
        rebuilt, error = _revalidate_asset(record)
        if rebuilt is None:
            issues.append(_issue(error or "invalid_asset_record", f"records.{index}", "An asset version record is invalid."))
            continue
        if not isinstance(asset_id, str) or not asset_id:
            issues.append(_issue("invalid_asset_record", f"records.{index}", "An asset version record is invalid."))
            continue
        if asset_id in records_by_id:
            issues.append(_issue("duplicate_asset_record", f"records.{index}", "Asset version records must be unique per asset."))
            continue
        records_by_id[asset_id] = rebuilt
        digest_by_id[asset_id] = record.content_digest if isinstance(record.content_digest, str) else ""
        object_version_by_id[asset_id] = record.object_version
        if error is not None:
            code = error
            message = {
                "asset_digest_mismatch": "The supplied digest does not match the validation evidence.",
                "validation_evidence_missing": "Matching validation evidence is required for the asset version.",
                "validation_evidence_mismatch": "Validation evidence does not match the declared asset version.",
                "invalid_asset_digest": "The asset digest does not match the supported format.",
                "invalid_validation_evidence": "Validation evidence does not match the supported contract.",
                "invalid_asset_metadata": "Asset metadata does not match the supported contract.",
                "invalid_asset_state": "The asset lifecycle state is invalid.",
            }.get(code, "An asset version record is invalid.")
            issues.append(_issue(code, f"records.{index}", message))
        if rebuilt.state != "ready":
            issues.append(_issue("asset_not_ready", f"records.{index}.state", "Every referenced asset version must be ready."))
        if rebuilt.declaration.project_id != plan.project_id:
            issues.append(_issue("project_mismatch", f"records.{index}.project_id", "Asset and plan project identifiers must match."))

    for asset_id in records_by_id.keys() - assets_by_id.keys():
        issues.append(_issue("unexpected_asset_record", "records", "Every supplied asset record must match a plan declaration."))
    for index, planned in enumerate(plan.assets):
        if type(planned) is not PlannedAsset:
            continue
        record = records_by_id.get(planned.asset_id)
        if record is None:
            issues.append(_issue("missing_asset_record", f"assets.{index}", "A plan asset has no matching version record."))
            continue
        if record.asset_version_id != planned.asset_version_id:
            issues.append(_issue("version_mismatch", f"assets.{index}", "The asset version does not match the pinned plan version."))
        if record.declaration.kind != planned.kind or record.declaration.declared_format != planned.format or record.declaration.declared_duration_frames != planned.declared_duration_frames:
            issues.append(_issue("asset_metadata_mismatch", f"assets.{index}", "Asset metadata does not match the plan declaration."))

    for index, segment in enumerate(plan.audio_segments):
        if type(segment) is not VersionedPlannedAudioSegment:
            continue
        if (
            not isinstance(segment.asset_id, str) or not segment.asset_id
            or not isinstance(segment.asset_version_id, str) or not segment.asset_version_id
        ):
            issues.append(_issue("invalid_plan_segment", f"audio_segments.{index}", "The render plan audio reference is invalid."))
            continue
        planned = assets_by_id.get(segment.asset_id)
        if planned is None:
            issues.append(_issue("segment_asset_missing", f"audio_segments.{index}.asset_id", "Every audio reference must identify one declared plan asset."))
        elif planned.asset_version_id != segment.asset_version_id:
            issues.append(_issue("segment_version_mismatch", f"audio_segments.{index}.asset_version_id", "The audio reference version must match its plan declaration."))
        record = records_by_id.get(segment.asset_id)
        if record is None:
            issues.append(_issue("segment_record_missing", f"audio_segments.{index}.asset_id", "Every audio reference must match a supplied asset version record."))
        elif record.asset_version_id != segment.asset_version_id:
            issues.append(_issue("segment_version_mismatch", f"audio_segments.{index}.asset_version_id", "The audio reference version must match its supplied asset record."))

    if issues:
        return AssetResolutionResult(None, _ordered(issues))

    snapshot = AssetResolutionSnapshot(
        project_id=plan.project_id,
        profile_id=plan.profile.profile_id,
        assets=tuple(ResolvedAsset(
            asset_id=asset.asset_id,
            asset_version_id=asset.asset_version_id,
            sha256=digest_by_id[asset.asset_id],
            profile_id=plan.profile.profile_id,
            declared_duration_frames=asset.declared_duration_frames,
            object_version=object_version_by_id[asset.asset_id],
        ) for asset in plan.assets),
    )
    return AssetResolutionResult(snapshot)
