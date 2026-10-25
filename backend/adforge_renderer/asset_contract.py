"""Pure domain types for future managed audio assets.

These models describe declarations and possible validation observations. They do
not store, inspect, authorize, or verify media. In particular, Python objects
and identifiers from this module are not a security or trust boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError, field_validator, model_validator

from .production_package import PROFILE_ID


ASSET_FORMAT = "wav-pcm-s16le-48000-stereo"
MAX_DECLARED_DURATION_FRAMES = 86_400

_ASSET_ID = re.compile(r"^ast_[A-Za-z0-9_-]{8,80}$")
_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_OWNER_ID = _PROJECT_ID
_ASSET_VERSION_ID = re.compile(r"^ver_[A-Za-z0-9_-]{8,80}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_VALIDATOR_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class AssetDeclaration(_StrictModel):
    """Untrusted caller declarations; lifecycle state is intentionally absent."""

    asset_id: StrictStr = Field(pattern=_ASSET_ID.pattern)
    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    tenant_id: StrictStr | None = Field(default=None, pattern=_OWNER_ID.pattern)
    owner_id: StrictStr | None = Field(default=None, pattern=_OWNER_ID.pattern)
    kind: Literal["audio"]
    declared_format: Literal["wav-pcm-s16le-48000-stereo"]
    declared_duration_frames: StrictInt = Field(ge=1, le=MAX_DECLARED_DURATION_FRAMES)
    original_filename: StrictStr | None = Field(default=None, min_length=1, max_length=255)

    @field_validator("original_filename")
    @classmethod
    def filename_is_display_only(cls, value: str | None) -> str | None:
        if value is not None and any(character in value for character in ("/", "\\", "\x00")):
            raise ValueError("filename must be display metadata")
        if value is not None and any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("filename must be display metadata")
        return value


class ObservedAudioMetadata(_StrictModel):
    """Potential server observations, distinct from caller-declared values."""

    container: StrictStr = Field(min_length=1, max_length=32)
    codec: StrictStr = Field(min_length=1, max_length=64)
    byte_size: StrictInt = Field(gt=0, le=9_223_372_036_854_775_807)
    sha256: StrictStr = Field(pattern=_SHA256.pattern)
    duration_frames: StrictInt = Field(ge=1, le=MAX_DECLARED_DURATION_FRAMES)
    sample_rate: StrictInt = Field(ge=1, le=192_000)
    channels: StrictInt = Field(ge=1, le=32)


class AssetValidationEvidence(_StrictModel):
    """A typed record of a future validator result, not proof of its origin."""

    asset_id: StrictStr = Field(pattern=_ASSET_ID.pattern)
    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    asset_version_id: StrictStr = Field(pattern=_ASSET_VERSION_ID.pattern)
    observed: ObservedAudioMetadata
    validated_at: StrictStr = Field(min_length=1, max_length=40)
    validator_version: StrictStr = Field(pattern=_VALIDATOR_VERSION.pattern)
    profile_id: Literal["spotloom.storyboard.vertical-1080x1920-h264-aac-15s.v1"]

    @field_validator("validated_at")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO 8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


AssetState = Literal[
    "uploading", "quarantined", "validating", "ready", "failed", "rejected",
    "deletion_pending", "deleted", "expired",
]


class PrivateObjectVersionReference(_StrictModel):
    """Opaque reference to one private immutable object version.

    The value is intentionally provider-neutral. Its presence does not prove
    that an object exists, is private, or is immutable; a trusted storage
    adapter must establish those properties.
    """

    value: StrictStr = Field(min_length=1, max_length=512)

    @field_validator("value")
    @classmethod
    def require_nonblank_reference(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("object version reference must not be blank")
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("object version reference contains unsupported characters")
        return value


class ObservedWavProperties(_StrictModel):
    """Media properties a trusted parser would observe from exact bytes.

    ``sample_count`` counts audio sample frames (one sample per channel), not
    interleaved scalar values. This pure model does not parse media.
    """

    container: Literal["wav"]
    codec: Literal["pcm_s16le"]
    sample_format: Literal["s16le"]
    sample_rate: Literal[48_000]
    channels: Literal[2]
    # This mirrors the existing structural duration bound, not an upload policy.
    sample_count: StrictInt = Field(gt=0, le=MAX_DECLARED_DURATION_FRAMES * 2_000)
    duration_frames: StrictInt = Field(ge=1, le=MAX_DECLARED_DURATION_FRAMES)

    @field_validator("sample_count")
    @classmethod
    def require_exact_video_frame_alignment(cls, value: int) -> int:
        if value % 2_000:
            raise ValueError("audio sample count must align exactly to video frames")
        return value

    @field_validator("duration_frames")
    @classmethod
    def sample_count_must_match_duration(cls, value: int, info) -> int:
        samples = info.data.get("sample_count")
        if samples is not None and samples // 2_000 != value:
            raise ValueError("observed duration must match the exact sample count")
        return value


class VersionBoundValidationEvidence(_StrictModel):
    """Immutable shape for future trusted evidence; never proof of authenticity.

    The schema version value and object-reference representation remain subject
    to the open policy decisions. Constructing or validating this model does
    not establish that a trusted service created it or inspected media bytes.
    """

    evidence_contract_version: StrictStr = Field(min_length=1, max_length=64)
    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    asset_id: StrictStr = Field(pattern=_ASSET_ID.pattern)
    asset_version_id: StrictStr = Field(pattern=_ASSET_VERSION_ID.pattern)
    validation_attempt_id: StrictStr = Field(min_length=1, max_length=128)
    object_version: PrivateObjectVersionReference
    sha256: StrictStr = Field(pattern=_SHA256.pattern)
    byte_size: StrictInt = Field(gt=0, le=9_223_372_036_854_775_807)
    observed: ObservedWavProperties
    media_profile_id: Literal[ASSET_FORMAT]
    media_profile_version: StrictStr = Field(min_length=1, max_length=64)
    validator_identity: StrictStr = Field(min_length=1, max_length=128)
    validator_build: StrictStr = Field(min_length=1, max_length=128)
    validated_at: StrictStr = Field(min_length=1, max_length=40)
    evidence_revision: StrictInt = Field(ge=1, le=2_147_483_647)

    @field_validator("validated_at")
    @classmethod
    def require_timezone_aware_validation_time(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO 8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value


class AssetVersionBinding(_StrictModel):
    """Expected authoritative version fields supplied by a trusted repository.

    The model itself is caller-constructible; it is only a comparison value,
    not proof that a repository or storage adapter supplied it.
    """

    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    asset_id: StrictStr = Field(pattern=_ASSET_ID.pattern)
    asset_version_id: StrictStr = Field(pattern=_ASSET_VERSION_ID.pattern)
    object_version: PrivateObjectVersionReference
    sha256: StrictStr = Field(pattern=_SHA256.pattern)
    byte_size: StrictInt = Field(gt=0, le=9_223_372_036_854_775_807)
    declared_duration_frames: StrictInt = Field(ge=1, le=MAX_DECLARED_DURATION_FRAMES)
    media_profile_id: Literal[ASSET_FORMAT]
    # The supported profile version remains an explicit caller of this contract;
    # no version is inferred or selected here.
    media_profile_version: StrictStr = Field(min_length=1, max_length=64)


@dataclass(frozen=True)
class EvidenceBindingResult:
    matches: bool
    issues: tuple[AssetIssue, ...] = ()


def compare_version_bound_evidence(
    evidence: VersionBoundValidationEvidence,
    binding: AssetVersionBinding,
) -> EvidenceBindingResult:
    """Compare evidence fields with an expected version record, without trust.

    This pure comparison cannot authenticate either input or prove that bytes
    were read, hashed, or inspected by a trusted validation service.
    """
    if type(evidence) is not VersionBoundValidationEvidence or type(binding) is not AssetVersionBinding:
        return EvidenceBindingResult(False, (AssetIssue(
            "invalid_evidence_binding", "", "Evidence or asset-version binding is invalid.",
        ),))
    try:
        evidence = VersionBoundValidationEvidence.model_validate(evidence.model_dump(mode="python", warnings=False))
        binding = AssetVersionBinding.model_validate(binding.model_dump(mode="python", warnings=False))
    except (ValidationError, TypeError, ValueError):
        return EvidenceBindingResult(False, (AssetIssue(
            "invalid_evidence_binding", "", "Evidence or asset-version binding is invalid.",
        ),))

    comparisons = (
        ("project_id", evidence.project_id, binding.project_id),
        ("asset_id", evidence.asset_id, binding.asset_id),
        ("asset_version_id", evidence.asset_version_id, binding.asset_version_id),
        ("object_version", evidence.object_version, binding.object_version),
        ("sha256", evidence.sha256, binding.sha256),
        ("byte_size", evidence.byte_size, binding.byte_size),
        ("media_profile_id", evidence.media_profile_id, binding.media_profile_id),
        ("media_profile_version", evidence.media_profile_version, binding.media_profile_version),
        ("observed.duration_frames", evidence.observed.duration_frames, binding.declared_duration_frames),
    )
    issues = tuple(AssetIssue(
        "evidence_binding_mismatch", path, "Validation evidence does not match the expected asset version.",
    ) for path, actual, expected in comparisons if actual != expected)
    return EvidenceBindingResult(not issues, issues)


class AssetLifecycleSnapshot(_StrictModel):
    """Version-specific state snapshot used as a CAS precondition value.

    It is caller-constructible and is not authoritative without a trusted
    lifecycle repository.
    """

    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    asset_id: StrictStr = Field(pattern=_ASSET_ID.pattern)
    asset_version_id: StrictStr = Field(pattern=_ASSET_VERSION_ID.pattern)
    state: AssetState
    state_revision: StrictInt = Field(ge=0, le=2_147_483_647)
    validation_attempt_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)


class AssetTransitionCommand(_StrictModel):
    """Expected-state CAS command; applying it is a repository operation."""

    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    asset_id: StrictStr = Field(pattern=_ASSET_ID.pattern)
    asset_version_id: StrictStr = Field(pattern=_ASSET_VERSION_ID.pattern)
    expected_state: AssetState
    expected_state_revision: StrictInt = Field(ge=0, le=2_147_483_647)
    expected_validation_attempt_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    target_state: AssetState
    evidence_revision: StrictInt | None = Field(default=None, ge=1, le=2_147_483_647)


class LeaseAssetPin(_StrictModel):
    """One immutable asset-version binding in an all-or-nothing lease."""

    asset_id: StrictStr = Field(pattern=_ASSET_ID.pattern)
    asset_version_id: StrictStr = Field(pattern=_ASSET_VERSION_ID.pattern)
    object_version: PrivateObjectVersionReference
    sha256: StrictStr = Field(pattern=_SHA256.pattern)
    profile_id: Literal[PROFILE_ID]
    declared_duration_frames: StrictInt = Field(ge=1, le=MAX_DECLARED_DURATION_FRAMES)


class AssetLeaseRequest(_StrictModel):
    """Data shape for requesting a lease over every resolved package asset.

    This value does not authorize a job or acquire/retain storage objects. A
    future trusted repository must reject new leases after logical deletion
    and verify project authorization and every exact version pin.
    """

    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    job_id: StrictStr = Field(min_length=1, max_length=128)
    assets: tuple[LeaseAssetPin, ...] = Field(min_length=1, max_length=16)

    @field_validator("assets", mode="before")
    @classmethod
    def require_immutable_asset_collection(cls, value: object) -> object:
        if type(value) is not tuple:
            raise ValueError("lease assets must be an immutable tuple")
        return value

    @model_validator(mode="after")
    def require_unique_asset_ids(self) -> AssetLeaseRequest:
        ids = [asset.asset_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("lease asset pins must be unique")
        return self


class AssetLeaseRecord(_StrictModel):
    """Immutable lease record shape, not proof of a currently valid lease.

    ``state == "active"`` alone is insufficient; validity also depends on an
    explicit time check and a trusted repository's authoritative record.
    """

    lease_id: StrictStr = Field(min_length=1, max_length=128)
    project_id: StrictStr = Field(pattern=_PROJECT_ID.pattern)
    job_id: StrictStr = Field(min_length=1, max_length=128)
    assets: tuple[LeaseAssetPin, ...] = Field(min_length=1, max_length=16)
    created_at: StrictStr = Field(min_length=1, max_length=40)
    expires_at: StrictStr = Field(min_length=1, max_length=40)
    lease_revision: StrictInt = Field(ge=1, le=2_147_483_647)
    state: Literal["active", "released", "expired"]

    @field_validator("assets", mode="before")
    @classmethod
    def require_immutable_asset_collection(cls, value: object) -> object:
        if type(value) is not tuple:
            raise ValueError("lease assets must be an immutable tuple")
        return value

    @field_validator("created_at", "expires_at")
    @classmethod
    def require_timezone_aware_lease_time(cls, value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO 8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_bindings_and_interval(self) -> AssetLeaseRecord:
        ids = [asset.asset_id for asset in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("lease asset pins must be unique")
        if datetime.fromisoformat(self.expires_at.replace("Z", "+00:00")) <= datetime.fromisoformat(self.created_at.replace("Z", "+00:00")):
            raise ValueError("lease expiry must follow creation")
        return self


class AssetLeaseTransitionCommand(_StrictModel):
    """CAS shape for future renewal, release, expiry, or abandoned recovery.

    The value does not prove that the caller may mutate a lease. A trusted
    lease repository must compare the expected revision/state atomically.
    """

    lease_id: StrictStr = Field(min_length=1, max_length=128)
    expected_lease_revision: StrictInt = Field(ge=1, le=2_147_483_647)
    expected_state: Literal["active", "released", "expired"]
    target_state: Literal["active", "released", "expired"]
    target_expiry: StrictStr | None = Field(default=None, min_length=1, max_length=40)

    @field_validator("target_expiry")
    @classmethod
    def require_timezone_aware_target_expiry(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO 8601") from exc
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timestamp must include a timezone")
        return value

    @model_validator(mode="after")
    def enforce_lease_terminal_states(self) -> AssetLeaseTransitionCommand:
        if self.expected_state != "active" and self.target_state != self.expected_state:
            raise ValueError("released and expired leases are terminal")
        if self.target_state == "active" and self.target_expiry is None:
            raise ValueError("an active lease transition requires an expiry")
        if self.target_state != "active" and self.target_expiry is not None:
            raise ValueError("only active leases may carry a target expiry")
        return self


def asset_lease_is_valid_at(lease: AssetLeaseRecord, now: datetime) -> bool:
    """Return temporal validity for an explicit aware time, not authority.

    An ``active`` state alone is insufficient. This helper reads no system
    clock and cannot establish that the record or clock is trusted.
    """
    if type(lease) is not AssetLeaseRecord or not isinstance(now, datetime):
        return False
    if now.tzinfo is None or now.utcoffset() is None:
        return False
    try:
        lease = AssetLeaseRecord.model_validate(lease.model_dump(mode="python", warnings=False))
    except (ValidationError, TypeError, ValueError):
        return False
    created = datetime.fromisoformat(lease.created_at.replace("Z", "+00:00"))
    expires = datetime.fromisoformat(lease.expires_at.replace("Z", "+00:00"))
    return lease.state == "active" and created <= now < expires


def check_asset_lease_transition_preconditions(
    current: AssetLeaseRecord,
    command: AssetLeaseTransitionCommand,
) -> TransitionPreconditionResult:
    """Check lease ID/state/revision CAS fields without changing a lease."""
    if type(current) is not AssetLeaseRecord or type(command) is not AssetLeaseTransitionCommand:
        return TransitionPreconditionResult(False, (AssetIssue(
            "invalid_lease_transition_precondition", "", "Lease transition preconditions are invalid.",
        ),))
    try:
        current = AssetLeaseRecord.model_validate(current.model_dump(mode="python", warnings=False))
        command = AssetLeaseTransitionCommand.model_validate(command.model_dump(mode="python", warnings=False))
    except (ValidationError, TypeError, ValueError):
        return TransitionPreconditionResult(False, (AssetIssue(
            "invalid_lease_transition_precondition", "", "Lease transition preconditions are invalid.",
        ),))
    if (
        current.lease_id != command.lease_id
        or current.lease_revision != command.expected_lease_revision
        or current.state != command.expected_state
    ):
        return TransitionPreconditionResult(False, (AssetIssue(
            "stale_asset_lease", "lease", "The lease changed after the transition was prepared.",
        ),))
    if command.target_state != current.state and current.state != "active":
        return TransitionPreconditionResult(False, (AssetIssue(
            "asset_lease_transition_not_allowed", "state", "The requested lease transition is not allowed.",
        ),))
    if command.target_state == "active" and command.target_expiry is None:
        return TransitionPreconditionResult(False, (AssetIssue(
            "lease_expiry_required", "target_expiry", "An active lease transition requires an explicit expiry.",
        ),))
    return TransitionPreconditionResult(True)


@dataclass(frozen=True)
class TransitionPreconditionResult:
    accepted: bool
    issues: tuple[AssetIssue, ...] = ()


def check_asset_transition_preconditions(
    current: AssetLifecycleSnapshot,
    command: AssetTransitionCommand,
    *,
    validation_result_attempt_id: object | None = None,
    validation_evidence: VersionBoundValidationEvidence | None = None,
    authoritative_binding: AssetVersionBinding | None = None,
) -> TransitionPreconditionResult:
    """Check caller-supplied CAS values; this does not persist or authorize.

    ``validation_result_attempt_id`` must be copied from the worker result,
    independently of the command's expected ID. A future repository must
    supply an authoritative binding and perform the final atomic CAS.
    """
    if type(current) is not AssetLifecycleSnapshot or type(command) is not AssetTransitionCommand:
        return TransitionPreconditionResult(False, (AssetIssue(
            "invalid_transition_precondition", "", "Lifecycle transition preconditions are invalid.",
        ),))
    try:
        current = AssetLifecycleSnapshot.model_validate(current.model_dump(mode="python", warnings=False))
        command = AssetTransitionCommand.model_validate(command.model_dump(mode="python", warnings=False))
    except (ValidationError, TypeError, ValueError):
        return TransitionPreconditionResult(False, (AssetIssue(
            "invalid_transition_precondition", "", "Lifecycle transition preconditions are invalid.",
        ),))
    if validation_result_attempt_id is not None and (
        not isinstance(validation_result_attempt_id, str)
        or not validation_result_attempt_id
        or len(validation_result_attempt_id) > 128
    ):
        return TransitionPreconditionResult(False, (AssetIssue(
            "invalid_transition_precondition", "validation_attempt_id",
            "Lifecycle transition preconditions are invalid.",
        ),))
    matches = (
        current.project_id == command.project_id
        and current.asset_id == command.asset_id
        and current.asset_version_id == command.asset_version_id
        and current.state == command.expected_state
        and current.state_revision == command.expected_state_revision
        and current.validation_attempt_id == command.expected_validation_attempt_id
    )
    if not matches:
        return TransitionPreconditionResult(False, (AssetIssue(
            "stale_asset_transition", "state", "The asset changed after the transition was prepared.",
        ),))
    if command.target_state != current.state and command.target_state not in _ALLOWED_TRANSITIONS[current.state]:
        return TransitionPreconditionResult(False, (AssetIssue(
            "asset_transition_not_allowed", "state", "The requested asset lifecycle transition is not allowed.",
        ),))
    if command.target_state == "ready" and (
        current.state != "validating"
        or not current.validation_attempt_id
        or command.evidence_revision is None
        or validation_result_attempt_id is None
        or validation_result_attempt_id != command.expected_validation_attempt_id
        or validation_result_attempt_id != current.validation_attempt_id
    ):
        return TransitionPreconditionResult(False, (AssetIssue(
            "validation_attempt_mismatch", "validation_attempt_id",
            "The validation result does not match the active asset attempt.",
        ),))
    if command.target_state == "ready":
        if type(validation_evidence) is not VersionBoundValidationEvidence or type(authoritative_binding) is not AssetVersionBinding:
            return TransitionPreconditionResult(False, (AssetIssue(
                "asset_validation_evidence_required", "validation",
                "Version-bound validation evidence and an expected asset binding are required.",
            ),))
        evidence_match = compare_version_bound_evidence(validation_evidence, authoritative_binding)
        if not evidence_match.matches or (
            validation_evidence.validation_attempt_id != validation_result_attempt_id
            or validation_evidence.evidence_revision != command.evidence_revision
            or authoritative_binding.project_id != current.project_id
            or authoritative_binding.asset_id != current.asset_id
            or authoritative_binding.asset_version_id != current.asset_version_id
        ):
            return TransitionPreconditionResult(False, (AssetIssue(
                "asset_validation_evidence_mismatch", "validation",
                "Validation evidence does not match the active asset attempt and version.",
            ),))
    elif validation_result_attempt_id is not None or validation_evidence is not None or authoritative_binding is not None:
        return TransitionPreconditionResult(False, (AssetIssue(
            "unexpected_validation_result", "validation",
            "Validation evidence is accepted only when checking readiness.",
        ),))
    return TransitionPreconditionResult(True)


@dataclass(frozen=True)
class ManagedAsset:
    """An in-process, caller-constructible lifecycle value.

    A ``ready`` value is descriptive only; it must never independently
    authorize resolution, lease acquisition, or rendering. Only a future
    trusted lifecycle service may establish authoritative readiness.
    """

    declaration: AssetDeclaration
    asset_version_id: str
    state: AssetState = "uploading"
    validation: AssetValidationEvidence | None = None

    def __post_init__(self) -> None:
        if self.state not in _ALLOWED_TRANSITIONS:
            raise ValueError("unsupported asset lifecycle state")
        if not isinstance(self.asset_version_id, str) or not _ASSET_VERSION_ID.fullmatch(self.asset_version_id):
            raise ValueError("asset version identifier does not match the supported format")
        if self.state == "ready" and not _evidence_matches_asset(
            self.declaration, self.asset_version_id, self.validation,
        ):
            raise ValueError("ready assets require matching validation evidence")


@dataclass(frozen=True)
class AssetIssue:
    code: str
    path: str
    message: str


T = TypeVar("T")


@dataclass(frozen=True)
class AssetContractResult(Generic[T]):
    value: T | None
    issues: tuple[AssetIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.value is not None and not self.issues


@dataclass(frozen=True)
class AssetTransitionResult:
    asset: ManagedAsset | None
    issues: tuple[AssetIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.asset is not None and not self.issues


_FIELD_CODES = {
    "asset_id": ("invalid_asset_id", "Asset identifier does not match the supported format."),
    "project_id": ("invalid_project_id", "Project identifier does not match the supported format."),
    "tenant_id": ("invalid_owner_id", "Owner identifier does not match the supported format."),
    "owner_id": ("invalid_owner_id", "Owner identifier does not match the supported format."),
    "original_filename": ("invalid_display_filename", "Display filename is invalid."),
}


def _safe_model_issues(error: ValidationError) -> tuple[AssetIssue, ...]:
    issues: list[AssetIssue] = []
    for item in error.errors():
        location = tuple(item.get("loc", ()))
        field = location[0] if location and isinstance(location[0], str) else ""
        code, message = _FIELD_CODES.get(
            field,
            ("invalid_asset_metadata", "Value does not match the supported asset contract."),
        )
        path = field if field in _FIELD_CODES or field in {
            "kind", "declared_format", "declared_duration_frames", "container", "codec",
            "byte_size", "sha256", "duration_frames", "sample_rate", "channels",
            "asset_version_id", "observed", "validated_at", "validator_version", "profile_id",
        } else ""
        if field == "asset_version_id":
            code, message = "invalid_asset_version", "Asset version identifier does not match the supported format."
        elif field == "asset_id":
            code, message = "invalid_asset_id", "Asset identifier does not match the supported format."
        elif field == "project_id":
            code, message = "invalid_project_id", "Project identifier does not match the supported format."
        issues.append(AssetIssue(code, path, message))
    return tuple(sorted(set(issues), key=lambda issue: (issue.path, issue.code, issue.message)))


def validate_asset_declaration(value: object) -> AssetContractResult[AssetDeclaration]:
    """Validate untrusted caller declarations with bounded, sanitized issues."""
    try:
        return AssetContractResult(AssetDeclaration.model_validate(value))
    except ValidationError as error:
        return AssetContractResult(None, _safe_model_issues(error))


def validate_observed_audio_metadata(value: object) -> AssetContractResult[ObservedAudioMetadata]:
    """Validate a possible observation record; this does not inspect media."""
    try:
        return AssetContractResult(ObservedAudioMetadata.model_validate(value))
    except ValidationError as error:
        return AssetContractResult(None, _safe_model_issues(error))


def validate_asset_validation_evidence(value: object) -> AssetContractResult[AssetValidationEvidence]:
    """Validate the shape of future validator evidence, not its authenticity."""
    try:
        return AssetContractResult(AssetValidationEvidence.model_validate(value))
    except ValidationError as error:
        return AssetContractResult(None, _safe_model_issues(error))


_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "uploading": frozenset({"quarantined", "failed", "deletion_pending", "expired"}),
    "quarantined": frozenset({"validating", "failed", "rejected", "deletion_pending", "expired"}),
    "validating": frozenset({"ready", "failed", "rejected", "deletion_pending"}),
    "ready": frozenset({"deletion_pending", "expired"}),
    "failed": frozenset({"quarantined", "deletion_pending", "expired"}),
    "rejected": frozenset({"deletion_pending", "expired"}),
    "deletion_pending": frozenset({"deleted"}),
    "expired": frozenset({"deletion_pending"}),
    "deleted": frozenset(),
}


def _evidence_matches_asset(
    declaration: AssetDeclaration,
    asset_version_id: str,
    evidence: AssetValidationEvidence | None,
) -> bool:
    if evidence is None:
        return False
    observed = evidence.observed
    return (
        evidence.asset_id == declaration.asset_id
        and evidence.project_id == declaration.project_id
        and evidence.asset_version_id == asset_version_id
        and declaration.declared_format == ASSET_FORMAT
        and observed.container.lower() == "wav"
        and observed.codec.lower() == "pcm_s16le"
        and observed.sample_rate == 48_000
        and observed.channels == 2
        and observed.duration_frames == declaration.declared_duration_frames
        and evidence.profile_id == PROFILE_ID
    )


def create_managed_asset(
    declaration: AssetDeclaration,
    asset_version_id: object,
) -> AssetContractResult[ManagedAsset]:
    """Create a record with an explicit immutable version identity.

    A future store must allocate a fresh version ID for replacement content.
    The record itself is immutable; this pure contract does not generate or
    persist either identifier.
    """
    if not isinstance(asset_version_id, str) or not _ASSET_VERSION_ID.fullmatch(asset_version_id):
        return AssetContractResult(None, (AssetIssue(
            "invalid_asset_version", "asset_version_id", "Asset version identifier does not match the supported format.",
        ),))
    return AssetContractResult(ManagedAsset(declaration=declaration, asset_version_id=asset_version_id))


def transition_asset(
    asset: ManagedAsset,
    target: AssetState,
    *,
    evidence: AssetValidationEvidence | None = None,
) -> AssetTransitionResult:
    """Apply one deterministic lifecycle transition without performing I/O.

    Same-state transitions are idempotent. Entering ``ready`` requires typed
    evidence matching the current declared WAV profile and duration. The type is
    not cryptographically or operationally trusted; only a future trusted
    validator boundary may supply authoritative evidence.
    """
    if target == asset.state:
        return AssetTransitionResult(asset)
    if target not in _ALLOWED_TRANSITIONS.get(asset.state, frozenset()):
        return AssetTransitionResult(None, (AssetIssue(
            "asset_transition_not_allowed", "state", "The requested asset lifecycle transition is not allowed.",
        ),))
    if target == "ready":
        if evidence is None:
            return AssetTransitionResult(None, (AssetIssue(
                "asset_validation_evidence_required", "validation", "Validated media evidence is required before readiness.",
            ),))
        if not _evidence_matches_asset(asset.declaration, asset.asset_version_id, evidence):
            return AssetTransitionResult(None, (AssetIssue(
                "asset_validation_evidence_mismatch", "validation", "Observed media does not match the declared supported profile.",
            ),))
        return AssetTransitionResult(ManagedAsset(asset.declaration, asset.asset_version_id, target, evidence))
    if evidence is not None:
        return AssetTransitionResult(None, (AssetIssue(
            "asset_validation_evidence_unexpected", "validation", "Validation evidence is accepted only when entering readiness.",
        ),))
    return AssetTransitionResult(ManagedAsset(asset.declaration, asset.asset_version_id, target, asset.validation))
