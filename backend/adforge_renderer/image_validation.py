"""Pure bounded validation of in-memory PNG and JPEG image bytes.

Successful results are byte-decoding observations only. They are not trusted
asset evidence, storage verification, authorization, or readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import warnings

from PIL import Image, ImageFile, UnidentifiedImageError


IMAGE_PROFILE_ID = "spotloom.product-image.png-jpeg.v1"

# Conservative local development defaults, not approved production upload limits.
DEVELOPMENT_MAX_IMAGE_BYTES = 10 * 1024 * 1024
DEVELOPMENT_MAX_IMAGE_WIDTH = 4_096
DEVELOPMENT_MAX_IMAGE_HEIGHT = 4_096
DEVELOPMENT_MAX_IMAGE_PIXELS = 12_000_000

# Hard ceilings prevent a caller from accidentally disabling meaningful bounds.
MAX_CONFIGURABLE_IMAGE_BYTES = 25 * 1024 * 1024
MAX_CONFIGURABLE_IMAGE_DIMENSION = 8_192
MAX_CONFIGURABLE_IMAGE_PIXELS = 40_000_000

_SUPPORTED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg"}


@dataclass(frozen=True)
class ImageValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ObservedImageMetadata:
    """Properties decoded from the exact in-memory byte string supplied.

    This record deliberately has no trusted/readiness status and does not bind
    itself to a project, immutable version, or storage object.
    """

    profile_id: str
    format: str
    media_type: str
    width: int
    height: int
    pixel_count: int
    mode: str
    byte_size: int
    sha256: str


@dataclass(frozen=True)
class ImageValidationResult:
    observation: ObservedImageMetadata | None
    issues: tuple[ImageValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.observation is not None and not self.issues


def _failure(code: str, message: str) -> ImageValidationResult:
    return ImageValidationResult(None, (ImageValidationIssue(code, message),))


def _limits_are_valid(*limits: int) -> bool:
    ceilings = (
        MAX_CONFIGURABLE_IMAGE_BYTES,
        MAX_CONFIGURABLE_IMAGE_DIMENSION,
        MAX_CONFIGURABLE_IMAGE_DIMENSION,
        MAX_CONFIGURABLE_IMAGE_PIXELS,
    )
    return all(
        type(value) is int and 0 < value <= ceiling
        for value, ceiling in zip(limits, ceilings, strict=True)
    )


def validate_image_bytes(
    data: object,
    *,
    declared_media_type: object | None = None,
    max_input_bytes: int = DEVELOPMENT_MAX_IMAGE_BYTES,
    max_width: int = DEVELOPMENT_MAX_IMAGE_WIDTH,
    max_height: int = DEVELOPMENT_MAX_IMAGE_HEIGHT,
    max_pixels: int = DEVELOPMENT_MAX_IMAGE_PIXELS,
) -> ImageValidationResult:
    """Decode and observe a bounded PNG/JPEG byte string.

    The development defaults are provisional local bounds, not production
    upload policy. Explicit limits may be configured up to module hard caps.
    MIME metadata is optional and is only compared with the decoder result; it
    never determines the accepted format or validates an asset.
    """
    if not _limits_are_valid(max_input_bytes, max_width, max_height, max_pixels):
        return _failure("invalid_validation_limit", "The image validation limits are invalid.")
    if type(data) is not bytes:
        return _failure("invalid_image_input", "Image input must be an immutable byte string.")
    if len(data) > max_input_bytes:
        return _failure("image_input_too_large", "Image input exceeds the configured byte limit.")
    if not data:
        return _failure("image_data_invalid", "The image data is invalid or incomplete.")
    if declared_media_type is not None and type(declared_media_type) is not str:
        return _failure("invalid_declared_image_format", "The declared image format is invalid.")
    if declared_media_type is not None and declared_media_type not in _SUPPORTED_FORMATS.values():
        return _failure("unsupported_declared_image_format", "The declared image format is unsupported.")

    # Truncated-image decoding is a process-global Pillow switch. Fail closed
    # rather than changing that switch or allowing another caller to weaken it.
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        return _failure("image_decoder_configuration_unsafe", "The image decoder is not configured for strict reads.")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as inspected:
                detected_format = inspected.format
                if detected_format not in _SUPPORTED_FORMATS:
                    return _failure("unsupported_image_format", "Only PNG and JPEG images are supported.")
                if declared_media_type is not None and _SUPPORTED_FORMATS[detected_format] != declared_media_type:
                    return _failure("declared_image_format_mismatch", "The declared format does not match the decoded image.")

                width, height = inspected.size
                if width <= 0 or height <= 0 or width > max_width or height > max_height:
                    return _failure("image_dimensions_exceeded", "Image dimensions exceed the configured limits.")
                pixel_count = width * height
                if pixel_count > max_pixels:
                    return _failure("image_pixel_count_exceeded", "Image pixel count exceeds the configured limit.")
                if getattr(inspected, "n_frames", 1) != 1 or getattr(inspected, "is_animated", False):
                    return _failure("unsupported_animated_image", "Animated images are not supported.")

                inspected.verify()

            # verify() checks container integrity but leaves pixel decoding to
            # load(); reopen the same immutable input and force a complete decode.
            with Image.open(BytesIO(data)) as decoded:
                if decoded.format != detected_format or decoded.size != (width, height):
                    return _failure("image_decode_inconsistent", "The image decoder returned inconsistent metadata.")
                decoded.load()
                mode = decoded.mode
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        return _failure("image_pixel_count_exceeded", "Image exceeds the safe decoder pixel limit.")
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError):
        return _failure("image_data_invalid", "The image data is invalid or incomplete.")

    return ImageValidationResult(ObservedImageMetadata(
        profile_id=IMAGE_PROFILE_ID,
        format=detected_format,
        media_type=_SUPPORTED_FORMATS[detected_format],
        width=width,
        height=height,
        pixel_count=pixel_count,
        mode=mode,
        byte_size=len(data),
        sha256=sha256(data).hexdigest(),
    ))
