from __future__ import annotations

import errno
import hashlib
import os
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest

from adforge_renderer.asset_contract import PrivateObjectVersionReference
from adforge_renderer.asset_storage_provider import (
    MAX_STORAGE_CHUNK_BYTES,
    StorageAtomicOperationUnsupported,
    StorageCleanupNotConfirmed,
    StorageConfigurationError,
    StorageIOFailure,
    StorageInvalidReference,
    StorageObjectConflict,
    StorageObjectIncomplete,
    StorageObjectMissing,
    StorageSizeLimitExceeded,
    TemporaryObjectReference,
)
from adforge_renderer.local_asset_storage import (
    LocalAssetStorageConfig,
    LocalPrivateAssetStorage,
)


def make_storage(tmp_path: Path) -> LocalPrivateAssetStorage:
    return LocalPrivateAssetStorage(LocalAssetStorageConfig(tmp_path / "private-assets"))


def store_bytes(storage: LocalPrivateAssetStorage, payload: bytes, *, max_bytes: int = 10_000):
    temporary = storage.create_temporary_object()
    observation = storage.write_temporary_object(
        temporary, (payload[index:index + 7] for index in range(0, len(payload), 7)),
        max_bytes=max_bytes,
    )
    return temporary, observation


def test_configuration_requires_explicit_absolute_root_and_rejects_repository_roots(
    tmp_path: Path,
) -> None:
    with pytest.raises(StorageConfigurationError):
        LocalAssetStorageConfig.from_environment({})
    with pytest.raises(StorageConfigurationError):
        LocalAssetStorageConfig.from_environment({"SPOTLOOM_ASSET_STORAGE_ROOT": "relative/path"})
    with pytest.raises(StorageConfigurationError):
        LocalAssetStorageConfig.from_environment(
            {"SPOTLOOM_ASSET_STORAGE_ROOT": str(Path(__file__).resolve().parents[2] / "backend" / "data")}
        )
    with pytest.raises(StorageConfigurationError):
        LocalAssetStorageConfig.from_environment(
            {"SPOTLOOM_ASSET_STORAGE_ROOT": str(tmp_path / "public" / "asset-store")}
        )


def test_references_are_opaque_generated_and_invalid_paths_are_rejected(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary = storage.create_temporary_object()
    version = storage.new_object_version_reference()
    assert temporary.value.startswith("tmp_")
    assert version.value.startswith("ver_")
    assert "/" not in temporary.value and "\\" not in temporary.value
    assert "/" not in version.value and "\\" not in version.value

    for invalid in (
        TemporaryObjectReference("../../escape"),
        TemporaryObjectReference("C:\\outside"),
        TemporaryObjectReference("tmp_" + "A" * 32),
    ):
        with pytest.raises(StorageInvalidReference):
            storage.inspect_temporary_object(invalid)
    with pytest.raises(StorageInvalidReference):
        storage.open_exact_version(PrivateObjectVersionReference(value="latest"))


def test_project_operation_bound_reference_allocation_is_stable_and_private(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    project_id, operation_id = uuid4(), uuid4()
    reference = storage.allocate_temporary_reference(
        project_id=project_id, operation_id=operation_id
    )
    assert reference == storage.allocate_temporary_reference(
        project_id=project_id, operation_id=operation_id
    )
    assert reference.value.startswith("tmp_") and len(reference.value) == 36
    assert "/" not in reference.value and "\\" not in reference.value
    assert reference != storage.allocate_temporary_reference(
        project_id=uuid4(), operation_id=operation_id
    )
    assert reference != storage.allocate_temporary_reference(
        project_id=project_id, operation_id=uuid4()
    )
    assert not (tmp_path / "private-assets" / "temporary" / reference.value).exists()

    storage.create_temporary_object(reference)
    # Re-materialization after a lost response is safe and never truncates.
    assert storage.create_temporary_object(reference) == reference
    with pytest.raises(StorageInvalidReference):
        storage.inspect_temporary_object(
            type(reference)(reference.value, uuid4(), operation_id)
        )
    observed = storage.write_temporary_object(reference, [b"bound bytes"], max_bytes=100)
    assert storage.inspect_temporary_object(reference).sha256 == observed.sha256
    version = storage.new_object_version_reference()
    finalized = storage.finalize_temporary_object(
        reference, version, expected_sha256=observed.sha256,
        expected_byte_size=observed.byte_size,
    )
    assert (finalized.project_id, finalized.operation_id) == (project_id, operation_id)
    assert storage.inspect_finalized_object(version) == observed
    retry = storage.finalize_temporary_object(
        reference, version, expected_sha256=observed.sha256,
        expected_byte_size=observed.byte_size,
    )
    assert (retry.project_id, retry.operation_id) == (project_id, operation_id)
    foreign_reference = storage.allocate_temporary_reference(
        project_id=uuid4(), operation_id=operation_id
    )
    with pytest.raises(StorageObjectConflict):
        storage.finalize_temporary_object(
            foreign_reference, version, expected_sha256=observed.sha256,
            expected_byte_size=observed.byte_size,
        )


def test_recovery_finalization_preserves_both_objects_and_is_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = make_storage(tmp_path)
    project_id, intent_id = uuid4(), uuid4()
    temporary = storage.allocate_temporary_reference(
        project_id=project_id, operation_id=intent_id
    )
    storage.create_temporary_object(temporary)
    payload = b"recovery finalization keeps the source until reconciliation"
    observation = storage.write_temporary_object(temporary, [payload], max_bytes=1024)
    version = storage.new_object_version_reference()

    def no_delete(*_args, **_kwargs):
        raise AssertionError("Recovery finalization must never delete an object.")

    monkeypatch.setattr(storage, "delete_temporary_object", no_delete)
    monkeypatch.setattr(storage, "delete_finalized_object", no_delete)
    finalized = storage.finalize_temporary_object_preserving_temporary(
        temporary,
        version,
        expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    assert finalized.temporary_preserved is True
    assert finalized.temporary_cleanup_confirmed is False
    assert finalized.project_id == project_id
    assert finalized.operation_id == intent_id
    assert storage.inspect_temporary_object(temporary).complete
    assert storage.inspect_finalized_object(version) == observation

    repeated = storage.finalize_temporary_object_preserving_temporary(
        temporary,
        version,
        expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    assert repeated == finalized
    assert storage.inspect_temporary_object(temporary).complete


def test_recovery_finalization_rejects_wrong_provenance_and_observations(
    tmp_path: Path,
) -> None:
    storage = make_storage(tmp_path)
    project_id, intent_id = uuid4(), uuid4()
    temporary = storage.allocate_temporary_reference(
        project_id=project_id, operation_id=intent_id
    )
    storage.create_temporary_object(temporary)
    observation = storage.write_temporary_object(temporary, [b"exact recovery bytes"], max_bytes=100)
    version = storage.new_object_version_reference()

    with pytest.raises(StorageInvalidReference):
        storage.finalize_temporary_object_preserving_temporary(
            TemporaryObjectReference(temporary.value),
            version,
            expected_sha256=observation.sha256,
            expected_byte_size=observation.byte_size,
        )
    with pytest.raises(StorageObjectConflict):
        storage.finalize_temporary_object_preserving_temporary(
            temporary,
            version,
            expected_sha256="0" * 64,
            expected_byte_size=observation.byte_size,
        )
    with pytest.raises(StorageObjectConflict):
        storage.finalize_temporary_object_preserving_temporary(
            temporary,
            version,
            expected_sha256=observation.sha256,
            expected_byte_size=observation.byte_size + 1,
        )

    storage.finalize_temporary_object_preserving_temporary(
        temporary,
        version,
        expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    other_project = uuid4()
    other_temporary = storage.allocate_temporary_reference(
        project_id=other_project, operation_id=uuid4()
    )
    storage.create_temporary_object(other_temporary)
    storage.write_temporary_object(other_temporary, [b"exact recovery bytes"], max_bytes=100)
    foreign_version = storage.new_object_version_reference()
    foreign_observation = storage.inspect_temporary_object(other_temporary)
    storage.finalize_temporary_object_preserving_temporary(
        other_temporary,
        foreign_version,
        expected_sha256=foreign_observation.sha256,
        expected_byte_size=foreign_observation.byte_size,
    )
    with pytest.raises(StorageObjectConflict):
        storage.finalize_temporary_object_preserving_temporary(
            temporary,
            foreign_version,
            expected_sha256=observation.sha256,
            expected_byte_size=observation.byte_size,
        )


def test_recovery_finalization_retries_after_ambiguous_link_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import adforge_renderer.local_asset_storage as local_storage_module

    storage = make_storage(tmp_path)
    temporary = storage.allocate_temporary_reference(project_id=uuid4(), operation_id=uuid4())
    storage.create_temporary_object(temporary)
    observation = storage.write_temporary_object(temporary, [b"atomic link outcome"], max_bytes=100)
    version = storage.new_object_version_reference()
    real_link = local_storage_module.os.link

    def link_then_lose_response(source, destination, **kwargs) -> None:
        real_link(source, destination, **kwargs)
        raise OSError("simulated ambiguous link response")

    monkeypatch.setattr(local_storage_module.os, "link", link_then_lose_response)
    with pytest.raises(StorageIOFailure):
        storage.finalize_temporary_object_preserving_temporary(
            temporary,
            version,
            expected_sha256=observation.sha256,
            expected_byte_size=observation.byte_size,
        )

    # Recovery retries inspect and verify the already-created exact final
    # object; neither object is replaced or removed.
    monkeypatch.setattr(local_storage_module.os, "link", real_link)
    recovered = storage.finalize_temporary_object_preserving_temporary(
        temporary,
        version,
        expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    assert recovered.temporary_preserved
    assert storage.inspect_temporary_object(temporary).complete
    assert storage.inspect_finalized_object(version) == observation


def test_bound_temporary_reference_rejects_foreign_context_and_cleans_only_bound_object(
    tmp_path: Path,
) -> None:
    storage = make_storage(tmp_path)
    project_id, operation_id = uuid4(), uuid4()
    reference = storage.allocate_temporary_reference(
        project_id=project_id, operation_id=operation_id
    )
    storage.create_temporary_object(reference)
    foreign = type(reference)(reference.value, uuid4(), operation_id)
    with pytest.raises(StorageInvalidReference):
        storage.write_temporary_object(foreign, [b"no"], max_bytes=10)
    assert storage.delete_temporary_object(reference).physically_absent


def test_exclusive_temporary_creation_streaming_observation_and_exact_read(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    first = storage.create_temporary_object()
    assert first != storage.create_temporary_object()

    payload = b"bounded chunks are streamed, not trusted metadata"
    observation = storage.write_temporary_object(
        first,
        (payload[index:index + 5] for index in range(0, len(payload), 5)),
        max_bytes=len(payload),
    )
    assert observation.byte_size == len(payload)
    assert observation.sha256 == hashlib.sha256(payload).hexdigest()
    assert storage.inspect_temporary_object(first).complete

    version = storage.new_object_version_reference()
    finalized = storage.finalize_temporary_object(
        first, version, expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    assert finalized.object_version == version
    assert finalized.temporary_cleanup_confirmed
    with storage.open_exact_version(version) as stream:
        assert stream.read() == payload
    assert storage.inspect_finalized_object(version) == observation


def test_empty_stream_is_observed_but_not_finalized_as_an_asset_version(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary = storage.create_temporary_object()
    observation = storage.write_temporary_object(temporary, iter(()), max_bytes=10)
    assert observation.byte_size == 0
    assert observation.sha256 == hashlib.sha256(b"").hexdigest()
    assert storage.inspect_temporary_object(temporary).complete
    with pytest.raises(StorageObjectIncomplete):
        storage.finalize_temporary_object(
            temporary, storage.new_object_version_reference(),
            expected_sha256=observation.sha256, expected_byte_size=0,
        )


def test_size_limit_and_oversized_chunk_fail_without_completing_object(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary = storage.create_temporary_object()
    with pytest.raises(StorageSizeLimitExceeded):
        storage.write_temporary_object(temporary, [b"1234", b"56"], max_bytes=5)
    assert not storage.inspect_temporary_object(temporary).complete
    assert storage.delete_temporary_object(temporary).physically_absent

    oversized = storage.create_temporary_object()
    with pytest.raises(StorageSizeLimitExceeded):
        storage.write_temporary_object(
            oversized, [b"x" * (MAX_STORAGE_CHUNK_BYTES + 1)],
            max_bytes=MAX_STORAGE_CHUNK_BYTES * 2,
        )
    assert not storage.inspect_temporary_object(oversized).complete


def test_stream_source_is_closed_when_a_limit_is_exceeded(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary = storage.create_temporary_object()
    closed: list[bool] = []

    def chunks():
        try:
            yield b"1234"
            yield b"56"
        finally:
            closed.append(True)

    with pytest.raises(StorageSizeLimitExceeded):
        storage.write_temporary_object(temporary, chunks(), max_bytes=5)
    assert closed == [True]


def test_incomplete_and_interrupted_writes_are_not_readable_and_can_be_cleaned(
    tmp_path: Path,
) -> None:
    storage = make_storage(tmp_path)
    incomplete = storage.create_temporary_object()
    assert storage.inspect_temporary_object(incomplete).complete is False

    interrupted = storage.create_temporary_object()

    def chunks():
        yield b"prefix"
        raise RuntimeError("private simulated transport detail")

    with pytest.raises(StorageIOFailure) as error:
        storage.write_temporary_object(interrupted, chunks(), max_bytes=100)
    assert "private simulated" not in str(error.value)
    assert not storage.inspect_temporary_object(interrupted).complete
    with pytest.raises(StorageObjectIncomplete):
        storage.finalize_temporary_object(
            interrupted, storage.new_object_version_reference(),
            expected_sha256=hashlib.sha256(b"prefix").hexdigest(), expected_byte_size=6,
        )
    assert storage.delete_temporary_object(interrupted).physically_absent


def test_finalization_is_no_overwrite_conflict_safe_and_same_operation_retryable(
    tmp_path: Path,
) -> None:
    storage = make_storage(tmp_path)
    temp_a, observed_a = store_bytes(storage, b"first object")
    version = storage.new_object_version_reference()
    created = storage.finalize_temporary_object(
        temp_a, version, expected_sha256=observed_a.sha256,
        expected_byte_size=observed_a.byte_size,
    )
    assert created.temporary_cleanup_confirmed
    retry = storage.finalize_temporary_object(
        temp_a, version, expected_sha256=observed_a.sha256,
        expected_byte_size=observed_a.byte_size,
    )
    assert retry.object_version == version
    assert retry.sha256 == observed_a.sha256

    temp_b, observed_b = store_bytes(storage, b"different object")
    with pytest.raises(StorageObjectConflict):
        storage.finalize_temporary_object(
            temp_b, version, expected_sha256=observed_b.sha256,
            expected_byte_size=observed_b.byte_size,
        )
    with storage.open_exact_version(version) as stream:
        assert stream.read() == b"first object"
    assert storage.inspect_temporary_object(temp_b).complete


def test_finalization_reports_unconfirmed_temp_cleanup_and_retry_recovers_it(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary, observation = store_bytes(storage, b"final object with pending cleanup")
    version = storage.new_object_version_reference()
    temp_dir = tmp_path / "private-assets" / "temporary" / temporary.value
    unexpected = temp_dir / "left-by-an-interrupted-operation"
    unexpected.write_bytes(b"preserve unknown file")

    first = storage.finalize_temporary_object(
        temporary, version, expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    assert first.temporary_cleanup_confirmed is False
    assert unexpected.exists()
    assert storage.inspect_finalized_object(version) == observation

    unexpected.unlink()
    retried = storage.finalize_temporary_object(
        temporary, version, expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    assert retried.temporary_cleanup_confirmed is True
    assert storage.delete_temporary_object(temporary).physically_absent


def test_finalization_rejects_preexisting_unmanifested_destination(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary, observation = store_bytes(storage, b"expected")
    version = storage.new_object_version_reference()
    key = version.value
    versions_dir = tmp_path / "private-assets" / "versions"
    (versions_dir / f"{key}.blob").write_bytes(b"other")
    with pytest.raises(StorageObjectConflict):
        storage.finalize_temporary_object(
            temporary, version, expected_sha256=observation.sha256,
            expected_byte_size=observation.byte_size,
        )
    assert (versions_dir / f"{key}.blob").read_bytes() == b"other"


def test_unsupported_atomic_finalization_fails_closed_without_rename_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    storage = make_storage(tmp_path)
    temporary, observation = store_bytes(storage, b"must not be renamed")
    version = storage.new_object_version_reference()

    def unsupported_link(*_args, **_kwargs):
        raise OSError(errno.EXDEV, "simulated cross-filesystem operation")

    monkeypatch.setattr("adforge_renderer.local_asset_storage.os.link", unsupported_link)
    with pytest.raises(StorageAtomicOperationUnsupported) as error:
        storage.finalize_temporary_object(
            temporary, version, expected_sha256=observation.sha256,
            expected_byte_size=observation.byte_size,
        )
    assert str(tmp_path) not in str(error.value)
    assert not (tmp_path / "private-assets" / "versions" / f"{version.value}.blob").exists()
    assert storage.delete_finalized_object(version).physically_absent
    assert storage.inspect_temporary_object(temporary).complete


def test_finalized_bytes_are_checked_against_the_private_manifest(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary, observation = store_bytes(storage, b"immutable content")
    version = storage.new_object_version_reference()
    storage.finalize_temporary_object(
        temporary, version, expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    object_path = tmp_path / "private-assets" / "versions" / f"{version.value}.blob"
    object_path.write_bytes(b"tampered content")
    with pytest.raises(StorageObjectIncomplete):
        storage.inspect_finalized_object(version)


def test_temporary_and_final_cleanup_are_idempotent_and_confirm_absence(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary, observation = store_bytes(storage, b"cleanup me")
    assert storage.delete_temporary_object(temporary).physically_absent
    assert storage.delete_temporary_object(temporary).physically_absent

    temporary, observation = store_bytes(storage, b"final cleanup")
    version = storage.new_object_version_reference()
    storage.finalize_temporary_object(
        temporary, version, expected_sha256=observation.sha256,
        expected_byte_size=observation.byte_size,
    )
    assert storage.delete_finalized_object(version).physically_absent
    assert storage.delete_finalized_object(version).physically_absent
    with pytest.raises(StorageObjectMissing):
        storage.open_exact_version(version)


def test_unknown_files_prevent_temporary_directory_cleanup(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary = storage.create_temporary_object()
    temp_dir = tmp_path / "private-assets" / "temporary" / temporary.value
    (temp_dir / "unknown").write_text("do not sweep")
    with pytest.raises(StorageCleanupNotConfirmed):
        storage.delete_temporary_object(temporary)
    assert (temp_dir / "unknown").exists()


def test_symlinked_payload_and_replaced_storage_directory_fail_closed(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside sentinel")
    temporary = storage.create_temporary_object()
    payload = tmp_path / "private-assets" / "temporary" / temporary.value / "payload"
    payload.unlink()
    try:
        os.symlink(outside, payload)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink creation is unavailable for this account/platform: {type(exc).__name__}")
    with pytest.raises(StorageInvalidReference):
        storage.write_temporary_object(temporary, [b"overwrite"], max_bytes=100)
    assert outside.read_bytes() == b"outside sentinel"

    temporary_root = tmp_path / "private-assets" / "temporary"
    moved = tmp_path / "private-assets" / "temporary-moved"
    temporary_root.rename(moved)
    try:
        os.symlink(tmp_path, temporary_root, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink creation is unavailable: {type(exc).__name__}")
    with pytest.raises(StorageIOFailure):
        storage.create_temporary_object()


@pytest.mark.skipif(os.name != "nt", reason="Windows junction checks require Windows.")
def test_windows_junction_replacement_fails_closed(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    temporary_root = tmp_path / "private-assets" / "temporary"
    moved = tmp_path / "private-assets" / "temporary-moved"
    temporary_root.rename(moved)
    result = subprocess.run(
        ["cmd.exe", "/c", f'mklink /J "{temporary_root}" "{tmp_path}"'],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        moved.rename(temporary_root)
        pytest.skip(f"junction creation is unavailable: cmd exit {result.returncode}")
    try:
        with pytest.raises(StorageIOFailure):
            storage.create_temporary_object()
    finally:
        os.rmdir(temporary_root)
        moved.rename(temporary_root)


@pytest.mark.skipif(os.name != "nt", reason="Windows reparse-point checks require Windows.")
def test_windows_hardlink_finalization_is_create_only_and_cleans_inside_root(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    payload = b"Windows create-only finalization"
    temporary, observed = store_bytes(storage, payload)
    version = storage.new_object_version_reference()
    result = storage.finalize_temporary_object(
        temporary, version, expected_sha256=observed.sha256,
        expected_byte_size=observed.byte_size,
    )
    assert result.temporary_cleanup_confirmed
    assert storage.inspect_finalized_object(version) == observed
    final_path = tmp_path / "private-assets" / "versions" / f"{version.value}.blob"
    assert final_path.exists()
    with storage.open_exact_version(version) as stream:
        assert stream.read() == payload

    other, other_observation = store_bytes(storage, b"different")
    with pytest.raises(StorageObjectConflict):
        storage.finalize_temporary_object(
            other, version, expected_sha256=other_observation.sha256,
            expected_byte_size=other_observation.byte_size,
        )
    assert final_path.read_bytes() == payload
    assert storage.delete_finalized_object(version).physically_absent
    assert not final_path.exists()


def test_missing_directory_or_bad_reference_never_triggers_sweeping(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    unknown = TemporaryObjectReference("tmp_" + "0" * 32)
    assert storage.delete_temporary_object(unknown).physically_absent
    with pytest.raises(StorageInvalidReference):
        storage.delete_finalized_object(PrivateObjectVersionReference(value="../outside"))
