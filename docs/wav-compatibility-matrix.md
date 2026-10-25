# WAV v1 Compatibility Matrix

**Status: proposed v1 parser contract for review.** The matrix records the WAV
byte behavior implemented by the pure validator. Fixture names are deterministic
byte patterns; they are not real user audio or trusted evidence.

## Established profile and bounds

| Item | Repository evidence | v1 behavior |
| --- | --- | --- |
| Audio profile | `backend/adforge_renderer/asset_contract.py`: `ASSET_FORMAT` and `ObservedWavProperties` require WAV, PCM signed 16-bit little-endian, 48 kHz, stereo. | Accept only this profile and internally consistent PCM fields. |
| Frame alignment | `ObservedWavProperties` requires sample-frame count divisible by 2,000; `docs/asset-trust-policy-decisions.md` ties this to 24 fps and prohibits rounding. | Accept only an exact multiple of 2,000 sample frames. Duration is the quotient; never rounded. |
| Byte bound | Policy record identifies 25 MiB as provisional, not production-approved. | Configurable default `25 * 1024 * 1024` bytes. Enforced against actual immutable input length before parsing. Not workload-validated or production-approved. |
| Duration bound | Policy record identifies 60 seconds as provisional, not production-approved. | Configurable default 60 seconds, converted to video frames at 24 fps and checked against observed samples. Not workload-validated or production-approved. |
| Structural bound | Asset metadata uses `MAX_DECLARED_DURATION_FRAMES = 86_400`. | Observed metadata is also bounded by its existing model; this is not an upload or workload limit. |
| Existing media fixtures | No pre-existing WAV byte fixtures existed. Package JSON fixtures declare audio metadata only. | `backend/tests/wav_fixture_factory.py` supplies deterministic in-memory cases. No prior byte-layout assumption is broken. |

## Accepted chunk behavior

| Case | v1 behavior | Fixture/test coverage |
| --- | --- | --- |
| Container | RIFF with `WAVE` form only. Declared RIFF extent must equal the full input; no trailing bytes. | canonical and malformed extent/trailing fixtures |
| Required chunks | Exactly one 16-byte PCM `fmt ` and exactly one `data`; `fmt ` must precede `data`. Duplicates reject. | missing, duplicate, and ordering fixtures |
| Ancillary chunks | Structurally valid chunks may appear before, between, or after required chunks. Unknown IDs are opaque; payloads are not interpreted. | ancillary before/between/after and unknown-ID fixtures |
| Chunk boundaries | Every header, payload, and odd-size pad byte must fit within actual RIFF input. Odd payloads require one pad byte; its value is unrestricted. | truncated, overrun, missing-pad, and arbitrary-pad fixtures |

## Deliberate compatibility restrictions

| Case | v1 behavior | Compatibility trade-off |
| --- | --- | --- |
| `LIST` including `LIST/INFO` | Reject every `LIST` chunk, including valid nested metadata. | Some WAV metadata-bearing files will not be accepted; nested structures stay out of the v1 parser. |
| RF64 and RIFX | Reject. | Large-file and big-endian variants are unsupported. |
| WAVE_FORMAT_EXTENSIBLE | Reject. | Only classic 16-byte PCM `WAVEFORMAT` is accepted; extensible PCM is not inferred as equivalent. |
| Other `fmt ` sizes | Reject; v1 requires exactly 16 bytes. | This narrow format-layout rule avoids interpreting extension bytes not defined by this profile. |
| Other encoding/profile values | Reject unsupported encoding, sample rate, channels, bit depth, byte rate, or block alignment. | No implicit conversion or resampling. |
| Empty or non-frame-aligned data | Reject. | No empty audio and no partial interleaved PCM sample frame. |

The 16-byte `fmt ` requirement is the validator's explicit narrow v1 parser
choice. The accepted profile itself remains the repository's documented PCM
profile; the parser does not infer trust or compatibility beyond these rules.

## Fixture inventory

`backend/tests/wav_fixture_factory.py` generates repeatable bytes using only the
Python standard library. Its cases include canonical input, ancillary ordering,
unknown ancillary IDs, arbitrary odd padding, rejected `LIST`, duplicate/missing
required chunks, malformed RIFF/chunk extents, unsupported PCM variants, RF64,
and sample misalignment. Generated data is in-memory; no media artifacts are
checked in.

## Trust and scope boundary

`backend/adforge_renderer/wav_validation.py` returns observed byte size and WAV
properties only. Ancillary payloads are opaque and never treated as evidence.
The validator performs no storage lookup, digest computation, authorization,
authentication, identity check, evidence issuance, persistence, or readiness
transition. These observations do not prove who supplied bytes, where they were
stored, or whether a trusted service validated them. `/scan` remains unavailable.
