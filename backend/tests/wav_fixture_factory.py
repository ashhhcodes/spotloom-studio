"""Deterministic in-memory WAV byte fixtures for policy review and parser tests.

These builders describe byte patterns only. The presence of a fixture does not
mean that its chunk layout is accepted by the product contract.
"""

from __future__ import annotations

import struct


SAMPLE_RATE = 48_000
CHANNELS = 2
BITS_PER_SAMPLE = 16
BLOCK_ALIGN = CHANNELS * BITS_PER_SAMPLE // 8
SAMPLES_PER_VIDEO_FRAME = 2_000


def riff_chunk(chunk_id: bytes, payload: bytes, *, include_padding: bool = True) -> bytes:
    """Build one RIFF chunk, optionally omitting its odd-length pad byte."""
    if len(chunk_id) != 4:
        raise ValueError("RIFF chunk IDs must be four bytes")
    padding = b"\x00" if len(payload) % 2 and include_padding else b""
    return chunk_id + struct.pack("<I", len(payload)) + payload + padding


def pcm_format_chunk(
    *, format_tag: int = 1, channels: int = CHANNELS, sample_rate: int = SAMPLE_RATE,
    byte_rate: int | None = None, block_align: int | None = None,
    bits_per_sample: int = BITS_PER_SAMPLE,
) -> bytes:
    """Build a 16-byte WAVEFORMAT payload, including deliberate invalid variants."""
    expected_align = channels * bits_per_sample // 8
    align = expected_align if block_align is None else block_align
    rate = sample_rate * align if byte_rate is None else byte_rate
    return struct.pack(
        "<HHIIHH", format_tag, channels, sample_rate, rate, align, bits_per_sample,
    )


def wav_bytes(
    chunks: tuple[bytes, ...], *, riff_id: bytes = b"RIFF", form_type: bytes = b"WAVE",
    declared_riff_size: int | None = None, trailing: bytes = b"",
) -> bytes:
    """Wrap already encoded chunks in a RIFF/WAVE header."""
    body = form_type + b"".join(chunks)
    size = len(body) if declared_riff_size is None else declared_riff_size
    return riff_id + struct.pack("<I", size) + body + trailing


def canonical_pcm_wav(duration_frames: int = 1) -> bytes:
    """Produce deterministic fmt-then-data PCM bytes for an integral video duration."""
    if type(duration_frames) is not int or duration_frames < 1:
        raise ValueError("duration_frames must be a positive integer")
    sample_frames = duration_frames * SAMPLES_PER_VIDEO_FRAME
    data = b"\x00" * (sample_frames * BLOCK_ALIGN)
    return wav_bytes((riff_chunk(b"fmt ", pcm_format_chunk()), riff_chunk(b"data", data)))


def wav_fixture_cases() -> dict[str, bytes]:
    """Return deterministic small cases classified by the proposed v1 policy."""
    fmt = riff_chunk(b"fmt ", pcm_format_chunk())
    data = riff_chunk(b"data", b"\x00" * (SAMPLES_PER_VIDEO_FRAME * BLOCK_ALIGN))
    info = riff_chunk(b"LIST", b"INFO" + riff_chunk(b"INAM", b"demo\x00"))
    cases = {
        "accepted_canonical_fmt_then_data": wav_bytes((fmt, data)),
        "accepted_ancillary_before_between_after": wav_bytes((
            riff_chunk(b"JUNK", b"pre!"), fmt,
            riff_chunk(b"zzzz", b"x"), data, riff_chunk(b"bext", b"post"),
        )),
        "accepted_odd_ancillary_arbitrary_pad": wav_bytes((
            fmt, riff_chunk(b"JUNK", b"x")[:-1] + b"\xa5", data,
        )),
        "rejected_list_info": wav_bytes((fmt, info, data)),
        "accepted_unknown_ancillary_length_bounded": wav_bytes((
            fmt, riff_chunk(b"zzzz", b"x"), data,
        )),
        "rejected_data_before_fmt": wav_bytes((data, fmt)),
        "rejected_duplicate_fmt": wav_bytes((fmt, fmt, data)),
        "rejected_duplicate_data": wav_bytes((fmt, data, data)),
        "rejected_missing_fmt": wav_bytes((riff_chunk(b"JUNK", b"only ancillary"),)),
        "rejected_missing_data": wav_bytes((fmt,)),
        "rejected_odd_ancillary_missing_pad": wav_bytes((
            fmt, riff_chunk(b"JUNK", b"x", include_padding=False),
        )),
        "malformed_declared_riff_short": wav_bytes((fmt, data), declared_riff_size=4),
        "malformed_declared_riff_long": wav_bytes((fmt, data), declared_riff_size=len(b"WAVE" + fmt + data) + 1),
        "malformed_trailing_bytes": wav_bytes((fmt, data), trailing=b"extra"),
        "malformed_truncated_riff_header": b"RIFF\x04\x00",
        "malformed_truncated_chunk_header": wav_bytes((b"fmt",)),
        "malformed_chunk_overrun": wav_bytes((b"data\xff\xff\xff\xfftiny",)),
        "unsupported_format_tag": wav_bytes((riff_chunk(b"fmt ", pcm_format_chunk(format_tag=3)), data)),
        "unsupported_format_extensible": wav_bytes((riff_chunk(
            b"fmt ", struct.pack("<HHIIHHH", 0xFFFE, CHANNELS, SAMPLE_RATE,
                                 SAMPLE_RATE * BLOCK_ALIGN, BLOCK_ALIGN, BITS_PER_SAMPLE, 22)
            + b"\x00" * 22,
        ), data)),
        "unsupported_channel_count": wav_bytes((riff_chunk(b"fmt ", pcm_format_chunk(channels=1)), data)),
        "unsupported_sample_rate": wav_bytes((riff_chunk(b"fmt ", pcm_format_chunk(sample_rate=44_100)), data)),
        "inconsistent_byte_rate": wav_bytes((riff_chunk(b"fmt ", pcm_format_chunk(byte_rate=1)), data)),
        "inconsistent_block_align": wav_bytes((riff_chunk(b"fmt ", pcm_format_chunk(block_align=2)), data)),
        "unsupported_bit_depth": wav_bytes((riff_chunk(b"fmt ", pcm_format_chunk(bits_per_sample=24)), data)),
        "unsupported_rf64": wav_bytes((fmt, data), riff_id=b"RF64"),
        "unsupported_rifx": wav_bytes((fmt, data), riff_id=b"RIFX"),
        "non_aligned_sample_frames": wav_bytes((fmt, riff_chunk(b"data", b"\x00" * 8_004))),
    }
    return cases
