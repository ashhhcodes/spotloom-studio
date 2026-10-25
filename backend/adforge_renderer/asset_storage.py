"""Provider-neutral contract for exact immutable object-version reads.

This module defines an interface and computes observations over bytes returned
by that interface. It does not provide storage, prove privacy or immutability,
authenticate a reader, or establish trusted asset readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Protocol

from pydantic import ValidationError

from .asset_contract import PrivateObjectVersionReference


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ObjectVersionNotFound(Exception):
    """A reader could not find the explicitly requested object version."""


class ObjectVersionReadError(Exception):
    """A reader failed to return bytes for the explicitly requested version."""


class ExactVersionObjectReader(Protocol):
    """Reader contract; implementations must never substitute a mutable alias.

    ``read_exact_version`` must retrieve the exact immutable version identified
    by the supplied opaque reference. Implementations must raise
    ``ObjectVersionNotFound`` or ``ObjectVersionReadError`` for expected read
    failures and must not fall back to a latest/current object.
    """

    def read_exact_version(
        self, object_version: PrivateObjectVersionReference, /
    ) -> bytes:
        """Return the bytes for this exact version, or raise a typed read error."""


@dataclass(frozen=True)
class ExactVersionObservation:
    """Local size and digest measured from bytes returned by one exact read.

    This value alone proves neither storage identity nor provider behavior,
    byte authenticity, authorization, or readiness.
    """

    object_version: PrivateObjectVersionReference
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class ExactVersionReadIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ExactVersionReadResult:
    observation: ExactVersionObservation | None
    issues: tuple[ExactVersionReadIssue, ...] = ()

    @property
    def succeeded(self) -> bool:
        return self.observation is not None and not self.issues


def _failure(code: str, message: str) -> ExactVersionReadResult:
    return ExactVersionReadResult(None, (ExactVersionReadIssue(code, message),))


def _validate_reference(value: object) -> PrivateObjectVersionReference | None:
    if type(value) is not PrivateObjectVersionReference:
        return None
    try:
        validated = PrivateObjectVersionReference.model_validate(
            value.model_dump(mode="python", warnings=False),
        )
    except (ValidationError, TypeError, ValueError, AttributeError):
        return None
    if validated.value.casefold() == "latest":
        return None
    return validated


def observe_exact_version(
    reader: ExactVersionObjectReader,
    object_version: object,
    *,
    expected_sha256: object | None = None,
    expected_byte_size: object | None = None,
) -> ExactVersionReadResult:
    """Read one explicit immutable version and observe the exact returned bytes.

    Expected integrity values are optional, but any supplied value is validated
    and compared. Adapter-specific expected failures must be translated to the
    typed exceptions in this module; unexpected implementation errors remain
    visible to developers rather than being silently swallowed.
    """
    reference = _validate_reference(object_version)
    if reference is None:
        return _failure(
            "invalid_object_version_reference",
            "An explicit object-version reference is required.",
        )
    if not callable(getattr(reader, "read_exact_version", None)):
        return _failure("invalid_object_version_reader", "The object-version reader is invalid.")
    if expected_sha256 is not None and (
        type(expected_sha256) is not str or not _SHA256.fullmatch(expected_sha256)
    ):
        return _failure("invalid_expected_digest", "The expected digest is invalid.")
    if expected_byte_size is not None and (
        type(expected_byte_size) is not int or expected_byte_size <= 0
    ):
        return _failure("invalid_expected_size", "The expected byte size is invalid.")

    try:
        data = reader.read_exact_version(reference)
    except ObjectVersionNotFound:
        return _failure("object_version_not_found", "The requested object version was not found.")
    except (ObjectVersionReadError, OSError):
        return _failure("object_version_read_failed", "The requested object version could not be read.")

    if type(data) is not bytes:
        return _failure("object_version_read_invalid", "The object-version reader returned invalid data.")

    byte_size = len(data)
    sha256 = hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and sha256 != expected_sha256:
        return _failure("object_version_digest_mismatch", "The object-version digest did not match.")
    if expected_byte_size is not None and byte_size != expected_byte_size:
        return _failure("object_version_size_mismatch", "The object-version size did not match.")

    return ExactVersionReadResult(ExactVersionObservation(reference, byte_size, sha256))
