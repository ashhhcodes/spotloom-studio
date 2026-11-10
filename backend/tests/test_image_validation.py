from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import struct
import zlib

import pytest
from PIL import Image

from adforge_renderer.image_validation import (
    DEVELOPMENT_MAX_IMAGE_BYTES,
    DEVELOPMENT_MAX_IMAGE_HEIGHT,
    DEVELOPMENT_MAX_IMAGE_PIXELS,
    DEVELOPMENT_MAX_IMAGE_WIDTH,
    IMAGE_PROFILE_ID,
    ObservedImageMetadata,
    ImageValidationResult,
    validate_image_bytes,
)


def encoded_image(format_name: str, *, size: tuple[int, int] = (32, 24)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (24, 96, 160)).save(output, format=format_name)
    return output.getvalue()


def png_with_declared_dimensions(width: int, height: int) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        checksum = zlib.crc32(kind + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(b"")) + chunk(b"IEND", b"")


@pytest.mark.parametrize(
    ("format_name", "media_type", "expected_format"),
    [("PNG", "image/png", "PNG"), ("JPEG", "image/jpeg", "JPEG")],
)
def test_supported_image_bytes_decode_and_return_exact_observations(format_name, media_type, expected_format):
    data = encoded_image(format_name)

    result = validate_image_bytes(data, declared_media_type=media_type)

    assert result.valid
    assert result.issues == ()
    assert result.observation is not None
    assert result.observation.profile_id == IMAGE_PROFILE_ID
    assert result.observation.format == expected_format
    assert result.observation.media_type == media_type
    assert (result.observation.width, result.observation.height) == (32, 24)
    assert result.observation.pixel_count == 32 * 24
    assert result.observation.byte_size == len(data)
    assert result.observation.sha256 == sha256(data).hexdigest()
    assert result.observation.mode == "RGB"


@pytest.mark.parametrize(
    ("data_format", "declared_media_type"),
    [("PNG", "image/jpeg"), ("JPEG", "image/png")],
)
def test_declared_format_must_match_decoded_content(data_format, declared_media_type):
    result = validate_image_bytes(encoded_image(data_format), declared_media_type=declared_media_type)

    assert not result.valid
    assert result.observation is None
    assert result.issues[0].code == "declared_image_format_mismatch"


@pytest.mark.parametrize("data", [b"not an image", encoded_image("PNG")[:-12], encoded_image("JPEG")[:-12]])
def test_corrupt_or_truncated_image_data_is_rejected(data):
    result = validate_image_bytes(data)

    assert not result.valid
    assert result.observation is None
    assert result.issues[0].code == "image_data_invalid"


def test_actual_byte_size_is_checked_before_decode():
    data = encoded_image("PNG")

    result = validate_image_bytes(data, max_input_bytes=len(data) - 1)

    assert not result.valid
    assert result.observation is None
    assert result.issues[0].code == "image_input_too_large"


def test_dimensions_and_pixel_count_are_bounded_before_pixel_decode():
    data = encoded_image("PNG", size=(40, 30))

    dimension_result = validate_image_bytes(data, max_width=39)
    pixel_result = validate_image_bytes(data, max_pixels=1_199)

    assert dimension_result.observation is None
    assert dimension_result.issues[0].code == "image_dimensions_exceeded"
    assert pixel_result.observation is None
    assert pixel_result.issues[0].code == "image_pixel_count_exceeded"


def test_decompression_bomb_dimensions_fail_before_pixel_allocation():
    result = validate_image_bytes(png_with_declared_dimensions(10_000, 10_000))

    assert not result.valid
    assert result.observation is None
    assert result.issues[0].code == "image_pixel_count_exceeded"


def test_unsupported_raster_format_is_rejected():
    result = validate_image_bytes(encoded_image("GIF"))

    assert not result.valid
    assert result.observation is None
    assert result.issues[0].code == "unsupported_image_format"


def test_configured_development_defaults_are_explicit():
    assert DEVELOPMENT_MAX_IMAGE_BYTES == 10 * 1024 * 1024
    assert DEVELOPMENT_MAX_IMAGE_WIDTH == 4_096
    assert DEVELOPMENT_MAX_IMAGE_HEIGHT == 4_096
    assert DEVELOPMENT_MAX_IMAGE_PIXELS == 12_000_000
    assert validate_image_bytes(encoded_image("PNG")).valid


@pytest.mark.parametrize(
    "limits",
    [
        {"max_input_bytes": None},
        {"max_input_bytes": 0},
        {"max_input_bytes": 25 * 1024 * 1024 + 1},
        {"max_width": True},
        {"max_height": -1},
        {"max_pixels": None},
        {"max_pixels": 40_000_001},
    ],
)
def test_invalid_or_unbounded_config_fails_closed(limits):
    result = validate_image_bytes(encoded_image("PNG"), **limits)

    assert not result.valid
    assert result.observation is None
    assert result.issues[0].code == "invalid_validation_limit"


def test_client_metadata_or_constructed_observation_cannot_validate_image_bytes():
    forged = ImageValidationResult(ObservedImageMetadata(
        profile_id=IMAGE_PROFILE_ID,
        format="PNG",
        media_type="image/png",
        width=32,
        height=24,
        pixel_count=768,
        mode="RGB",
        byte_size=1,
        sha256="a" * 64,
    ))

    result = validate_image_bytes(forged, declared_media_type="image/png")

    assert not result.valid
    assert result.observation is None
    assert result.issues[0].code == "invalid_image_input"
    assert not hasattr(forged.observation, "trusted")
    assert not hasattr(forged.observation, "asset_version_id")
