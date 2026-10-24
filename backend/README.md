# AdForge AI renderer proof (Milestone 1)

This local Windows milestone accepts manually supplied, user-approved business details and renders a deterministic 7.5-second vertical MP4. It uses Pillow to draw the brand scenes and real text overlays, and FFmpeg/FFprobe to encode and verify the video. It does not call an LLM or paid API.

## Prerequisites

- 64-bit Python 3.11 (the project pins its supported minor version).
- FFmpeg and FFprobe available on `PATH`.

Verify the tools from a new PowerShell window:

```powershell
py -3.11 --version
ffmpeg -version
ffprobe -version
```

Install an FFmpeg distribution for Windows that includes both `ffmpeg.exe` and `ffprobe.exe`, add its `bin` directory to `PATH`, and reopen PowerShell if either command is not found. This project does not install system software automatically.

## Set up and render

Run from the project root (`D:\AdForge_AI`):

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".\backend[test]"
python -m adforge_renderer.cli --input .\backend\sample_business.json --output .\artifacts\northstar-coffee.mp4
```

If PowerShell blocks virtual-environment activation, invoke the environment interpreter directly instead:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".\backend[test]"
.\.venv\Scripts\python.exe -m adforge_renderer.cli --input .\backend\sample_business.json --output .\artifacts\northstar-coffee.mp4
```

The renderer writes an MP4 only when FFprobe confirms MP4 container metadata, H.264 video, 1080×1920 dimensions, and a duration from 6.5 to 8.5 seconds. Failed or partial outputs are removed. Generated videos under `artifacts/` are ignored by Git.

## Milestone 2: facts to deterministic creative to MP4

The new fact sheet records each supplied value independently with a stable `fact_id`, field, provenance, and `review_state` (`unreviewed`, `approved`, or `rejected`). Only approved facts can support generated factual copy. Corrections reject the old record and add a linked, unreviewed revision; a missing field is absent, never treated as an approved negative or positive claim. Website provenance is supported as data, but no website is fetched in this milestone.

Fact IDs are unique lowercase identifiers. Fact text is whitespace-trimmed and limited to 240 characters; renderer-bound business name, product/service, CTA, selling points, and brand colors retain the renderer's field-specific limits. Brand colors normalize to uppercase `#RRGGBB`; at most three selling points and two colors are accepted. Offer, price, address, contact, and website facts are optional and are not used by this generator.

The creative is a typed sequence: hook, value proposition, zero to three distinct supporting points, then CTA. It copies factual text literally and carries supporting fact IDs; optional scene descriptions also need to match a cited approved fact exactly. This makes deterministic checks possible but does not prove semantic truth; reviewers remain responsible for whether supplied facts are accurate. If business name, product/service, or CTA is absent or not approved, generation returns `needs_review` with no creative and no video. When brand colors are absent, the renderer's neutral default colors are used as styling only and a warning is included.

Run the sample fact → creative → renderer flow from the project root:

```powershell
python -m adforge_renderer.creative_cli --input .\backend\sample_business_facts.json --creative-output .\artifacts\sample_creative.json --output .\artifacts\sample-creative.mp4
```

The generated creative JSON and MP4 are runtime outputs under the Git-ignored `artifacts/` directory. The renderer adapter maps the generated schema back to its existing `BusinessInput`; render timing remains owned by the renderer. Up to three approved selling points are carried through without repetition or silent omission. With more than one point, the renderer shows all three together in its middle scene to retain the existing three-scene structure.

## Run tests

```powershell
python -m pytest .\backend\tests -v
```

The schema-only storyboard production package contract is in `adforge_renderer.production_package`; its focused tests are `tests/test_production_package.py`. Strict v1 and v2 schemas are selected by their explicit `contractVersion`; v1 retains unpinned asset IDs, while v2 requires a root project ID and immutable asset version IDs. Both versions are structural contracts, not a renderer implementation or proof of asset availability. The JSON entry point enforces a 65,536-byte UTF-8 limit before parsing; its decoded-object entry point has no serialized-byte limit. Claim association is literal and conditional on caller classification, and audio timing checks use declared frame metadata only. Validation does not access the filesystem, resolve assets, inspect media, execute FFmpeg/FFprobe, verify factual truth, or establish renderability. The legacy `compile_render_plan` entry point accepts v1 validation results; the separate `compile_versioned_render_plan` entry point accepts v2 validation results and preserves immutable asset-version pins. See `docs/integration-contract.md` §5B for version compatibility and limitations.

`adforge_renderer.render_plan.compile_render_plan` compiles v1 validation results, while `compile_versioned_render_plan` compiles v2 results into immutable, frame-based instructions. The v2 plan carries the project ID and exact asset/version pins through to audio segments. Both are pure planning boundaries: they do not resolve opaque asset IDs, establish asset/render readiness, or invoke the existing fixed-scene renderer. Compilation is not proof of asset availability, renderability, or successful output. See `docs/integration-contract.md` §5D.

`adforge_renderer.asset_contract` defines pure typed metadata and lifecycle transitions for a future managed-audio boundary. Caller-declared format/duration are separate from optional observed media metadata. Readiness evidence is bound to the asset ID, project ID, and immutable version ID, and must match the declared WAV profile. Each record is immutable; replacement content requires a new version ID. No media is inspected or stored; evidence is data, not proof of origin or media verification. Asset and project IDs are identifiers, never authorization credentials. See `docs/integration-contract.md` §5E.

`adforge_renderer.asset_resolution.resolve_versioned_assets` is a pure matcher over an exact `VersionedRenderPlan` and caller-supplied immutable asset-version values. It compares project, asset, version, readiness, profile, evidence, and supplied digest fields, returning either a complete immutable snapshot or sanitized issues. It does not authenticate those values, establish compiler provenance, inspect media bytes, authorize access, or prove storage availability; it is not safe as authorization or proof of availability for a render job. Future storage-backed resolution still requires trusted evidence, authorization, immutable object-version access, and retention protection. See `docs/integration-contract.md` §5E.

The metadata/schema/failure tests do not need FFmpeg. The real renderer integration test is skipped if FFmpeg or FFprobe is unavailable.

## Local HTTP API foundation

Install the backend and test dependencies from the project root if needed:

```powershell
python -m pip install -e ".\backend[test]"
```

Start the local API explicitly from the project root:

```powershell
python -m adforge_renderer.api
```

It binds to `127.0.0.1:8000` by default. Configure a different local loopback address and port with `--host` and `--port`, for example `python -m adforge_renderer.api --host ::1 --port 8123`. Hosts must be `localhost` or a loopback IP, and ports must be from 1 to 65535. The health check is `GET http://127.0.0.1:8000/health` and returns `{"status":"ok"}`. It confirms only that this HTTP application is responding; it does not check external providers or the generation pipeline.

Run the API and existing backend tests with:

```powershell
python -m pytest .\backend\tests -v
```

The local API exposes `GET /health`, `POST /validate/preproduction`, and the separate schema-only `POST /validate/production-package` route. The production-package route accepts a bounded JSON body and reports structural validation only; it does not integrate with the renderer, assets, generation, persistence, or the frontend. These validation routes do not create or render ads.

Website scanning remains CLI-only. There is intentionally no `/scan` route: although the scanner validates resolved addresses and each redirect, HTTPX resolves the hostname again when connecting, leaving a DNS-rebinding/time-of-check-to-time-of-use gap. No deployment egress isolation or request-concurrency limit is configured. The scanner also echoes `original_url` in `ScanResult`, so a rejected URL containing credentials would be reflected in serialized output; a future HTTP adapter must redact it. See [`WEBSITE_EXTRACTION.md`](WEBSITE_EXTRACTION.md) for the security boundary and limitations. Do not expose the scanner as a network service until destination pinning or enforceable egress isolation, resource limits, and safe response handling are established.

## Milestone 3: safe website fact scan

Install the project dependencies with the setup command above, then scan one public HTML page. This command only emits a JSON review candidate file; it does not approve facts, generate copy, or render video:

```powershell
python -m adforge_renderer.scan_cli https://example.com --output .\artifacts\example-scan.json
```

`adforge-scan` is also installed as a console command. Exit codes are 0 for extracted business facts, 1 for partial/no useful facts, 2 for policy rejection, and 3 for unsupported content, fetch failure, or an output-write error (the JSON output carries the precise status). Full fetch and robots policy, bounded extraction rules, and SSRF limitations are documented in [`WEBSITE_EXTRACTION.md`](WEBSITE_EXTRACTION.md). Tests use mocked HTTPX transports and never contact arbitrary websites.

## Input fields

`sample_business.json` shows the required schema. Business name, product/service, CTA, selling points, and up to two `#RRGGBB` brand colors are validated; unknown fields are rejected. Selling points are treated as approved copy supplied by the user.
