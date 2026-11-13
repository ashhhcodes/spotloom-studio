"""Private local development implementation of the asset storage contract.

This module is deliberately independent of HTTP, SQLAlchemy, project ownership,
and media validation. The configured directory must be private and must not be
served by another process. It is not a production storage guarantee.

Cooperating processes coordinate with Windows byte-range locks or POSIX flock
on persistent per-object lock files. Correctness assumes a local filesystem
with those kernel lock and atomic hard-link semantics; network filesystems are
not supported. Lock files, tombstones, and the private cleanup-receipt key are
retained so process crashes cannot silently erase fencing state.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
import errno
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import struct
import subprocess
import sys
from contextlib import contextmanager
from collections.abc import Iterable, Mapping
from typing import BinaryIO
from uuid import UUID, uuid4

from pydantic import ValidationError

from .asset_contract import PrivateObjectVersionReference
from .asset_storage_provider import (
    MAX_STORAGE_CHUNK_BYTES,
    AssetStorageError,
    CleanupConfirmation,
    FinalizedObject,
    StorageAtomicOperationUnsupported,
    StorageCleanupNotConfirmed,
    StorageConfigurationError,
    StorageIOFailure,
    StorageInvalidReference,
    StorageObjectConflict,
    StorageObjectIncomplete,
    StorageObjectMissing,
    StorageSizeLimitExceeded,
    TemporaryObjectInspection,
    TemporaryObjectReference,
    TransferObservation,
)
from .environment import load_backend_environment


_TEMP_REF = re.compile(r"^tmp_[0-9a-f]{32}$")
_VERSION_REF = re.compile(r"^ver_[0-9a-f]{32}$")
_TEMP_META = struct.Struct(">4sQQ32s")  # magic, limit, count, raw SHA-256
_FINAL_META = struct.Struct(">4s16sQ32s")  # magic, originating temp UUID, count, digest
_TEMP_BINDING_META = struct.Struct(">4s16s16s")  # magic, project UUID, operation UUID
_FINAL_META_V2 = struct.Struct(">4s16s16s16sQ32s")  # magic, project, operation, temp UUID, count, digest
_FINAL_META_V3 = struct.Struct(">4s16s16s16s16sQ32s")  # magic, exact version, project, operation, temp, count, digest
_TEMP_MAGIC = b"SLT1"
_FINAL_MAGIC = b"SLV1"
_TEMP_BINDING_MAGIC = b"SLP1"
_FINAL_MAGIC_V2 = b"SLV2"
_FINAL_MAGIC_V3 = b"SLV3"
_ROOT_MARKER = ".spotloom-private-storage-v1"
_LOCKS_DIR = "temporary-locks"
_REPARSE_POINT = 0x400
_PROTECTED_WEB_DIRS = {"public", "static", "www", "wwwroot", "htdocs", "httpdocs"}
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class LocalAssetStorageConfig:
    """An explicit absolute local storage root; no repository-local default."""

    root: Path

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None,
    ) -> LocalAssetStorageConfig:
        source = os.environ if environ is None else environ
        if environ is None:
            load_backend_environment()
            source = os.environ
        raw = source.get("SPOTLOOM_ASSET_STORAGE_ROOT")
        if not isinstance(raw, str) or not raw or raw != raw.strip():
            raise StorageConfigurationError()
        try:
            configured = Path(raw)
            if not configured.is_absolute() or ".." in configured.parts:
                raise ValueError
            _reject_reparse_components(configured)
            resolved = configured.resolve(strict=False)
            _reject_reparse_components(resolved)
            _validate_root_location(resolved)
            return cls(resolved)
        except (OSError, RuntimeError, ValueError):
            raise StorageConfigurationError() from None


def _is_reparse(stat_result: os.stat_result) -> bool:
    return stat.S_ISLNK(stat_result.st_mode) or bool(
        getattr(stat_result, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _reject_reparse_components(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if _is_reparse(info):
            raise ValueError("reparse points are not accepted in storage paths")


def _validate_root_location(root: Path) -> None:
    try:
        root.relative_to(_REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        raise ValueError("storage root must be outside the repository")
    if any(part.casefold() in _PROTECTED_WEB_DIRS for part in root.parts):
        raise ValueError("storage root must not be under a conventional web directory")


def _identity(info: os.stat_result) -> tuple[int, int]:
    return info.st_dev, info.st_ino


def _cleanup_confirmation_payload(confirmation: CleanupConfirmation) -> bytes:
    reference = confirmation.reference
    if type(reference) is TemporaryObjectReference:
        reference_data = {
            "type": "temporary", "value": reference.value,
            "project_id": reference.project_id.hex if reference.project_id else None,
            "operation_id": reference.operation_id.hex if reference.operation_id else None,
        }
    elif type(reference) is PrivateObjectVersionReference:
        reference_data = {"type": "version", "value": reference.value}
    else:
        raise StorageCleanupNotConfirmed()
    payload = {
        "reference": reference_data,
        "physically_absent": confirmation.physically_absent,
        "target_kind": confirmation.target_kind,
        "cleanup_operation": confirmation.cleanup_operation,
        "project_id": confirmation.project_id.hex if confirmation.project_id else None,
        "asset_id": confirmation.asset_id.hex if confirmation.asset_id else None,
        "intent_id": confirmation.intent_id.hex if confirmation.intent_id else None,
        "operation_id": confirmation.operation_id.hex if confirmation.operation_id else None,
        "claim_token": confirmation.claim_token.hex if confirmation.claim_token else None,
        "cleanup_revision": confirmation.cleanup_revision,
        "cleanup_generation": confirmation.cleanup_generation,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")


class LocalPrivateAssetStorage:
    """Private local adapter using exclusive files and create-only hard links.

    Finalization uses ``os.link`` as the atomic no-replace primitive. It works
    only when the filesystem supports hard links and both directories share a
    filesystem; the adapter never falls back to overwrite-capable rename.
    """

    def __init__(self, config: LocalAssetStorageConfig) -> None:
        if type(config) is not LocalAssetStorageConfig:
            raise StorageConfigurationError()
        root = config.root
        try:
            if not root.is_absolute() or ".." in root.parts:
                raise ValueError
            _reject_reparse_components(root)
            root = root.resolve(strict=False)
            _reject_reparse_components(root)
            _validate_root_location(root)
            existed = root.exists()
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            root_info = root.lstat()
            if _is_reparse(root_info) or not stat.S_ISDIR(root_info.st_mode):
                raise ValueError
            if not existed and os.name != "nt":
                os.chmod(root, 0o700)
            marker = root / _ROOT_MARKER
            if not marker.exists():
                if any(root.iterdir()):
                    raise ValueError
                if os.name == "nt":
                    self._secure_windows_acl(root)
                self._write_marker(marker)
            elif os.name == "nt":
                self._secure_windows_acl(root)
            elif stat.S_IMODE(root_info.st_mode) & 0o077:
                os.chmod(root, 0o700)

            temporary = root / "temporary"
            versions = root / "versions"
            locks = root / _LOCKS_DIR
            temporary.mkdir(mode=0o700, exist_ok=True)
            versions.mkdir(mode=0o700, exist_ok=True)
            locks.mkdir(mode=0o700, exist_ok=True)
            for directory in (root, temporary, versions, locks):
                info = directory.lstat()
                if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                    raise ValueError
                if os.name != "nt":
                    if stat.S_IMODE(info.st_mode) & 0o077:
                        os.chmod(directory, 0o700)
            self.__root = root
            self.__temporary = temporary
            self.__versions = versions
            self.__locks = locks
            self.__root_identity = _identity(root.lstat())
            self.__temporary_identity = _identity(temporary.lstat())
            self.__versions_identity = _identity(versions.lstat())
            self.__locks_identity = _identity(locks.lstat())
            self._verify_layout()
            self.__cleanup_confirmation_key = self._load_cleanup_confirmation_key()
        except StorageConfigurationError:
            raise
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            raise StorageConfigurationError() from None

    @staticmethod
    def _write_marker(path: Path) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "wb", closefd=False) as marker:
                value = b"Spotloom private local storage v1\n"
                if marker.write(value) != len(value):
                    raise OSError("short marker write")
                marker.flush()
                os.fsync(fd)
        finally:
            os.close(fd)

    @staticmethod
    def _secure_windows_acl(root: Path) -> None:
        """Protect the dedicated root and inherited children with Windows ACLs."""
        try:
            identity = subprocess.run(
                ["whoami.exe", "/user", "/fo", "csv", "/nh"],
                check=True, capture_output=True, text=True, timeout=10,
            )
            rows = list(csv.reader(identity.stdout.splitlines()))
            sid = rows[0][-1].strip() if rows and rows[0] else ""
            if not re.fullmatch(r"S-1-[0-9-]+", sid):
                raise ValueError
            entries = [
                f"*{sid}:(OI)(CI)F",
                "*S-1-5-18:(OI)(CI)F",  # Local System
                "*S-1-5-32-544:(OI)(CI)F",  # Built-in Administrators
            ]
            subprocess.run(
                ["icacls.exe", str(root), "/inheritance:r", "/grant:r", *entries],
                check=True, capture_output=True, text=True, timeout=20,
            )
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            raise StorageConfigurationError() from None

    def _verify_layout(self) -> None:
        expected = (
            (self.__root, self.__root_identity),
            (self.__temporary, self.__temporary_identity),
            (self.__versions, self.__versions_identity),
            (self.__locks, self.__locks_identity),
        )
        try:
            for path, expected_identity in expected:
                info = path.lstat()
                if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
                    raise ValueError
                if _identity(info) != expected_identity:
                    raise ValueError
            marker = self.__root / _ROOT_MARKER
            info = marker.lstat()
            if _is_reparse(info) or not stat.S_ISREG(info.st_mode):
                raise ValueError
        except (OSError, ValueError):
            raise StorageIOFailure() from None

    def _load_cleanup_confirmation_key(self) -> bytes:
        """Load a stable private key so receipts remain verifiable after restart."""
        self._verify_layout()
        path = self.__root / ".cleanup-receipt-key-v1"
        try:
            try:
                fd = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                fd = -1
            if fd >= 0:
                key = secrets.token_bytes(32)
                try:
                    with os.fdopen(fd, "wb") as stream:
                        if stream.write(key) != len(key):
                            raise OSError
                        stream.flush()
                        os.fsync(stream.fileno())
                except OSError:
                    raise StorageConfigurationError() from None
            self._verify_layout()
            info = self._lstat_regular(path)
            assert info is not None
            if info.st_size != 32:
                raise StorageConfigurationError()
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
            read_fd = os.open(path, flags)
            try:
                opened = os.fstat(read_fd)
                if not stat.S_ISREG(opened.st_mode) or _identity(opened) != _identity(info):
                    raise StorageConfigurationError()
                with os.fdopen(read_fd, "rb", closefd=False) as stream:
                    key = stream.read(33)
            finally:
                os.close(read_fd)
            self._verify_layout()
            if len(key) != 32:
                raise StorageConfigurationError()
            return key
        except StorageConfigurationError:
            raise
        except (OSError, ValueError):
            raise StorageConfigurationError() from None

    def _issue_cleanup_confirmation(self, **values) -> CleanupConfirmation:
        confirmation = CleanupConfirmation(**values)
        proof = hmac.new(
            self.__cleanup_confirmation_key,
            _cleanup_confirmation_payload(confirmation),
            hashlib.sha256,
        ).digest()
        return replace(confirmation, proof=proof)

    def verify_cleanup_confirmation(self, confirmation: CleanupConfirmation, /) -> bool:
        if type(confirmation) is not CleanupConfirmation or confirmation.physically_absent is not True:
            return False
        if type(confirmation.proof) is not bytes or len(confirmation.proof) != hashlib.sha256().digest_size:
            return False
        try:
            expected = hmac.new(
                self.__cleanup_confirmation_key,
                _cleanup_confirmation_payload(confirmation),
                hashlib.sha256,
            ).digest()
        except (TypeError, ValueError, AttributeError):
            return False
        return hmac.compare_digest(expected, confirmation.proof)

    @staticmethod
    def _validate_temporary(reference: object) -> str:
        if type(reference) is not TemporaryObjectReference or not isinstance(reference.value, str):
            raise StorageInvalidReference()
        if not _TEMP_REF.fullmatch(reference.value):
            raise StorageInvalidReference()
        if (reference.project_id is None) != (reference.operation_id is None):
            raise StorageInvalidReference()
        if reference.project_id is not None:
            if reference.value != LocalPrivateAssetStorage._bound_temporary_value(
                reference.project_id, reference.operation_id
            ):
                raise StorageInvalidReference()
        return reference.value

    @contextmanager
    def _temporary_guard(self, value: str, *, cleanup: bool = False):
        """Acquire a cross-process lock for one temp reference.

        Lock files live outside the removable object directory and are never
        unlinked. Windows uses a byte-range lock; POSIX uses flock. Both are
        kernel-managed and released on process death. Contention fails closed.
        """
        with self._object_guard(f"{value}.lock", f"{value}.deleted", cleanup=cleanup):
            yield

    @contextmanager
    def _version_guard(self, value: str, *, cleanup: bool = False):
        version_id = value.removeprefix("ver_")
        with self._object_guard(
            f"version-{version_id}.lock", f"version-{version_id}.deleted", cleanup=cleanup
        ):
            yield

    @contextmanager
    def _object_guard(self, lock_name: str, tombstone_name: str, *, cleanup: bool = False):
        self._verify_layout()
        lock_path = self.__locks / lock_name
        tombstone = self.__locks / tombstone_name
        fd = -1
        acquired = False
        try:
            try:
                fd = os.open(
                    lock_path,
                    os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode):
                    raise ValueError
                path_info = self._lstat_regular(lock_path)
                assert path_info is not None
                if _identity(info) != _identity(path_info):
                    raise ValueError
                if os.name == "nt":
                    import msvcrt
                    os.lseek(fd, 0, os.SEEK_SET)
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"\0")
                    os.fsync(fd)
                # A replaced lock directory could make this process hold a
                # lock different from the one other adapter instances use.
                # Revalidate the directory and the opened lock inode after
                # acquisition, before any caller can touch an object.
                self._verify_layout()
                current_lock = self._lstat_regular(lock_path)
                if current_lock is None or _identity(os.fstat(fd)) != _identity(current_lock):
                    raise ValueError
                if not cleanup and self._lstat_regular(tombstone, missing_ok=True) is not None:
                    raise StorageObjectConflict()
            except StorageObjectConflict:
                raise
            except (OSError, ValueError, ImportError):
                if cleanup:
                    raise StorageCleanupNotConfirmed() from None
                raise StorageObjectIncomplete() from None
            yield
            self._verify_layout()
            current_lock = self._lstat_regular(lock_path)
            if current_lock is None or _identity(os.fstat(fd)) != _identity(current_lock):
                raise StorageIOFailure()
        finally:
            if fd >= 0:
                try:
                    if acquired:
                        if os.name == "nt":
                            import msvcrt
                            os.lseek(fd, 0, os.SEEK_SET)
                            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl
                            fcntl.flock(fd, fcntl.LOCK_UN)
                except OSError:
                    pass
                os.close(fd)

    def _mark_deleted(self, name: str, marker: bytes) -> None:
        """Permanently fence recreation after cleanup starts."""
        self._verify_layout()
        path = self.__locks / name
        try:
            try:
                fd = os.open(
                    path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
            except FileExistsError:
                if self._read_marker(path, len(marker)) != marker:
                    raise StorageCleanupNotConfirmed()
                return
            with os.fdopen(fd, "wb") as stream:
                if stream.write(marker) != len(marker):
                    raise StorageCleanupNotConfirmed()
                stream.flush()
                os.fsync(stream.fileno())
            self._verify_layout()
            if self._read_marker(path, len(marker)) != marker:
                raise StorageCleanupNotConfirmed()
        except AssetStorageError:
            raise
        except OSError:
            raise StorageCleanupNotConfirmed() from None

    def _mark_temporary_deleted(self, value: str) -> None:
        self._mark_deleted(f"{value}.deleted", b"Spotloom temporary object deleted v1\n")

    def _mark_version_deleted(self, value: str) -> None:
        version_id = value.removeprefix("ver_")
        self._mark_deleted(
            f"version-{version_id}.deleted", b"Spotloom finalized version deleted v1\n"
        )

    @staticmethod
    def _bound_temporary_value(project_id: UUID, operation_id: UUID) -> str:
        if type(project_id) is not UUID or type(operation_id) is not UUID:
            raise StorageInvalidReference()
        value = hashlib.sha256(
            b"spotloom-temp-v1\0" + project_id.bytes + operation_id.bytes
        ).hexdigest()[:32]
        return f"tmp_{value}"

    def allocate_temporary_reference(
        self, *, project_id: UUID, operation_id: UUID
    ) -> TemporaryObjectReference:
        """Allocate a stable, project-bound handle without filesystem I/O.

        The backend supplies a fresh random operation UUID. Physical creation
        happens later, after the upload intent and quota reservation commit.
        """
        value = self._bound_temporary_value(project_id, operation_id)
        return TemporaryObjectReference(value, project_id, operation_id)

    def _verify_temporary_binding(
        self, reference: TemporaryObjectReference, directory: Path
    ) -> None:
        binding_path = directory / "binding"
        binding_info = self._lstat_regular(binding_path, missing_ok=True)
        if reference.project_id is None:
            if binding_info is not None:
                raise StorageInvalidReference()
            return
        if binding_info is None or binding_info.st_size != _TEMP_BINDING_META.size:
            raise StorageInvalidReference()
        raw = self._read_marker(binding_path, _TEMP_BINDING_META.size)
        magic, project_bytes, operation_bytes = _TEMP_BINDING_META.unpack(raw)
        if (
            magic != _TEMP_BINDING_MAGIC
            or project_bytes != reference.project_id.bytes
            or operation_bytes != reference.operation_id.bytes
        ):
            raise StorageInvalidReference()

    @staticmethod
    def _validate_version(reference: object) -> str:
        if type(reference) is not PrivateObjectVersionReference:
            raise StorageInvalidReference()
        try:
            validated = PrivateObjectVersionReference.model_validate(
                reference.model_dump(mode="python", warnings=False)
            )
        except (ValidationError, TypeError, ValueError, AttributeError):
            raise StorageInvalidReference() from None
        if not _VERSION_REF.fullmatch(validated.value):
            raise StorageInvalidReference()
        return validated.value

    def create_temporary_object(
        self, reference: TemporaryObjectReference | None = None, /
    ) -> TemporaryObjectReference:
        if reference is None:
            value = f"tmp_{uuid4().hex}"
            bound_reference = TemporaryObjectReference(value)
        else:
            value = self._validate_temporary(reference)
            bound_reference = reference
        with self._temporary_guard(value):
            return self._create_temporary_object_locked(bound_reference)

    def _create_temporary_object_locked(
        self, bound_reference: TemporaryObjectReference
    ) -> TemporaryObjectReference:
        value = self._validate_temporary(bound_reference)
        self._verify_layout()
        directory = self.__temporary / value
        created = False
        try:
            os.mkdir(directory, 0o700)
            created = True
            if bound_reference.project_id is not None:
                binding_fd = os.open(
                    directory / "binding",
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                with os.fdopen(binding_fd, "wb") as binding:
                    data = _TEMP_BINDING_META.pack(
                        _TEMP_BINDING_MAGIC,
                        bound_reference.project_id.bytes,
                        bound_reference.operation_id.bytes,
                    )
                    if binding.write(data) != len(data):
                        raise OSError("short binding marker write")
                    binding.flush()
                    os.fsync(binding.fileno())
            payload = directory / "payload"
            fd = os.open(
                payload,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            os.close(fd)
            return bound_reference
        except FileExistsError:
            if created:
                try:
                    for name in ("payload", "complete", "writing", "binding"):
                        path = directory / name
                        info = self._lstat_regular(path, missing_ok=True)
                        if info is not None:
                            path.unlink()
                    directory.rmdir()
                except (OSError, AssetStorageError):
                    pass
            if not created and bound_reference.project_id is not None:
                try:
                    self._verify_directory(directory)
                    self._verify_temporary_binding(bound_reference, directory)
                    if self._lstat_regular(directory / "payload", missing_ok=True) is None:
                        raise StorageObjectIncomplete()
                    return bound_reference
                except AssetStorageError:
                    pass
            raise StorageObjectConflict() from None
        except OSError:
            if created:
                try:
                    for name in ("payload", "complete", "writing", "binding"):
                        path = directory / name
                        info = self._lstat_regular(path, missing_ok=True)
                        if info is not None:
                            path.unlink()
                    directory.rmdir()
                except (OSError, AssetStorageError):
                    pass
            raise StorageIOFailure() from None

    def new_object_version_reference(self) -> PrivateObjectVersionReference:
        self._verify_layout()
        return PrivateObjectVersionReference(value=f"ver_{uuid4().hex}")

    def _temp_dir(self, reference: object) -> Path:
        self._verify_layout()
        return self.__temporary / self._validate_temporary(reference)

    def _temp_files(self, reference: object) -> tuple[Path, Path, Path]:
        directory = self._temp_dir(reference)
        self._verify_directory(directory)
        return directory / "payload", directory / "complete", directory / "writing"

    def _verify_directory(self, path: Path) -> None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            raise StorageObjectMissing() from None
        except OSError:
            raise StorageIOFailure() from None
        if _is_reparse(info) or not stat.S_ISDIR(info.st_mode):
            raise StorageInvalidReference()

    @staticmethod
    def _lstat_regular(path: Path, *, missing_ok: bool = False) -> os.stat_result | None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            if missing_ok:
                return None
            raise StorageObjectMissing() from None
        except OSError:
            raise StorageIOFailure() from None
        if _is_reparse(info) or not stat.S_ISREG(info.st_mode):
            raise StorageInvalidReference()
        return info

    @staticmethod
    def _open_read(path: Path) -> BinaryIO:
        before = LocalPrivateAssetStorage._lstat_regular(path)
        assert before is not None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags)
            after = os.fstat(fd)
            if not stat.S_ISREG(after.st_mode) or _identity(before) != _identity(after):
                os.close(fd)
                raise StorageInvalidReference()
            return os.fdopen(fd, "rb")
        except StorageInvalidReference:
            raise
        except FileNotFoundError:
            raise StorageObjectMissing() from None
        except OSError:
            raise StorageIOFailure() from None

    @staticmethod
    def _read_marker(path: Path, expected_size: int) -> bytes:
        info = LocalPrivateAssetStorage._lstat_regular(path)
        assert info is not None
        if info.st_size != expected_size:
            raise StorageObjectIncomplete()
        try:
            with LocalPrivateAssetStorage._open_read(path) as stream:
                data = stream.read(expected_size + 1)
        except AssetStorageError:
            raise
        except OSError:
            raise StorageIOFailure() from None
        if len(data) != expected_size:
            raise StorageObjectIncomplete()
        return data

    @staticmethod
    def _hash_stream(stream: BinaryIO, *, expected_size: int | None = None) -> TransferObservation:
        digest = hashlib.sha256()
        count = 0
        try:
            while True:
                chunk = stream.read(MAX_STORAGE_CHUNK_BYTES)
                if not chunk:
                    break
                count += len(chunk)
                if expected_size is not None and count > expected_size:
                    raise StorageObjectIncomplete()
                digest.update(chunk)
        except AssetStorageError:
            raise
        except OSError:
            raise StorageIOFailure() from None
        if expected_size is not None and count != expected_size:
            raise StorageObjectIncomplete()
        return TransferObservation(count, digest.hexdigest())

    def write_temporary_object(
        self,
        reference: TemporaryObjectReference,
        chunks: Iterable[bytes],
        *,
        max_bytes: int,
    ) -> TransferObservation:
        value = self._validate_temporary(reference)
        with self._temporary_guard(value):
            return self._write_temporary_object_locked(
                reference, chunks, max_bytes=max_bytes
            )

    def _write_temporary_object_locked(
        self,
        reference: TemporaryObjectReference,
        chunks: Iterable[bytes],
        *,
        max_bytes: int,
    ) -> TransferObservation:
        if type(max_bytes) is not int or max_bytes <= 0:
            raise StorageSizeLimitExceeded()
        payload, complete, writing = self._temp_files(reference)
        self._lstat_regular(payload)
        if self._lstat_regular(complete, missing_ok=True) is not None:
            raise StorageObjectConflict()
        try:
            lock_fd = os.open(
                writing,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
        except FileExistsError:
            raise StorageObjectIncomplete() from None
        except OSError:
            raise StorageIOFailure() from None

        digest = hashlib.sha256()
        count = 0
        try:
            os.close(lock_fd)
            payload_info = self._lstat_regular(payload)
            assert payload_info is not None
            if payload_info.st_size != 0:
                raise StorageObjectIncomplete()
            fd = os.open(
                payload,
                os.O_WRONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
            )
            try:
                opened_info = os.fstat(fd)
                if not stat.S_ISREG(opened_info.st_mode) or _identity(payload_info) != _identity(opened_info):
                    raise StorageInvalidReference()
                raw_stream = os.fdopen(fd, "wb", buffering=0, closefd=False)
                with raw_stream as stream:
                    iterator = iter(chunks)
                    try:
                        for chunk in iterator:
                            if type(chunk) is not bytes:
                                raise StorageIOFailure()
                            if len(chunk) > MAX_STORAGE_CHUNK_BYTES:
                                raise StorageSizeLimitExceeded()
                            if count + len(chunk) > max_bytes:
                                raise StorageSizeLimitExceeded()
                            if not chunk:
                                continue
                            written = stream.write(chunk)
                            if written != len(chunk):
                                raise StorageIOFailure()
                            count += written
                            digest.update(chunk)
                    finally:
                        close = getattr(iterator, "close", None)
                        if callable(close):
                            active_error = sys.exc_info()[0]
                            try:
                                close()
                            except Exception:
                                if active_error is None:
                                    raise
                    stream.flush()
                    os.fsync(stream.fileno())
            finally:
                os.close(fd)

            hexdigest = digest.hexdigest()
            marker_data = _TEMP_META.pack(
                _TEMP_MAGIC, max_bytes, count, bytes.fromhex(hexdigest)
            )
            marker_fd = os.open(
                complete,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                0o600,
            )
            with os.fdopen(marker_fd, "wb") as marker:
                if marker.write(marker_data) != len(marker_data):
                    raise StorageIOFailure()
                marker.flush()
                os.fsync(marker.fileno())
            self._unlink_known(writing)
            return TransferObservation(count, hexdigest)
        except AssetStorageError:
            raise
        except Exception:
            raise StorageIOFailure() from None

    def _inspect_temporary(
        self, reference: object,
    ) -> tuple[TemporaryObjectInspection, Path, Path]:
        payload, complete, _writing = self._temp_files(reference)
        payload_info = self._lstat_regular(payload, missing_ok=True)
        marker_info = self._lstat_regular(complete, missing_ok=True)
        if payload_info is None and marker_info is None:
            raise StorageObjectMissing()
        if marker_info is None:
            return TemporaryObjectInspection(False, payload_info.st_size if payload_info else 0, None), payload, complete
        raw = self._read_marker(complete, _TEMP_META.size)
        magic, limit, recorded_size, recorded_digest = _TEMP_META.unpack(raw)
        if magic != _TEMP_MAGIC or recorded_size > limit:
            raise StorageObjectIncomplete()
        if payload_info is None or payload_info.st_size != recorded_size:
            raise StorageObjectIncomplete()
        with self._open_read(payload) as stream:
            observed = self._hash_stream(stream, expected_size=recorded_size)
        if observed.sha256 != recorded_digest.hex():
            raise StorageObjectIncomplete()
        return TemporaryObjectInspection(True, observed.byte_size, observed.sha256), payload, complete

    def inspect_temporary_object(
        self, reference: TemporaryObjectReference, /
    ) -> TemporaryObjectInspection:
        return self._inspect_temporary(reference)[0]

    def _final_paths(self, reference: object) -> tuple[str, Path, Path]:
        self._verify_layout()
        key = self._validate_version(reference)
        return key, self.__versions / f"{key}.blob", self.__versions / f"{key}.manifest"

    def _inspect_final(
        self, reference: object
    ) -> tuple[TransferObservation, bytes, bytes | None, Path, Path]:
        key, object_path, manifest_path = self._final_paths(reference)
        object_info = self._lstat_regular(object_path, missing_ok=True)
        manifest_info = self._lstat_regular(manifest_path, missing_ok=True)
        if object_info is None and manifest_info is None:
            raise StorageObjectMissing()
        if object_info is None or manifest_info is None:
            raise StorageObjectIncomplete()
        if manifest_info.st_size == _FINAL_META.size:
            manifest = self._read_marker(manifest_path, _FINAL_META.size)
            magic, operation_id, count, expected_digest = _FINAL_META.unpack(manifest)
            project_id = None
        elif manifest_info.st_size == _FINAL_META_V3.size:
            manifest = self._read_marker(manifest_path, _FINAL_META_V3.size)
            magic, version_id, project_id, operation_id, temp_id, count, expected_digest = _FINAL_META_V3.unpack(manifest)
            if version_id != UUID(hex=key.removeprefix("ver_")).bytes:
                raise StorageObjectIncomplete()
            try:
                temp_value = f"tmp_{UUID(bytes=temp_id).hex}"
                if temp_value != self._bound_temporary_value(UUID(bytes=project_id), UUID(bytes=operation_id)):
                    raise StorageObjectIncomplete()
            except (ValueError, TypeError):
                raise StorageObjectIncomplete() from None
        elif manifest_info.st_size == _FINAL_META_V2.size:
            manifest = self._read_marker(manifest_path, _FINAL_META_V2.size)
            magic, project_id, operation_id, temp_id, count, expected_digest = _FINAL_META_V2.unpack(manifest)
            try:
                temp_value = f"tmp_{temp_id.hex()}"
                if temp_value != self._bound_temporary_value(UUID(bytes=project_id), UUID(bytes=operation_id)):
                    raise StorageObjectIncomplete()
            except (ValueError, TypeError):
                raise StorageObjectIncomplete() from None
        else:
            raise StorageObjectIncomplete()
        expected_magic = (
            _FINAL_MAGIC if project_id is None
            else _FINAL_MAGIC_V3 if manifest_info.st_size == _FINAL_META_V3.size
            else _FINAL_MAGIC_V2
        )
        if magic != expected_magic or object_info.st_size != count:
            raise StorageObjectIncomplete()
        with self._open_read(object_path) as stream:
            observed = self._hash_stream(stream, expected_size=count)
        if observed.sha256 != expected_digest.hex():
            raise StorageObjectIncomplete()
        return observed, operation_id, project_id, object_path, manifest_path

    def inspect_finalized_object(
        self, object_version: PrivateObjectVersionReference, /
    ) -> TransferObservation:
        return self._inspect_final(object_version)[0]

    def finalize_temporary_object(
        self,
        temporary: TemporaryObjectReference,
        object_version: PrivateObjectVersionReference,
        *,
        expected_sha256: str,
        expected_byte_size: int,
    ) -> FinalizedObject:
        return self._finalize_temporary_object(
            temporary,
            object_version,
            expected_sha256=expected_sha256,
            expected_byte_size=expected_byte_size,
            preserve_temporary=False,
        )

    def finalize_temporary_object_preserving_temporary(
        self,
        temporary: TemporaryObjectReference,
        object_version: PrivateObjectVersionReference,
        *,
        expected_sha256: str,
        expected_byte_size: int,
    ) -> FinalizedObject:
        """Create/verify the immutable object without deleting either object.

        This recovery-only operation requires the project and operation-bound
        temporary reference. The recovery manifest binds those identities, the
        originating temporary ID, exact object reference, observed size and
        digest. A repeated call after an ambiguous outcome safely verifies the
        existing exact manifest and bytes.
        """
        if temporary.project_id is None or temporary.operation_id is None:
            raise StorageInvalidReference()
        return self._finalize_temporary_object(
            temporary,
            object_version,
            expected_sha256=expected_sha256,
            expected_byte_size=expected_byte_size,
            preserve_temporary=True,
        )

    def _finalize_temporary_object(
        self,
        temporary: TemporaryObjectReference,
        object_version: PrivateObjectVersionReference,
        *,
        expected_sha256: str,
        expected_byte_size: int,
        preserve_temporary: bool,
    ) -> FinalizedObject:
        temp_key = self._validate_temporary(temporary)
        version_key = self._validate_version(object_version)
        # Let the locked method inspect a tombstone so it can allow only an
        # exact already-existing finalized object; it never creates after one.
        with self._temporary_guard(temp_key, cleanup=True):
            with self._version_guard(version_key):
                tombstoned = self._lstat_regular(
                    self.__locks / f"{temp_key}.deleted", missing_ok=True
                ) is not None
                if tombstoned:
                    # Cleanup permanently fences new finalization. A retry is
                    # allowed only to verify an exact already-created V3
                    # object; it never creates or repairs the finalized pair.
                    try:
                        observed, operation_bytes, project_bytes, _object_path, manifest_path = self._inspect_final(
                            object_version
                        )
                    except StorageObjectMissing:
                        raise StorageObjectConflict() from None
                    manifest_info = self._lstat_regular(manifest_path)
                    expected_operation = (
                        temporary.operation_id.bytes
                        if temporary.operation_id is not None
                        else UUID(hex=temp_key.removeprefix("tmp_")).bytes
                    )
                    if (
                        manifest_info is None
                        or (temporary.project_id is not None and manifest_info.st_size != _FINAL_META_V3.size)
                        or project_bytes != (temporary.project_id.bytes if temporary.project_id else None)
                        or operation_bytes != expected_operation
                        or observed.byte_size != expected_byte_size
                        or observed.sha256 != expected_sha256
                    ):
                        raise StorageObjectConflict()
                    temp_dir = self.__temporary / temp_key
                    try:
                        self._verify_directory(temp_dir)
                        temp_exists = True
                    except StorageObjectMissing:
                        temp_exists = False
                    cleanup_confirmed = not temp_exists
                    if temp_exists and not preserve_temporary:
                        try:
                            self._delete_temporary_object_locked(temporary)
                            cleanup_confirmed = True
                            temp_exists = False
                        except (StorageCleanupNotConfirmed, StorageIOFailure, StorageInvalidReference):
                            cleanup_confirmed = False
                    return FinalizedObject(
                        object_version=object_version,
                        byte_size=observed.byte_size,
                        sha256=observed.sha256,
                        temporary_cleanup_confirmed=cleanup_confirmed,
                        project_id=temporary.project_id,
                        operation_id=temporary.operation_id,
                        temporary_preserved=temp_exists,
                    )
                version_tombstoned = self._lstat_regular(
                    self.__locks / f"version-{version_key.removeprefix('ver_')}.deleted",
                    missing_ok=True,
                ) is not None
                if version_tombstoned:
                    raise StorageObjectConflict()
                return self._finalize_temporary_object_locked(
                    temporary,
                    object_version,
                    expected_sha256=expected_sha256,
                    expected_byte_size=expected_byte_size,
                    preserve_temporary=preserve_temporary,
                )

    def _finalize_temporary_object_locked(
        self,
        temporary: TemporaryObjectReference,
        object_version: PrivateObjectVersionReference,
        *,
        expected_sha256: str,
        expected_byte_size: int,
        preserve_temporary: bool,
    ) -> FinalizedObject:
        temp_key = self._validate_temporary(temporary)
        version_key, destination, manifest_path = self._final_paths(object_version)
        if (type(expected_sha256) is not str or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256)
                or type(expected_byte_size) is not int or expected_byte_size < 0):
            raise StorageObjectIncomplete()
        bound = temporary.project_id is not None
        operation_id = (temporary.operation_id.bytes if bound
                        else UUID(hex=temp_key.removeprefix("tmp_")).bytes)
        project_id = temporary.project_id.bytes if bound else None
        try:
            inspection, source, _complete = self._inspect_temporary(temporary)
        except StorageObjectMissing:
            # A retry after successful finalization may arrive after temporary
            # cleanup. The persisted manifest proves this exact temp operation
            # and expected byte observation already finalized this reference.
            try:
                observed, actual_operation_id, actual_project_id, _object, existing_manifest_path = self._inspect_final(object_version)
            except StorageObjectMissing:
                raise
            if preserve_temporary:
                manifest_info = self._lstat_regular(existing_manifest_path)
                if manifest_info is None or manifest_info.st_size != _FINAL_META_V3.size:
                    raise StorageObjectConflict() from None
            if (actual_operation_id != operation_id or actual_project_id != project_id
                    or observed.byte_size != expected_byte_size
                    or observed.sha256 != expected_sha256):
                raise StorageObjectConflict() from None
            return FinalizedObject(
                object_version=PrivateObjectVersionReference(value=version_key),
                byte_size=observed.byte_size,
                sha256=observed.sha256,
                temporary_cleanup_confirmed=True,
                project_id=temporary.project_id,
                operation_id=temporary.operation_id,
                temporary_preserved=False,
            )
        if not inspection.complete or inspection.sha256 is None:
            raise StorageObjectIncomplete()
        if inspection.byte_size != expected_byte_size or inspection.sha256 != expected_sha256:
            raise StorageObjectConflict()
        if inspection.byte_size == 0:
            # The provider records empty transfers, but media admission rejects
            # them; current asset-version persistence also requires > 0 bytes.
            raise StorageObjectIncomplete()

        if bound:
            manifest_data = _FINAL_META_V3.pack(
                _FINAL_MAGIC_V3,
                UUID(hex=version_key.removeprefix("ver_")).bytes,
                project_id,
                operation_id,
                UUID(hex=temp_key.removeprefix("tmp_")).bytes,
                inspection.byte_size,
                bytes.fromhex(inspection.sha256),
            )
        else:
            manifest_data = _FINAL_META.pack(
                _FINAL_MAGIC, operation_id, inspection.byte_size, bytes.fromhex(inspection.sha256)
            )
        existing_manifest = self._lstat_regular(manifest_path, missing_ok=True)
        existing_object = self._lstat_regular(destination, missing_ok=True)
        if existing_manifest is None and existing_object is not None:
            raise StorageObjectConflict()
        if existing_manifest is None:
            try:
                self._verify_layout()
                fd = os.open(
                    manifest_path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                with os.fdopen(fd, "wb") as manifest:
                    if manifest.write(manifest_data) != len(manifest_data):
                        raise StorageIOFailure()
                    manifest.flush()
                    os.fsync(manifest.fileno())
                self._verify_layout()
            except FileExistsError:
                pass
            except StorageIOFailure:
                raise
            except OSError:
                raise StorageIOFailure() from None
        if existing_manifest is not None and existing_manifest.st_size != len(manifest_data):
            if existing_manifest.st_size in {
                _FINAL_META.size, _FINAL_META_V2.size, _FINAL_META_V3.size,
            }:
                raise StorageObjectConflict()
            raise StorageObjectIncomplete()
        current_manifest = self._read_marker(manifest_path, len(manifest_data))
        if current_manifest != manifest_data:
            raise StorageObjectConflict()

        existing_object = self._lstat_regular(destination, missing_ok=True)
        if existing_object is None:
            try:
                # Hard-link creation is atomic and fails if the target exists.
                # No rename/copy fallback is permitted.
                self._verify_layout()
                os.link(source, destination, follow_symlinks=False)
                self._verify_layout()
            except FileExistsError:
                pass
            except OSError as exc:
                if (exc.errno in (errno.EXDEV, errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOSYS)
                        or getattr(exc, "winerror", None) in {1, 17, 50, 1314}):
                    raise StorageAtomicOperationUnsupported() from None
                raise StorageIOFailure() from None
            except (NotImplementedError, TypeError):
                raise StorageAtomicOperationUnsupported() from None

        observed, actual_operation_id, actual_project_id, _destination, _manifest = self._inspect_final(object_version)
        if (actual_operation_id != operation_id or actual_project_id != project_id
                or observed.byte_size != expected_byte_size
                or observed.sha256 != expected_sha256):
            raise StorageObjectConflict()
        if preserve_temporary:
            manifest_info = self._lstat_regular(manifest_path)
            if manifest_info is None or manifest_info.st_size != _FINAL_META_V3.size:
                raise StorageObjectConflict()
        cleanup_confirmed = False
        if not preserve_temporary:
            cleanup_confirmed = True
            try:
                self._mark_temporary_deleted(temp_key)
                self._delete_temporary_object_locked(temporary)
            except (StorageCleanupNotConfirmed, StorageIOFailure, StorageInvalidReference):
                cleanup_confirmed = False
        return FinalizedObject(
            object_version=PrivateObjectVersionReference(value=version_key),
            byte_size=observed.byte_size,
            sha256=observed.sha256,
            temporary_cleanup_confirmed=cleanup_confirmed,
            project_id=temporary.project_id,
            operation_id=temporary.operation_id,
            temporary_preserved=preserve_temporary,
        )

    def open_exact_version(
        self, object_version: PrivateObjectVersionReference, /
    ) -> BinaryIO:
        _key, object_path, manifest_path = self._final_paths(object_version)
        object_info = self._lstat_regular(object_path)
        manifest_info = self._lstat_regular(manifest_path)
        assert object_info is not None and manifest_info is not None
        if manifest_info.st_size == _FINAL_META.size:
            manifest = self._read_marker(manifest_path, _FINAL_META.size)
            magic, _operation_id, count, _digest = _FINAL_META.unpack(manifest)
            valid_magic = magic == _FINAL_MAGIC
        elif manifest_info.st_size == _FINAL_META_V2.size:
            manifest = self._read_marker(manifest_path, _FINAL_META_V2.size)
            magic, _project, _operation, _temp, count, _digest = _FINAL_META_V2.unpack(manifest)
            valid_magic = magic == _FINAL_MAGIC_V2
        elif manifest_info.st_size == _FINAL_META_V3.size:
            manifest = self._read_marker(manifest_path, _FINAL_META_V3.size)
            magic, version_id, _project, _operation, _temp, count, _digest = _FINAL_META_V3.unpack(manifest)
            valid_magic = (
                magic == _FINAL_MAGIC_V3
                and version_id == UUID(hex=self._validate_version(object_version).removeprefix("ver_")).bytes
            )
        else:
            raise StorageObjectIncomplete()
        if not valid_magic or object_info.st_size != count:
            raise StorageObjectIncomplete()
        return self._open_read(object_path)

    def _unlink_known(self, path: Path) -> bool:
        self._verify_layout()
        if self._lstat_regular(path, missing_ok=True) is None:
            return True
        try:
            self._verify_layout()
            if self._lstat_regular(path, missing_ok=True) is None:
                return True
            path.unlink()
            self._verify_layout()
            return self._lstat_regular(path, missing_ok=True) is None
        except OSError:
            return False

    def delete_temporary_object(
        self, reference: TemporaryObjectReference, /, *,
        project_id: UUID | None = None,
        asset_id: UUID | None = None,
        intent_id: UUID | None = None,
        claim_token: UUID | None = None,
        cleanup_revision: int | None = None,
        cleanup_generation: int | None = None,
    ) -> CleanupConfirmation:
        value = self._validate_temporary(reference)
        bound = any(value is not None for value in (
            project_id, asset_id, intent_id, claim_token, cleanup_revision, cleanup_generation
        ))
        if bound:
            if (
                reference.project_id != project_id
                or reference.operation_id != intent_id
                or type(asset_id) is not UUID
                or type(claim_token) is not UUID
                or type(cleanup_revision) is not int or cleanup_revision < 0
                or type(cleanup_generation) is not int or cleanup_generation < 1
            ):
                raise StorageInvalidReference()
        with self._temporary_guard(value, cleanup=True):
            self._mark_temporary_deleted(value)
            result = self._delete_temporary_object_locked(reference)
            if not bound:
                return result
            return self._issue_cleanup_confirmation(
                reference=reference, physically_absent=True,
                target_kind="temporary_upload", project_id=project_id,
                cleanup_operation="temporary_object_delete",
                asset_id=asset_id, intent_id=intent_id, operation_id=intent_id,
                claim_token=claim_token,
                cleanup_revision=cleanup_revision,
                cleanup_generation=cleanup_generation,
            )

    def _delete_temporary_object_locked(
        self, reference: TemporaryObjectReference
    ) -> CleanupConfirmation:
        directory = self._temp_dir(reference)
        try:
            self._verify_directory(directory)
        except StorageObjectMissing:
            return CleanupConfirmation(reference, True)
        self._verify_temporary_binding(reference, directory)
        expected = {"payload", "complete", "writing"}
        if reference.project_id is not None:
            expected.add("binding")
        try:
            if any(entry.name not in expected for entry in directory.iterdir()):
                raise StorageCleanupNotConfirmed()
            for name in expected:
                if not self._unlink_known(directory / name):
                    raise StorageCleanupNotConfirmed()
            self._verify_layout()
            directory.rmdir()
            self._verify_layout()
            if directory.exists() or directory.is_symlink():
                raise StorageCleanupNotConfirmed()
            return CleanupConfirmation(reference, True)
        except (StorageInvalidReference, StorageCleanupNotConfirmed):
            raise StorageCleanupNotConfirmed() from None
        except OSError:
            raise StorageCleanupNotConfirmed() from None

    def delete_finalized_object(
        self, object_version: PrivateObjectVersionReference, /, *,
        project_id: UUID,
        asset_id: UUID,
        intent_id: UUID,
        claim_token: UUID,
        cleanup_revision: int,
        cleanup_generation: int,
    ) -> CleanupConfirmation:
        value = self._validate_version(object_version)
        if (
            type(project_id) is not UUID or type(asset_id) is not UUID
            or type(intent_id) is not UUID
            or type(claim_token) is not UUID
            or type(cleanup_revision) is not int or cleanup_revision < 0
            or type(cleanup_generation) is not int or cleanup_generation < 1
        ):
            raise StorageCleanupNotConfirmed()
        with self._version_guard(value, cleanup=True):
            _key, object_path, manifest_path = self._final_paths(object_version)
            object_info = self._lstat_regular(object_path, missing_ok=True)
            manifest_info = self._lstat_regular(manifest_path, missing_ok=True)
            if object_info is not None and manifest_info is None:
                # A blob without its provenance manifest cannot authorize
                # deletion or accounting release.
                raise StorageCleanupNotConfirmed()
            if manifest_info is not None:
                # V2 binds a project and operation, but not the exact
                # immutable version reference. It is readable for legacy
                # access but cannot authorize physical deletion.
                if manifest_info.st_size != _FINAL_META_V3.size:
                    raise StorageCleanupNotConfirmed()
                if object_info is not None:
                    _observed, operation_bytes, project_bytes, _object, _manifest = self._inspect_final(object_version)
                else:
                    manifest = self._read_marker(manifest_path, _FINAL_META_V3.size)
                    magic, version_bytes, project_bytes, operation_bytes, temp_bytes, count, digest = _FINAL_META_V3.unpack(manifest)
                    try:
                        expected_version = UUID(hex=value.removeprefix("ver_")).bytes
                        expected_temp = self._bound_temporary_value(project_id, intent_id)
                        actual_temp = f"tmp_{UUID(bytes=temp_bytes).hex}"
                    except (TypeError, ValueError):
                        raise StorageCleanupNotConfirmed() from None
                    if (
                        magic != _FINAL_MAGIC_V3
                        or version_bytes != expected_version
                        or actual_temp != expected_temp
                        or count <= 0
                        or len(digest) != 32
                    ):
                        raise StorageCleanupNotConfirmed()
                if project_bytes != project_id.bytes or operation_bytes != intent_id.bytes:
                    raise StorageCleanupNotConfirmed()
            elif object_info is None:
                # Idempotent absent/absent success is allowed only after this
                # exact version has a durable local tombstone.
                tombstone = self.__locks / f"version-{value.removeprefix('ver_')}.deleted"
                tombstone_info = self._lstat_regular(tombstone, missing_ok=True)
                marker = b"Spotloom finalized version deleted v1\n"
                if (
                    tombstone_info is None
                    or self._read_marker(tombstone, len(marker)) != marker
                ):
                    raise StorageCleanupNotConfirmed()

            self._mark_version_deleted(value)
            return self._delete_finalized_object_locked(
                object_version,
                project_id=project_id,
                asset_id=asset_id,
                intent_id=intent_id,
                claim_token=claim_token,
                cleanup_revision=cleanup_revision,
                cleanup_generation=cleanup_generation,
                manifest_only=object_info is None and manifest_info is not None,
                bound=True,
            )

    def _delete_finalized_object_locked(
        self, object_version: PrivateObjectVersionReference, /, *,
        project_id: UUID | None = None,
        asset_id: UUID | None = None,
        intent_id: UUID | None = None,
        claim_token: UUID | None = None,
        cleanup_revision: int | None = None,
        cleanup_generation: int | None = None,
        manifest_only: bool = False,
        bound: bool | None = None,
    ) -> CleanupConfirmation:
        _key, object_path, manifest_path = self._final_paths(object_version)
        try:
            if bound is None:
                bound = any(value is not None for value in (
                    project_id, asset_id, intent_id, claim_token,
                    cleanup_revision, cleanup_generation,
                ))
            if bound and (
                type(project_id) is not UUID or type(asset_id) is not UUID
                or type(intent_id) is not UUID or type(claim_token) is not UUID
                or type(cleanup_revision) is not int or cleanup_revision < 0
                or type(cleanup_generation) is not int or cleanup_generation < 1
            ):
                raise StorageCleanupNotConfirmed()
            if not bound:
                raise StorageCleanupNotConfirmed()
            if manifest_only:
                if self._lstat_regular(object_path, missing_ok=True) is not None:
                    raise StorageCleanupNotConfirmed()
                if not self._unlink_known(manifest_path):
                    raise StorageCleanupNotConfirmed()
            else:
                if not self._unlink_known(object_path):
                    raise StorageCleanupNotConfirmed()
                if not self._unlink_known(manifest_path):
                    raise StorageCleanupNotConfirmed()
            if (
                self._lstat_regular(object_path, missing_ok=True) is not None
                or self._lstat_regular(manifest_path, missing_ok=True) is not None
            ):
                raise StorageCleanupNotConfirmed()
            return self._issue_cleanup_confirmation(
                reference=object_version,
                physically_absent=True,
                target_kind="asset_version",
                cleanup_operation="finalized_object_delete",
                project_id=project_id,
                asset_id=asset_id,
                intent_id=intent_id,
                operation_id=intent_id,
                claim_token=claim_token,
                cleanup_revision=cleanup_revision,
                cleanup_generation=cleanup_generation,
            )
        except (StorageInvalidReference, StorageCleanupNotConfirmed):
            raise StorageCleanupNotConfirmed() from None
        except OSError:
            raise StorageCleanupNotConfirmed() from None
