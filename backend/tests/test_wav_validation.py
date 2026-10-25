from __future__ import annotations

import struct

import pytest

from adforge_renderer.wav_validation import (
    DEVELOPMENT_MAX_WAV_BYTES,
    DEVELOPMENT_MAX_WAV_DURATION_SECONDS,
    validate_wav_bytes,
)
from wav_fixture_factory import (
    BLOCK_ALIGN,
    SAMPLES_PER_VIDEO_FRAME,
    canonical_pcm_wav,
    riff_chunk,
    wav_bytes,
    wav_fixture_cases,
)


def test_canonical_wav_returns_observed_metadata_only() -> None:
    payload = canonical_pcm_wav()

    result = validate_wav_bytes(payload)

    assert result.valid
    assert result.issues == ()
    assert result.metadata is not None
    assert result.metadata.byte_size == len(payload)
    assert result.metadata.properties.model_dump() == {
        "container": "wav",
        "codec": "pcm_s16le",
        "sample_format": "s16le",
        "sample_rate": 48_000,
        "channels": 2,
        "sample_count": SAMPLES_PER_VIDEO_FRAME,
        "duration_frames": 1,
    }


@pytest.mark.parametrize(
    ("name", "issue_code"),
    [
        ("rejected_list_info", "wav_list_chunk_unsupported"),
        ("rejected_data_before_fmt", "wav_chunk_order_invalid"),
        ("rejected_duplicate_fmt", "wav_fmt_duplicate"),
        ("rejected_duplicate_data", "wav_data_duplicate"),
        ("rejected_missing_fmt", "wav_required_chunk_missing"),
        ("rejected_missing_data", "wav_required_chunk_missing"),
        ("rejected_odd_ancillary_missing_pad", "wav_chunk_bounds_invalid"),
        ("malformed_declared_riff_short", "wav_riff_extent_invalid"),
        ("malformed_declared_riff_long", "wav_riff_extent_invalid"),
        ("malformed_trailing_bytes", "wav_riff_extent_invalid"),
        ("malformed_truncated_riff_header", "wav_header_truncated"),
        ("malformed_truncated_chunk_header", "wav_chunk_header_truncated"),
        ("malformed_chunk_overrun", "wav_chunk_bounds_invalid"),
        ("unsupported_format_tag", "wav_format_unsupported"),
        ("unsupported_format_extensible", "wav_format_unsupported"),
        ("unsupported_channel_count", "wav_format_inconsistent"),
        ("unsupported_sample_rate", "wav_format_inconsistent"),
        ("inconsistent_byte_rate", "wav_format_inconsistent"),
        ("inconsistent_block_align", "wav_format_inconsistent"),
        ("unsupported_bit_depth", "wav_format_inconsistent"),
        ("unsupported_rf64", "wav_container_unsupported"),
        ("unsupported_rifx", "wav_container_invalid"),
        ("non_aligned_sample_frames", "wav_sample_alignment_invalid"),
    ],
)
def test_rejected_fixture_cases_have_controlled_findings(name: str, issue_code: str) -> None:
    result = validate_wav_bytes(wav_fixture_cases()[name])

    assert result.metadata is None
    assert [issue.code for issue in result.issues] == [issue_code]
    assert result.issues[0].message


@pytest.mark.parametrize(
    "name",
    [
        "accepted_canonical_fmt_then_data",
        "accepted_ancillary_before_between_after",
        "accepted_odd_ancillary_arbitrary_pad",
        "accepted_unknown_ancillary_length_bounded",
    ],
)
def test_policy_accepted_chunk_layouts(name: str) -> None:
    result = validate_wav_bytes(wav_fixture_cases()[name])

    assert result.valid
    assert result.metadata is not None
    assert result.metadata.properties.duration_frames == 1


def test_configured_byte_boundary_uses_actual_input_length() -> None:
    payload = canonical_pcm_wav()

    assert validate_wav_bytes(payload, max_input_bytes=len(payload)).valid
    rejected = validate_wav_bytes(payload, max_input_bytes=len(payload) - 1)
    assert rejected.metadata is None
    assert rejected.issues[0].code == "wav_input_too_large"


def test_provisional_default_bounds_are_explicit_and_configurable() -> None:
    assert DEVELOPMENT_MAX_WAV_BYTES == 25 * 1024 * 1024
    assert DEVELOPMENT_MAX_WAV_DURATION_SECONDS == 60
    # One second is exactly 24 video frames at 24 fps.
    assert validate_wav_bytes(canonical_pcm_wav(24), max_duration_seconds=1).valid
    too_long = validate_wav_bytes(canonical_pcm_wav(25), max_duration_seconds=1)
    assert too_long.metadata is None
    assert too_long.issues[0].code == "wav_duration_too_long"


def test_input_and_limits_reject_unexpected_types_without_exceptions() -> None:
    assert validate_wav_bytes(bytearray(canonical_pcm_wav())).issues[0].code == "invalid_wav_input"


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"max_input_bytes": True}, "invalid_validation_limit"),
        ({"max_input_bytes": None}, "invalid_validation_limit"),
        ({"max_input_bytes": 0}, "invalid_validation_limit"),
        ({"max_input_bytes": -1}, "invalid_validation_limit"),
        ({"max_input_bytes": 1.5}, "invalid_validation_limit"),
        ({"max_duration_seconds": False}, "invalid_validation_limit"),
        ({"max_duration_seconds": 0}, "invalid_validation_limit"),
        ({"max_duration_seconds": -1}, "invalid_validation_limit"),
        ({"max_duration_seconds": 1.5}, "invalid_validation_limit"),
        ({"max_duration_seconds": None}, "invalid_validation_limit"),
    ],
)
def test_invalid_configured_limits_fail_closed(options: dict[str, object], code: str) -> None:
    result = validate_wav_bytes(canonical_pcm_wav(), **options)
    assert result.metadata is None
    assert result.issues[0].code == code


def test_empty_audio_and_partial_pcm_sample_frame_are_rejected() -> None:
    fmt = riff_chunk(b"fmt ", struct.pack("<HHIIHH", 1, 2, 48_000, 192_000, 4, 16))
    empty = validate_wav_bytes(wav_bytes((fmt, riff_chunk(b"data", b""))))
    assert empty.metadata is None
    assert empty.issues[0].code == "wav_audio_data_invalid"

    partial = validate_wav_bytes(wav_bytes((fmt, riff_chunk(b"data", b"\x00" * (BLOCK_ALIGN + 1)))))
    assert partial.metadata is None
    assert partial.issues[0].code == "wav_audio_data_invalid"
