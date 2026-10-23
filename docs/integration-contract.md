# Spotloom Studio frontend/backend integration contract

**Status: planning document.** The only implemented HTTP route is `GET /health`, a local application liveness check. The future business API boundaries and examples below are proposals only.

## 1. Purpose and non-goals

This document records the frontend's current domain and the backend's verified local capabilities to guide a future integration milestone. It does not define an implemented API contract.

No business API is implemented. The only route is the local health check described above; it does not connect the Next.js frontend to Python, transmit business data, persist state, or enable generation. The existing CLI commands are not HTTP interfaces and must not be treated as such.

## 2. Current architecture and verified capabilities

The frontend is a Next.js App Router application. The Northstar route layout wraps its nested pages in `NorthstarDemoProjectProvider` (`frontend/src/app/projects/sample-northstar/layout.tsx`). The provider holds facts, brief, and storyboard scenes in React state (`frontend/src/app/projects/sample-northstar/demo-project-provider.tsx`). This state is shared during client navigation within those routes and resets when the page is refreshed. The production package preview explicitly says no data is sent to a backend (`frontend/src/app/projects/sample-northstar/package/production-package-preview.tsx`, `ProductionPackagePreview`).

The Python package is a local Python 3.11 package with CLI entry points and a minimal FastAPI application (`backend/pyproject.toml`, `backend/adforge_renderer/api.py`). The app exposes only `GET /health`; it does not expose the CLI workflows or any business operation over HTTP. Its response confirms only that the HTTP app is responding.

Verified local workflows:

- `adforge-scan` / `python -m adforge_renderer.scan_cli`: fetch one public HTML page, extract literal candidate facts, and write a JSON result to a caller-selected local file (`backend/adforge_renderer/scan_cli.py`, `main`; `backend/adforge_renderer/website_scan.py`, `scan_website`, `SafeFetcher`, `extract_facts`).
- `adforge-render` / `python -m adforge_renderer.cli`: parse a `BusinessInput` JSON file, render an MP4, and print metadata (`backend/adforge_renderer/cli.py`, `main`; `backend/adforge_renderer/models.py`, `BusinessInput`; `backend/adforge_renderer/renderer.py`, `render_ad`).
- `python -m adforge_renderer.creative_cli`: parse a `BusinessFacts` JSON file, generate deterministic literal-copy creative JSON, adapt it to renderer input, and render an MP4 (`backend/adforge_renderer/creative_cli.py`, `main`; `backend/adforge_renderer/creative.py`, `generate_creative`, `validate_creative`, `to_renderer_input`).

The backend tests exercise these Python models, CLI behaviors, scanner policies, generator, and renderer; website scanner tests use mocked HTTP transport (`backend/tests/test_website_scan.py`, `backend/tests/test_creative.py`, `backend/tests/test_renderer.py`). They do not establish a frontend/backend network contract.

## 3. Frontend domain model

The current frontend data shapes are local TypeScript types, not submitted backend payloads:

| Frontend concept | Current shape and behavior | Source |
| --- | --- | --- |
| Demo project | `DemoProject`: `id`, `name`, `isIllustrative: true`, and `facts` | `frontend/src/app/projects/sample-northstar/review/demo-facts.ts`, `DemoProject`, `northstarDemoProject` |
| Business fact | `ProjectFact`: `id`, `category`, current `claim`, `originalClaim`, string `revisions[]`, `status`, and illustrative `source` placeholder | same file, `ProjectFact`, `DemoFactSource` |
| Review state | `unreviewed`, `approved`, `rejected`; only unreviewed facts accept an approve/reject decision; correction retains prior wording and resets status to unreviewed | same file, `ReviewStatus`, `decideDemoFact`, `correctDemoFact` |
| Creative brief | Objective (`awareness`, `engagement`, `traffic`, `conversions`), audience, product/offer, key message, value proposition, platform, aspect ratio, duration, tone, CTA, relied-upon fact IDs, and explicit `requirementsConfirmed` | `frontend/src/app/projects/sample-northstar/creative-brief.ts`, `CreativeBrief`, `initialNorthstarBrief` |
| Storyboard | Ordered scene records with ID, title, narrative purpose, visual direction, on-screen text, narration, integer duration, and transition note | `frontend/src/app/projects/sample-northstar/storyboard-model.ts`, `StoryboardScene` |
| Readiness | A derived result containing findings, severities, counts, eligible demo facts, and runtime summary | `frontend/src/app/projects/sample-northstar/preproduction-validation.ts`, `validateNorthstarPreproduction`, `PreproductionValidationResult` |

The fact-review page requires human approve/reject/correct actions. Brief confirmation is a separate human action and is invalidated when any other brief field changes (`demo-project-provider.tsx`, `updateBrief`). Neither review approval nor brief confirmation means independent factual verification. The validator derives findings from current facts, brief, and scenes; its exact-text claim matching is explicitly not semantic grounding (`preproduction-validation.ts`, `validateNorthstarPreproduction`).

The current client eligibility calculation is `getApprovedDemoFacts`, which selects only facts whose status is `approved` (`review/demo-facts.ts`). The frontend uses that for the brief and package preview. Client-derived counts, readiness findings, eligibility, and runtime are display/planning values: any future server operation that relies on them must recompute or validate them from submitted authoritative data rather than trust client-supplied derived results.

## 4. Existing backend interfaces

The only existing HTTP interface is `GET /health` (`backend/adforge_renderer/api.py`, `health`); it is not a business API and accepts no business data. The following are confirmed local JSON/CLI interfaces only.

### Website scan

`scan_cli.main` accepts a positional URL and required `--output` path. It serializes `ScanResult` to JSON at that local path and returns process exit codes (0 success, 1 partial, 2 policy blocked, 3 unsupported content/failure/write error) (`backend/adforge_renderer/scan_cli.py`, `main`; `backend/README.md`, “Milestone 3”). `ScanResult` contains `original_url`, nullable `final_url`, `status`, `facts`, `warnings`, and nullable `{code, message}` error (`backend/adforge_renderer/website_scan.py`, `ScanResult`, `ScanError`, `ScanStatus`). These are Pydantic model fields serialized by the CLI, not HTTP response fields.

`SafeFetcher` fetches one page after fetching robots policy; it validates public destinations and revalidates redirects, limits redirects and body size, disables automatic redirects and environment proxies, and applies connect/read/total network-fetch timeouts (`backend/adforge_renderer/website_scan.py`, `normalize_and_validate_url`, `SafeFetcher._request`, `SafeFetcher.fetch`, `TOTAL_TIMEOUT_SECONDS`). `extract_facts` emits literal, unreviewed candidates with website provenance, source URL, extraction method, and bounded evidence. It does not establish truth (`website_scan.py`, `extract_facts`; `backend/WEBSITE_EXTRACTION.md`). The scanner is not exposed over HTTP: HTTPX performs a separate DNS resolution for the connection, no network-egress isolation or request concurrency limit is configured, synchronous HTML parsing is outside the fetch timeout, and `ScanResult.original_url` can echo credentials from a rejected URL.

### Facts and deterministic creative

`BusinessFacts` contains a business ID and up to 32 `BusinessFact` values. Each fact has `fact_id`, `field`, `value`, `provenance`, `review_state`, and optional `supersedes_fact_id`. Provenance includes source kind, optional URL, note, extraction method, and evidence. Website source requires a URL; non-website sources cannot include one (`backend/adforge_renderer/facts.py`, `BusinessFacts`, `BusinessFact`, `FactProvenance`). The CLI accepts this model from a local JSON file, not an HTTP body (`backend/adforge_renderer/creative_cli.py`, `main`).

`generate_creative` requires unambiguous approved business name, product/service, and CTA facts; it uses approved supporting points and colors only. `validate_creative` checks references and exact textual matches, not semantic truth. `Creative` has ordered role-tagged scenes and `claim_fact_ids`, but no per-scene durations or the frontend's brief fields (`backend/adforge_renderer/creative.py`, `Creative`, `CreativeScene`, `generate_creative`, `validate_creative`).

### Renderer

`BusinessInput` accepts business name, product/service, up to three selling points, one or two brand colors, and CTA; extra fields are forbidden (`backend/adforge_renderer/models.py`, `BusinessInput`). `render_ad` creates a fixed three-scene, 1080×1920 H.264 MP4, with FFmpeg timeout and FFprobe checks for MP4, H.264, dimensions, and a 6.5–8.5 second duration. It removes the target output if rendering or validation fails (`backend/adforge_renderer/renderer.py`, `render_ad`; `backend/adforge_renderer/validation.py`, `probe_video`). The renderer accepts no frontend brief or storyboard and has no artifact-serving or download API.

### Errors and operations

The CLIs report errors on stderr and through process exit codes; there is no HTTP error contract for business operations. `scan_website` catches failures into bounded `ScanResult` error codes/messages. The render CLIs catch selected validation, I/O, and renderer errors. No authentication, authorization, job queue, managed server lifecycle, rate limiting, or remote artifact store is implemented. These characteristics are confirmed in `scan_cli.py`, `creative_cli.py`, `cli.py`, and `website_scan.py`; they are not API guarantees.

## 5. Frontend/backend compatibility matrix

| Workflow/data | Status | Evidence and gap |
| --- | --- | --- |
| Submit website URL from browser and receive candidates | **No HTTP support; unsafe to expose currently** | Python `scan_cli` scans a URL and writes a local JSON file. `/scan` is deliberately absent because DNS preflight does not pin HTTPX's connection resolution, there is no deployment egress isolation or service concurrency cap, parsing has no CPU deadline, and raw rejected URLs can be echoed. |
| Website provenance and extraction limits | **Supported in local backend model** | `BusinessFact`/`FactProvenance` and `extract_facts` capture provenance/evidence. The frontend demo source is an illustrative placeholder, not this backend schema. |
| Human review and fact corrections | **Partial / incompatible shape** | Backend `BusinessFacts.approve`, `.reject`, and `.correct` model decisions and linked superseding IDs; frontend uses `id/category/claim/revisions[]`. No API maps these shapes or persists review decisions. |
| Brief editing and confirmation | **Missing backend support** | Frontend `CreativeBrief` has no corresponding backend brief model or CLI input. Backend confirmation semantics are absent. |
| Storyboard editing and scene timing | **Partial / incompatible** | Backend `CreativeScene` supports ordered role, on-screen text, support description, and fact IDs. It has neither the frontend scene schema nor its duration/timing validation. |
| Pre-production readiness findings | **Missing backend equivalent** | `validateNorthstarPreproduction` is frontend-only. Backend has no corresponding unified validator or findings contract. |
| Deterministic creative generation | **Supported locally, not as a service** | `generate_creative` and `creative_cli` operate on `BusinessFacts` JSON. No HTTP generation endpoint; output schema is not the frontend storyboard. |
| MP4 rendering | **Supported locally, not as a service** | `render_ad` and CLI produce a local MP4 from `BusinessInput`; fixed output profile/time does not match editable frontend target aspect ratio/runtime. |
| Persistent projects, jobs, artifacts, auth | **Missing** | No business API, persistence, job model, identity, or artifact download endpoint appears in the backend package. |

## 6. Proposed future API boundaries

Everything in this section is a design proposal, not an existing endpoint or commitment to a particular URL/method. Before implementation, choose a server runtime and authentication model; then publish and version a formal schema (for example OpenAPI) generated from or tested against server-side models.

Recommended resource boundaries:

1. **Project/business context:** create or retrieve a project and submit user-provided business facts with explicit provenance. Do not conflate project identity with the current CLI's `business_id`.
2. **Website scan operation:** accept a URL as an explicit, authorized operation; return a bounded scan result and unreviewed candidates with provenance. A future service must add deployment-level egress isolation or destination-pinning beyond the scanner's documented DNS rebinding limitation.
3. **Fact review:** accept explicit human decisions and corrections. Server-side state must preserve original/revision linkage; derive approved eligibility server-side. Never let a client set `approved` as evidence of truth.
4. **Brief and storyboard:** model and validate the frontend's planning data separately from backend `Creative` and renderer input. Preserve explicit brief confirmation as a user action, not a verification assertion.
5. **Creative generation:** separately authorized operation consuming current facts and relevant planning inputs; revalidate approved fact references on the server. Generation must not run merely because the frontend says readiness passed.
6. **Render job and artifact:** a distinct operation after creative review, with bounded resource use, explicit user action, status/result handling, and controlled artifact access. Never auto-publish.

Use stable project/fact/scene IDs and version or concurrency tokens if concurrent edits are supported. Define idempotency for operations that start scans, generation, or rendering. These are recommendations, not implemented mechanisms.

## 7. Proposed request/response examples

Illustrative JSON fragments below are design sketches only. No route, body, response, or status code shown here exists in the repository. The examples intentionally omit URL paths and HTTP methods until the service boundary and authentication model are selected.

**Proposed scan result shape**, inspired by `ScanResult` and `BusinessFact` (not a current HTTP response):

```json
{
  "status": "success",
  "original_url": "https://business.example/",
  "final_url": "https://business.example/",
  "facts": [
    {
      "fact_id": "web-example",
      "field": "product_or_service",
      "value": "Example text from a page",
      "review_state": "unreviewed",
      "provenance": {
        "source": "website",
        "source_url": "https://business.example/",
        "extraction_method": "meta:description",
        "evidence": "Example text from a page"
      }
    }
  ],
  "warnings": []
}
```

**Proposed review decision shape**, not accepted by any current endpoint:

```json
{
  "fact_id": "web-example",
  "decision": "approved",
  "expected_project_version": "opaque-version"
}
```

The response should report the resulting fact/revision and project version, while making clear that the decision is a human review status, not independent factual verification. The exact versioning and response fields remain open design questions.

## 8. Fact provenance and human approval semantics

The backend distinguishes `manual`, `website`, and `model_suggestion` sources; website facts require a source URL. Optional extraction method and bounded evidence are available in `FactProvenance` (`backend/adforge_renderer/facts.py`). The scanner populates website source URL, extraction method, and evidence, and every candidate begins `unreviewed` (`backend/adforge_renderer/website_scan.py`, `extract_facts`). Extraction is literal and does not establish truth (`backend/WEBSITE_EXTRACTION.md`).

Backend `ReviewState.APPROVED` is necessary for `generate_creative`, but is not proof that the value is true. The frontend similarly labels status as approved for demo use only (`frontend/src/app/projects/sample-northstar/review/demo-facts.ts`, `getApprovedDemoFacts`; `creative.py`, `_require_fact`, `generate_creative`). Future integrations must preserve the distinction among provenance, extraction, human approval, and factual verification. Rejected claims must not be converted to negative assertions or included as approved copy. A correction must preserve a link to earlier wording and require fresh review.

The frontend currently stores `originalClaim` plus a `revisions[]` text array; the backend stores separate fact records with `supersedes_fact_id`. A mapping must define lineage explicitly rather than flattening one representation and losing IDs, sources, or review state.

## 9. Error handling and loading-state expectations

The current CLI's exit codes and model errors cannot be translated mechanically into HTTP statuses. A future service should define stable machine-readable error codes, safe user-facing messages, field-level validation details, retryability, and request correlation IDs without exposing stack traces, internal paths, or secrets. Distinguish policy rejection, unsupported page content, partial extraction, transient network failure, invalid input, generation needing review, render failure, and timeout. Preserve partial scan results and warnings only where the operation actually returns them.

The frontend will need explicit idle/loading/success/partial/blocked/error states for scan and queued operations, cancellation or timeout messaging where supported, and protection against stale responses overwriting newer edits. Readiness findings and counts should remain derived from authoritative current inputs; do not submit their displayed counts as facts. Review, brief confirmation, generation, and rendering should each have explicit user actions and appropriately recoverable error states.

## 10. Security and operational concerns

- **SSRF and egress:** the scanner rejects non-global, private, reserved, loopback, link-local, multicast, and unspecified addresses, manually validates redirects, limits requests, and fails closed on unusable robots policy. These checks do not guarantee that the connection uses the preflight IP: HTTPX resolves again after the application's check. No deployment egress isolation is configured, so no `/scan` route is exposed (`backend/WEBSITE_EXTRACTION.md`, “SSRF limitation”; `website_scan.py`, `_public_ip`, `SafeFetcher`). Do not expose scanning as a network service without egress isolation or destination pinning, with defense in depth.
- **Scanner response/resource boundary:** `ScanResult.original_url` preserves the input and may echo embedded credentials on rejected URLs. The 20-second timeout wraps fetching but not synchronous BeautifulSoup parsing; request concurrency is not bounded at an API layer. A future service must sanitize input reflection and enforce parser/resource/concurrency limits.
- **Untrusted content:** fetched HTML is parsed as data; the extractor excludes active/non-visible elements, fetches no referenced assets, and does not interpret page text as instructions (`website_scan.py`, `extract_facts`; `WEBSITE_EXTRACTION.md`). Keep extracted content untrusted in storage, logs, prompts, and UI.
- **Secrets and configuration:** current code does not implement a server configuration or API-key management boundary. Any future provider credentials must stay server-side and must never appear in frontend responses or logs.
- **Resource controls:** the scanner has byte, redirect, and time bounds; renderer FFmpeg/FFprobe subprocesses have timeouts and output validation. No deployed service-level concurrency, rate limits, process isolation, CPU/memory quotas, durable storage policy, or job queue is implemented (`website_scan.py`; `renderer.py`; `validation.py`). Add these before exposing expensive work to clients.
- **Filesystem/artifacts:** current CLIs accept local input/output paths and write local files. A service must not expose arbitrary filesystem paths; it should generate opaque artifact identifiers, control storage paths, apply retention/access rules, and stream only authorized artifacts. `creative_cli.main` writes creative JSON before checking `needs_review` and before rendering; its CLI behavior is not a transactional job contract.
- **Authorization and consent:** no user identity, authentication, authorization, or project ownership model exists. Design it before multi-user project or artifact access. Require separate explicit authorization for website scanning, generation, and rendering; never publish automatically after readiness passes.
- **Privacy and logging:** define retention, deletion, data minimization, website content handling, and redaction policies before accepting real business data. Avoid returning internal exception details; current scan errors are intentionally bounded, while render CLI diagnostics may include subprocess error text.
- **Compatibility:** the renderer is fixed to vertical 1080×1920 and roughly 7.5 seconds, while the brief permits three aspect ratios and 15/30/60 second targets. This mismatch requires an explicit supported-profile decision, not silent coercion.

## 11. Recommended integration sequence

1. Decide deployment boundary, authentication, authorization, data ownership, retention, and hardened network egress for scanning.
2. Define versioned project, fact provenance/revision, brief, and storyboard schemas; document compatibility and migrations. Keep backend and frontend names distinct where their meanings differ.
3. Add contract tests and service-level validation for scans and fact review, including hostile URLs, redirect/DNS behavior, provenance preservation, correction lineage, and explicit approvals.
4. Integrate website scan as a review-only flow, with explicit loading/partial/error states and server-returned provenance. Do not auto-approve candidates.
5. Integrate project facts and human review with server-authoritative transitions and concurrency handling.
6. Integrate brief/storyboard save and validation, resolving scene/renderer timing and aspect-ratio differences. Recompute readiness on authoritative inputs.
7. Add creative generation as a distinct explicit action after server-side fact-reference validation and human review.
8. Add a separate render job/artifact lifecycle with bounded workers and authorized retrieval. Keep publication out of scope unless separately designed and authorized.

## 12. Acceptance criteria for the future integration milestone

- The service publishes a versioned, tested schema; documented requests/responses match runtime behavior, and the frontend has no dependency on CLI-only behavior.
- Project, fact, provenance, corrections, and review decisions round-trip without losing IDs, source evidence, revisions, or statuses.
- Website candidates remain unreviewed until an explicit human decision; approval is not described as verification.
- Rejected and unreviewed facts are excluded server-side from factual creative claims; corrected facts require fresh approval and preserve prior history.
- Brief confirmation remains a distinct human action and is invalidated when applicable inputs change; it does not imply claim truth.
- The server recomputes readiness and validates scene runtime, supported media profiles, and fact references; it does not trust client-derived counts or findings.
- URL scanning has deployment-tested SSRF/egress protections, bounded resource use, safe errors, and adversarial redirect/DNS tests.
- Generation and rendering are separate, explicit, authorized, observable operations with bounded time/resources and no automatic publication.
- Artifacts have controlled storage, authorization, retention, and safe retrieval; credentials and internal paths are not exposed.
- Frontend loading, partial, validation, policy, failure, retry, and stale-response behavior is accessible and covered by tests.
- Existing demo-only behavior remains honest until a real workflow is connected; Generate Ad stays unavailable until the full approved capability exists.

## 13. Open questions and assumptions

1. What deployment boundary will host the future business API? The current FastAPI application is only a local health-check foundation.
2. Who can create, view, edit, approve, generate, render, and retrieve a project? What authentication and tenant/ownership model applies?
3. What persistence, retention, export, and deletion guarantees are required for business facts, source excerpts, briefs, and artifacts?
4. Should frontend `ProjectFact` map to backend `BusinessFact` directly, or should a versioned API DTO preserve frontend labels and backend provenance separately? How are current text revision arrays mapped to `supersedes_fact_id` lineage?
5. Does human approval mean approval of one exact version only? What happens to approval when source/value changes or evidence is updated?
6. What website scan targets are acceptable in production, and which network-egress control will close the documented DNS rebinding gap?
7. What is the authoritative brief/storyboard schema, and should creative generation use the editable storyboard or continue generating a separate fixed role sequence?
8. Which output profiles should be supported? The current frontend supports 9:16, 1:1, 16:9 and 15/30/60 seconds; the renderer produces 1080×1920 at 6.5–8.5 seconds.
9. Is a human confirmation needed before generation and a separate confirmation before rendering? What review/edit checkpoints are mandatory?
10. Which media providers, if any, are in scope later, and how will provider credentials, cost limits, failure handling, and data use be controlled?
11. What artifact retention, download authorization, malware/content scanning, and deletion policy is required?
12. What availability, concurrency, queueing, cancellation, rate limits, and observability objectives apply?
13. Which legal, advertising-policy, accessibility, and jurisdiction-specific checks are required before an ad can be treated as publishable?

## Evidence reviewed

Backend implementation and tests: `backend/adforge_renderer/{models.py,facts.py,creative.py,website_scan.py,scan_cli.py,creative_cli.py,cli.py,renderer.py,validation.py}`, `backend/tests/{test_creative.py,test_renderer.py,test_website_scan.py}`, `backend/pyproject.toml`, `backend/README.md`, and `backend/WEBSITE_EXTRACTION.md`.

Frontend domain and state: `frontend/src/app/projects/sample-northstar/{layout.tsx,demo-project-provider.tsx,creative-brief.ts,storyboard-model.ts,preproduction-validation.ts,review/demo-facts.ts,review/fact-review-workspace.tsx,brief/creative-brief-workspace.tsx,storyboard/storyboard-workspace.tsx,creative/creative-readiness-workspace.tsx,package/production-package-preview.tsx}`.

Existing planning documents such as `docs/API_CONTRACTS.md` and `docs/ARCHITECTURE.md` describe intended architecture and example APIs; they were not treated as evidence that those routes or interfaces exist.
