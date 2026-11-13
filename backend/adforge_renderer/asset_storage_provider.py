"""Provider-neutral private storage contracts for internal asset services.

These interfaces neither authorize callers nor establish media validation,
asset readiness, or production storage guarantees.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import BinaryIO, Iterable, Protocol
from uuid import UUID

from .asset_contract import PrivateObjectVersionReference


MAX_STORAGE_CHUNK_BYTES = 1024 * 1024


class AssetStorageError(Exception):
    """Base for stable, sanitized storage failures."""

    code = "asset_storage_error"
    safe_message = "The asset storage operation could not be completed."

    def __init__(self) -> None:
        super().__init__(self.safe_message)


class StorageObjectMissing(AssetStorageError):
    code = "storage_object_missing"
    safe_message = "The requested storage object was not found."


class StorageObjectIncomplete(AssetStorageError):
    code = "storage_object_incomplete"
    safe_message = "The storage object is incomplete."


class StorageSizeLimitExceeded(AssetStorageError):
    code = "storage_size_limit_exceeded"
    safe_message = "The storage write exceeds its configured size limit."


class StorageObjectConflict(AssetStorageError):
    code = "storage_object_conflict"
    safe_message = "The storage object already exists with different contents."


class StorageInvalidReference(AssetStorageError):
    code = "storage_invalid_reference"
    safe_message = "The storage reference is invalid."


class StorageIOFailure(AssetStorageError):
    code = "storage_io_failure"
    safe_message = "The storage operation failed."


class StorageAtomicOperationUnsupported(AssetStorageError):
    code = "storage_atomic_operation_unsupported"
    safe_message = "This filesystem cannot provide the required atomic operation."


class StorageCleanupNotConfirmed(AssetStorageError):
    code = "storage_cleanup_not_confirmed"
    safe_message = "Physical storage cleanup could not be confirmed."


class StorageConfigurationError(AssetStorageError):
    code = "storage_configuration_invalid"
    safe_message = "Private local storage configuration is invalid."


@dataclass(frozen=True, slots=True)
class TemporaryObjectReference:
    """Opaque storage handle bound to one project and upload operation.

    The database persists only ``value``. Trusted backend code reconstructs
    the handle from that value and the owning row before calling storage.
    These identifiers are context, not caller-provided authorization.
    """

    value: str
    project_id: UUID | None = None
    operation_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class TransferObservation:
    """Exact transfer count and digest; not trusted media evidence."""

    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class TemporaryObjectInspection:
    """Storage-level completeness and measured bytes for a temporary object."""

    complete: bool
    byte_size: int
    sha256: str | None


@dataclass(frozen=True, slots=True)
class FinalizedObject:
    """Opaque exact-version reference and storage facts."""

    object_version: PrivateObjectVersionReference
    byte_size: int
    sha256: str
    temporary_cleanup_confirmed: bool
    project_id: UUID | None = None
    operation_id: UUID | None = None
    temporary_preserved: bool = False


@dataclass(frozen=True, slots=True)
class CleanupConfirmation:
    """Storage-authenticated receipt for one exact durable cleanup claim."""

    reference: TemporaryObjectReference | PrivateObjectVersionReference
    physically_absent: bool
    target_kind: str | None = None
    cleanup_operation: str | None = None
    project_id: UUID | None = None
    asset_id: UUID | None = None
    intent_id: UUID | None = None
    operation_id: UUID | None = None
    claim_token: UUID | None = None
    cleanup_revision: int | None = None
    cleanup_generation: int | None = None
    proof: bytes = field(default=b"", repr=False, compare=False)


class PrivateAssetStorage(Protocol):
    """Narrow provider-independent interface; references are not credentials."""

    def allocate_temporary_reference(
        self, *, project_id: UUID, operation_id: UUID
    ) -> TemporaryObjectReference: ...

    def create_temporary_object(
        self, reference: TemporaryObjectReference | None = None, /
    ) -> TemporaryObjectReference: ...

    def new_object_version_reference(self) -> PrivateObjectVersionReference: ...

    def write_temporary_object(
        self,
        reference: TemporaryObjectReference,
        chunks: Iterable[bytes],
        *,
        max_bytes: int,
    ) -> TransferObservation: ...

    def inspect_temporary_object(
        self, reference: TemporaryObjectReference, /
    ) -> TemporaryObjectInspection: ...

    def finalize_temporary_object(
        self,
        temporary: TemporaryObjectReference,
        object_version: PrivateObjectVersionReference,
        *,
        expected_sha256: str,
        expected_byte_size: int,
    ) -> FinalizedObject: ...

    def finalize_temporary_object_preserving_temporary(
        self,
        temporary: TemporaryObjectReference,
        object_version: PrivateObjectVersionReference,
        *,
        expected_sha256: str,
        expected_byte_size: int,
    ) -> FinalizedObject: ...

    def inspect_finalized_object(
        self, object_version: PrivateObjectVersionReference, /
    ) -> TransferObservation: ...

    def open_exact_version(
        self, object_version: PrivateObjectVersionReference, /
    ) -> BinaryIO: ...

    def delete_temporary_object(
        self, reference: TemporaryObjectReference, /, *,
        project_id: UUID | None = None,
        asset_id: UUID | None = None,
        intent_id: UUID | None = None,
        claim_token: UUID | None = None,
        cleanup_revision: int | None = None,
        cleanup_generation: int | None = None,
    ) -> CleanupConfirmation: ...

    def delete_finalized_object(
        self, object_version: PrivateObjectVersionReference, /, *,
        project_id: UUID,
        asset_id: UUID,
        intent_id: UUID,
        claim_token: UUID,
        cleanup_revision: int,
        cleanup_generation: int,
    ) -> CleanupConfirmation: ...

    def verify_cleanup_confirmation(self, confirmation: CleanupConfirmation, /) -> bool: ...
