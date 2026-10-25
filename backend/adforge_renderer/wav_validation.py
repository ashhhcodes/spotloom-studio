"""Pure bounded parser for Spotloom's deliberately narrow WAV v1 profile.

Returned values describe byte-level observations only. They do not establish
trusted storage, authorization, authenticity, or production readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

from pydantic import ValidationError

from .asset_contract import ObservedWavProperties
from .production_package import FPS


DEVELOPMENT_MAX_WAV_BYTES = 25 * 1024 * 1024
DEVELOPMENT_MAX_WAV_DURATION_SECONDS = 60
SAMPLES_PER_VIDEO_FRAME = 2_000
SAMPLE_RATE = 48_000
CHANNELS = 2
BITS_PER_SAMPLE = 16
BLOCK_ALIGN = CHANNELS * BITS_PER_SAMPLE // 8
BYTE_RATE = SAMPLE_RATE * BLOCK_ALIGN


@dataclass(frozen=True)
class WavValidationIssue:
    code: str
    message: str


@dataclass(frozen=True)
class ObservedWavMetadata:
    byte_size: int
    properties: ObservedWavProperties


@dataclass(frozen=True)
class WavValidationResult:
    metadata: ObservedWavMetadata | None
    issues: tuple[WavValidationIssue, ...] = ()

    @property
    def valid(self) -> bool:
        return self.metadata is not None and not self.issues


def _failure(code: str, message: str) -> WavValidationResult:
    return WavValidationResult(None, (WavValidationIssue(code, message),))


def validate_wav_bytes(
    data: object,
    *,
    max_input_bytes: int = DEVELOPMENT_MAX_WAV_BYTES,
    max_duration_seconds: int = DEVELOPMENT_MAX_WAV_DURATION_SECONDS,
) -> WavValidationResult:
    """Validate exact in-memory WAV bytes against the supported PCM profile.

    The byte and duration defaults are provisional development bounds, not
    production-approved limits. Callers may supply deployment-specific bounds.
    Ancillary chunk contents remain opaque and are never treated as evidence.
    """
    if type(max_input_bytes) is not int or max_input_bytes <= 0:
        return _failure("invalid_validation_limit", "The WAV validation limits are invalid.")
    if type(max_duration_seconds) is not int or max_duration_seconds <= 0:
        return _failure("invalid_validation_limit", "The WAV validation limits are invalid.")
    if type(data) is not bytes:
        return _failure("invalid_wav_input", "WAV input must be an immutable byte string.")
    if len(data) > max_input_bytes:
        return _failure("wav_input_too_large", "WAV input exceeds the configured byte limit.")
    if len(data) < 12:
        return _failure("wav_header_truncated", "The WAV container header is incomplete.")

    container = data[0:4]
    if container == b"RF64":
        return _failure("wav_container_unsupported", "The WAV container variant is unsupported.")
    if container != b"RIFF" or data[8:12] != b"WAVE":
        return _failure("wav_container_invalid", "The input is not a supported RIFF/WAVE container.")

    riff_size = struct.unpack_from("<I", data, 4)[0]
    riff_end = 8 + riff_size
    if riff_size < 4 or riff_end != len(data):
        return _failure("wav_riff_extent_invalid", "The declared RIFF extent does not match the input length.")

    offset = 12
    fmt_payload: tuple[int, int, int, int, int, int] | None = None
    data_size: int | None = None
    seen_fmt = False
    seen_data = False

    while offset < riff_end:
        if riff_end - offset < 8:
            return _failure("wav_chunk_header_truncated", "A WAV chunk header is incomplete.")
        chunk_id = data[offset:offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        payload_start = offset + 8
        payload_end = payload_start + chunk_size
        padded_end = payload_end + (chunk_size & 1)
        if payload_end > riff_end or padded_end > riff_end:
            return _failure("wav_chunk_bounds_invalid", "A WAV chunk exceeds the declared container boundary.")

        if chunk_id == b"LIST":
            return _failure("wav_list_chunk_unsupported", "LIST chunks are not supported by WAV profile v1.")
        if chunk_id == b"fmt ":
            if seen_fmt:
                return _failure("wav_fmt_duplicate", "The WAV contains duplicate format chunks.")
            if chunk_size >= 2 and struct.unpack_from("<H", data, payload_start)[0] == 0xFFFE:
                return _failure("wav_format_unsupported", "WAVE_FORMAT_EXTENSIBLE is not supported by WAV profile v1.")
            if chunk_size != 16:
                return _failure("wav_fmt_size_unsupported", "The WAV format chunk must use the 16-byte PCM v1 layout.")
            seen_fmt = True
            fmt_payload = struct.unpack_from("<HHIIHH", data, payload_start)
        elif chunk_id == b"data":
            if seen_data:
                return _failure("wav_data_duplicate", "The WAV contains duplicate audio data chunks.")
            if not seen_fmt:
                return _failure("wav_chunk_order_invalid", "The format chunk must precede the audio data chunk.")
            seen_data = True
            data_size = chunk_size

        offset = padded_end

    if not seen_fmt or not seen_data or fmt_payload is None or data_size is None:
        return _failure("wav_required_chunk_missing", "The WAV must contain one format chunk and one data chunk.")

    format_tag, channels, sample_rate, byte_rate, block_align, bits_per_sample = fmt_payload
    if format_tag != 1:
        return _failure("wav_format_unsupported", "Only integer PCM audio is supported.")
    if (
        channels != CHANNELS
        or sample_rate != SAMPLE_RATE
        or bits_per_sample != BITS_PER_SAMPLE
        or block_align != BLOCK_ALIGN
        or byte_rate != BYTE_RATE
    ):
        return _failure("wav_format_inconsistent", "The WAV format fields do not match the supported PCM profile.")
    if data_size == 0 or data_size % BLOCK_ALIGN:
        return _failure("wav_audio_data_invalid", "The WAV audio data must contain complete PCM sample frames.")

    sample_count = data_size // BLOCK_ALIGN
    if sample_count % SAMPLES_PER_VIDEO_FRAME:
        return _failure("wav_sample_alignment_invalid", "Audio sample frames must align exactly to video frames.")
    duration_frames = sample_count // SAMPLES_PER_VIDEO_FRAME
    if duration_frames > max_duration_seconds * FPS:
        return _failure("wav_duration_too_long", "WAV duration exceeds the configured duration limit.")

    try:
        properties = ObservedWavProperties(
            container="wav",
            codec="pcm_s16le",
            sample_format="s16le",
            sample_rate=SAMPLE_RATE,
            channels=CHANNELS,
            sample_count=sample_count,
            duration_frames=duration_frames,
        )
    except ValidationError:
        return _failure("wav_metadata_out_of_bounds", "Observed WAV metadata exceeds the supported bounds.")
    return WavValidationResult(ObservedWavMetadata(len(data), properties))
