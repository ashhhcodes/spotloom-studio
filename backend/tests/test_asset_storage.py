from __future__ import annotations

import hashlib

import pytest

from adforge_renderer.asset_contract import PrivateObjectVersionReference
from adforge_renderer.asset_storage import (
    ExactVersionReadResult,
    ObjectVersionNotFound,
    ObjectVersionReadError,
    observe_exact_version,
)


class InMemoryExactVersionReader:
    """Deterministic test fake; it proves no real storage guarantees."""

    def __init__(self) -> None:
        self.versions: dict[str, bytes] = {}
        self.read_errors: set[str] = set()
        self.reads: list[str] = []

    def add(self, version: str, data: bytes) -> None:
        if version in self.versions:
            raise ValueError("object version already exists")
        self.versions[version] = data

    def read_exact_version(self, object_version: PrivateObjectVersionReference) -> bytes:
        version = object_version.value
        self.reads.append(version)
        if version in self.read_errors:
            raise ObjectVersionReadError("simulated private detail")
        try:
            return self.versions[version]
        except KeyError as exc:
            raise ObjectVersionNotFound("simulated missing version") from exc


def test_read_uses_explicit_version_a_key_after_version_b_is_added() -> None:
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", b"version A bytes")
    ref_a = PrivateObjectVersionReference(value="object-version-A")
    reader.add("object-version-B", b"version B bytes")

    result = observe_exact_version(reader, ref_a)

    assert result.succeeded
    assert result.observation is not None
    assert result.observation.object_version == ref_a
    assert result.observation.sha256 == hashlib.sha256(b"version A bytes").hexdigest()
    assert result.observation.sha256 != hashlib.sha256(b"version B bytes").hexdigest()
    assert reader.reads == ["object-version-A"]


def test_fake_rejects_duplicate_version_insertion_and_preserves_original_bytes() -> None:
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", b"original bytes")

    with pytest.raises(ValueError, match="object version already exists"):
        reader.add("object-version-A", b"replacement bytes")

    result = observe_exact_version(reader, PrivateObjectVersionReference(value="object-version-A"))
    assert result.succeeded
    assert result.observation is not None
    assert result.observation.sha256 == hashlib.sha256(b"original bytes").hexdigest()


def test_unknown_version_fails_without_latest_or_other_version_fallback() -> None:
    reader = InMemoryExactVersionReader()
    reader.add("object-version-current", b"current bytes")

    result = observe_exact_version(
        reader, PrivateObjectVersionReference(value="object-version-missing"),
    )

    assert_failed(result, "object_version_not_found")
    assert reader.reads == ["object-version-missing"]


def test_simulated_read_error_fails_closed_without_leaking_error_text() -> None:
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", b"version A bytes")
    reader.read_errors.add("object-version-A")

    result = observe_exact_version(reader, PrivateObjectVersionReference(value="object-version-A"))

    assert_failed(result, "object_version_read_failed")
    assert "simulated private detail" not in result.issues[0].message


def test_observation_hash_and_size_are_from_exact_returned_bytes() -> None:
    payload = b"exact returned bytes"
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", payload)

    result = observe_exact_version(reader, PrivateObjectVersionReference(value="object-version-A"))

    assert result.succeeded
    assert result.observation is not None
    assert result.observation.byte_size == len(payload)
    assert result.observation.sha256 == hashlib.sha256(payload).hexdigest()


def test_matching_expected_digest_and_size_are_accepted() -> None:
    payload = b"expected exact bytes"
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", payload)

    result = observe_exact_version(
        reader,
        PrivateObjectVersionReference(value="object-version-A"),
        expected_sha256=hashlib.sha256(payload).hexdigest(),
        expected_byte_size=len(payload),
    )

    assert result.succeeded
    assert result.observation is not None
    assert result.observation.byte_size == len(payload)
    assert result.observation.sha256 == hashlib.sha256(payload).hexdigest()


def test_expected_digest_mismatch_fails_closed() -> None:
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", b"actual bytes")

    result = observe_exact_version(
        reader,
        PrivateObjectVersionReference(value="object-version-A"),
        expected_sha256=hashlib.sha256(b"different bytes").hexdigest(),
    )

    assert_failed(result, "object_version_digest_mismatch")


def test_expected_size_mismatch_fails_closed() -> None:
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", b"actual bytes")

    result = observe_exact_version(
        reader,
        PrivateObjectVersionReference(value="object-version-A"),
        expected_byte_size=len(b"actual bytes") + 1,
    )

    assert_failed(result, "object_version_size_mismatch")


@pytest.mark.parametrize(
    "reference",
    [
        None,
        "object-version-A",
        PrivateObjectVersionReference.model_construct(value=""),
        PrivateObjectVersionReference.model_construct(value="   "),
        PrivateObjectVersionReference.model_construct(value="\t"),
        PrivateObjectVersionReference.model_construct(value="\n"),
        PrivateObjectVersionReference(value="latest"),
        PrivateObjectVersionReference(value="LATEST"),
    ],
)
def test_invalid_or_incomplete_version_references_are_rejected(reference: object) -> None:
    reader = InMemoryExactVersionReader()

    result = observe_exact_version(reader, reference)

    assert_failed(result, "invalid_object_version_reference")
    assert reader.reads == []


def test_nonblank_opaque_reference_is_preserved_without_normalization() -> None:
    reader = InMemoryExactVersionReader()
    value = " opaque-version-id "
    reader.add(value, b"exact bytes")
    reference = PrivateObjectVersionReference(value=value)

    result = observe_exact_version(reader, reference)

    assert result.succeeded
    assert result.observation is not None
    assert result.observation.object_version.value == value
    assert reader.reads == [value]


def test_malformed_copied_reference_is_revalidated_before_read() -> None:
    reference = PrivateObjectVersionReference(value="object-version-A").model_copy(
        update={"value": "bad\nreference"},
    )

    result = observe_exact_version(InMemoryExactVersionReader(), reference)

    assert_failed(result, "invalid_object_version_reference")


def test_reader_returning_mutable_or_invalid_data_fails_closed() -> None:
    class InvalidDataReader:
        def read_exact_version(self, _object_version: PrivateObjectVersionReference) -> bytearray:
            return bytearray(b"mutable")

    result = observe_exact_version(
        InvalidDataReader(), PrivateObjectVersionReference(value="object-version-A"),
    )

    assert_failed(result, "object_version_read_invalid")


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"expected_sha256": "not-a-digest"}, "invalid_expected_digest"),
        ({"expected_byte_size": True}, "invalid_expected_size"),
        ({"expected_byte_size": 0}, "invalid_expected_size"),
    ],
)
def test_invalid_expected_integrity_values_fail_before_read(kwargs: dict[str, object], code: str) -> None:
    reader = InMemoryExactVersionReader()
    reader.add("object-version-A", b"bytes")

    result = observe_exact_version(
        reader, PrivateObjectVersionReference(value="object-version-A"), **kwargs,
    )

    assert_failed(result, code)
    assert reader.reads == []


def assert_failed(result: ExactVersionReadResult, code: str) -> None:
    assert not result.succeeded
    assert result.observation is None
    assert [issue.code for issue in result.issues] == [code]
