# Spotloom Studio frontend/backend integration contract

**Status: partially implemented contract.** The local FastAPI app exposes `GET /health` and `POST /validate/preproduction`. The validation route is described in §5A. Website scanning, review, persistence, generation, rendering, and other business API boundaries remain proposals or unavailable as stated below.

## 1. Purpose and non-goals

This document records the frontend's current domain, backend's verified local capabilities, and the limited implemented pre-production validation contract. Other business API boundaries remain proposals.

The validation route accepts caller-submitted facts, a brief, and storyboard, then applies strict schema checks and derives runtime. It does not connect the Next.js frontend to Python, persist state, or enable generation. The existing CLI commands are not HTTP interfaces and must not be treated as such.

## 2. Current architecture and verified capabilities

The frontend is a Next.js App Router application. The Northstar route layout wraps its nested pages in `NorthstarDemoProjectProvider` (`frontend/src/app/projects/sample-northstar/layout.tsx`). The provider holds facts, brief, and storyboard scenes in React state (`frontend/src/app/projects/sample-northstar/demo-project-provider.tsx`). This state is shared during client navigation within those routes and resets when the page is refreshed. The production package preview explicitly says no data is sent to a backend (`frontend/src/app/projects/sample-northstar/package/production-package-preview.tsx`, `ProductionPackagePreview`).

The Python package is a local Python 3.11 package with CLI entry points and a minimal FastAPI application (`backend/pyproject.toml`, `backend/adforge_renderer/api.py`). The app exposes `GET /health` and the structural `POST /validate/preproduction`; it does not expose CLI workflows over HTTP. The health response confirms only that the HTTP app is responding.

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

The existing HTTP interfaces are `GET /health` and `POST /validate/preproduction` (`backend/adforge_renderer/api.py`); the latter accepts only caller-supplied structural validation inputs, as specified in §5A. The following other interfaces are confirmed local JSON/CLI interfaces only.

### Website scan

`scan_cli.main` accepts a positional URL and required `--output` path. It serializes `ScanResult` to JSON at that local path and returns process exit codes (0 success, 1 partial, 2 policy blocked, 3 unsupported content/failure/write error) (`backend/adforge_renderer/scan_cli.py`, `main`; `backend/README.md`, “Milestone 3”). `ScanResult` contains `original_url`, nullable `final_url`, `status`, `facts`, `warnings`, and nullable `{code, message}` error (`backend/adforge_renderer/website_scan.py`, `ScanResult`, `ScanError`, `ScanStatus`). These are Pydantic model fields serialized by the CLI, not HTTP response fields.

The scanner's verified threat surface, no-go decision, candidate architectures, and future security requirements are documented in [`website-fetching-threat-model.md`](website-fetching-threat-model.md). The document is a design proposal; it does not add a route or infrastructure.

`SafeFetcher` fetches one page after fetching robots policy; it validates public destinations and revalidates redirects, limits redirects and body size, disables automatic redirects and environment proxies, and applies connect/read/total network-fetch timeouts (`backend/adforge_renderer/website_scan.py`, `normalize_and_validate_url`, `SafeFetcher._request`, `SafeFetcher.fetch`, `TOTAL_TIMEOUT_SECONDS`). `extract_facts` emits literal, unreviewed candidates with website provenance, source URL, extraction method, and bounded evidence. It does not establish truth (`website_scan.py`, `extract_facts`; `backend/WEBSITE_EXTRACTION.md`). The scanner is not exposed over HTTP: HTTPX performs a separate DNS resolution for the connection, no network-egress isolation or request concurrency limit is configured, synchronous HTML parsing is outside the fetch timeout, and `ScanResult.original_url` can echo credentials from a rejected URL.

### Facts and deterministic creative

`BusinessFacts` contains a business ID and up to 32 `BusinessFact` values. Each fact has `fact_id`, `field`, `value`, `provenance`, `review_state`, and optional `supersedes_fact_id`. Provenance includes source kind, optional URL, note, extraction method, and evidence. Website source requires a URL; non-website sources cannot include one (`backend/adforge_renderer/facts.py`, `BusinessFacts`, `BusinessFact`, `FactProvenance`). The CLI accepts this model from a local JSON file, not an HTTP body (`backend/adforge_renderer/creative_cli.py`, `main`).

`generate_creative` requires unambiguous approved business name, product/service, and CTA facts; it uses approved supporting points and colors only. `validate_creative` checks references and exact textual matches, not semantic truth. `Creative` has ordered role-tagged scenes and `claim_fact_ids`, but no per-scene durations or the frontend's brief fields (`backend/adforge_renderer/creative.py`, `Creative`, `CreativeScene`, `generate_creative`, `validate_creative`).

### Renderer

`BusinessInput` accepts business name, product/service, up to three selling points, one or two brand colors, and CTA; extra fields are forbidden (`backend/adforge_renderer/models.py`, `BusinessInput`). `render_ad` creates a fixed three-scene, 1080×1920 H.264 MP4, with FFmpeg timeout and FFprobe checks for MP4, H.264, dimensions, and a 6.5–8.5 second duration. It removes the target output if rendering or validation fails (`backend/adforge_renderer/renderer.py`, `render_ad`; `backend/adforge_renderer/validation.py`, `probe_video`). The renderer accepts no frontend brief or storyboard and has no artifact-serving or download API.

### Errors and operations

The CLIs report errors on stderr and through process exit codes. The validation endpoint's bounded HTTP errors are specified in §5A; there are no HTTP error contracts for scan, generation, or rendering operations because those routes are absent. `scan_website` catches failures into bounded `ScanResult` error codes/messages. The render CLIs catch selected validation, I/O, and renderer errors. No authentication, authorization, job queue, managed server lifecycle, rate limiting, or remote artifact store is implemented. These characteristics are confirmed in `scan_cli.py`, `creative_cli.py`, `cli.py`, and `website_scan.py`; they are not API guarantees.

### Typed integration schemas and validation API

`backend/adforge_renderer/integration_schemas.py` defines strict Pydantic schemas and pure validation helpers. `POST /validate/preproduction` uses those schemas and `validate_contract_input`; it does not add persistence, generation, or rendering. `/scan` and all other business endpoints remain absent. The helper accepts supplied Python/JSON-shaped data and returns a deterministic validity flag, sanitized field paths/codes, and a derived runtime when all scene data is valid. It performs no network, filesystem, subprocess, generation, or rendering operations.

The implemented schemas are intentionally frontend-shaped:

- **Business claim:** `id`, `category`, `claim`, `originalClaim`, `revisions`, `status`, and `source`. Status is exactly `unreviewed`, `approved`, or `rejected`. `source` contains `kind`, `reference`, `pageOrSection`, and nullable `excerpt`; kinds are `illustrative-placeholder`, `manual`, `website`, and `model_suggestion`. Website references must be absolute HTTP(S) URLs without credentials. This check parses a supplied string only and does not resolve or fetch it. Missing source metadata is invalid; fact ID duplication is invalid. An approval value is accepted as caller-supplied data, not trusted evidence or authorization.
- **Creative brief:** `objective` (`awareness`, `engagement`, `traffic`, `conversions`), `targetAudience`, `productOrOffer`, `keyMessage`, `valueProposition`, `platform` (`instagram`, `tiktok`, `youtube`, `other`), `aspectRatio` (`9:16`, `1:1`, `16:9`), `duration` (15, 30, 60), `tone`, `callToAction`, `reliedUponFactIds`, and boolean `requirementsConfirmed`. Required text must be nonblank; `valueProposition` may be empty. Fact references must use the bounded lowercase fact-ID form and be unique. A false confirmation is structurally valid and remains distinct from factual verification.
- **Storyboard:** `scenes` with each scene's `id`, `title`, `narrativePurpose`, `visualDirection`, `onScreenText`, `narration`, `durationSeconds`, and `transitionNote`. Scene titles must be nonblank, IDs unique, and duration a strict whole integer from 1 through 60. Empty storyboard collections are structurally valid, but runtime is unavailable (`None`). Runtime is derived only when every scene is valid and the collection is nonempty; no client-supplied total is accepted.

Schemas reject extra keys, non-string text, numeric strings/fractional/bool durations, invalid enums, missing required properties, duplicate IDs/references, and out-of-bound values. Values are not silently coerced or trimmed. Current implemented bounds: at most 32 claims, 20 text revisions per claim, 32 relied-upon fact IDs, and 32 scenes; claim/original/revision text 240 characters; category 80; source reference 2,048, section 240, excerpt 240; required brief text 500 and value proposition 500; scene title 120, visual direction/narration 1,000, and the other scene text fields 500; IDs 64. Extra-key names are redacted from the helper's issue paths. These are bounded integration-schema values, not yet agreed user-facing limits; 32 claim capacity and 240-character facts follow existing backend precedent, while the scene and brief limits are proposed and need frontend/product confirmation before a connected workflow.

The Python model deliberately differs from existing backend `BusinessFact`: this schema uses the frontend field names and text revision array, while `BusinessFact` uses `fact_id`, `field`, `value`, structured `provenance`, `review_state`, and `supersedes_fact_id`. The frontend currently supports only illustrative-placeholder source objects, while the integration schema additionally permits backend-like source kinds; the mapping must translate reference/page/section/evidence fields without losing provenance. Frontend scene schema has no maximum collection size, whereas this schema bounds it to 32. No project identity/version, concurrency token, persistence, authority to approve, or source verification is introduced. The API request/response shape is specified separately in §5A. Schema validation checks structure only; it neither establishes claim truth nor converts review status into proof. See [`website-fetching-threat-model.md`](website-fetching-threat-model.md) for the separate no-go decision and security gates for any future website-fetch endpoint.

#### Compatibility verification (Phase 6D.2)

`backend/tests/fixtures/contract-compatibility.json` is grounded in the current Northstar demo facts, initial brief, and initial storyboard. Python tests load the fixture directly and validate it with the Pydantic models. `backend/tests/verify_frontend_contract.mjs` uses the already-installed TypeScript compiler to type-check the valid fixture against the actual frontend `ProjectFact`, `CreativeBrief`, and `StoryboardScene` types, compiles the relevant existing frontend modules to a temporary directory, and executes their helpers against the shared fixture and mutations. It adds no test framework or frontend source. The script validates temporary output cleanup and its runtime assertions are separate from Python tests.

Verified common behavior: the valid fixture matches the initial Northstar defaults and field names; review status strings and brief selections/duration values align; scene order follows array order; both runtime helpers sum valid durations and return unavailable for empty or invalid durations; duplicate fact/scene IDs are blocked by their corresponding validators; and frontend corrections retain the old claim and reset the current status to `unreviewed`. Python rejects a client-supplied runtime field, while the frontend helper accepts only scene durations and derives its own total. The compile check proves the valid fixture is assignable to the current frontend static types. The frontend types are erased at runtime: frontend helpers and pre-production checks are not a general request-schema validator. TypeScript checking of application source plus execution of these helpers must not be described as runtime JSON validation.

The following are verified mapping differences, not silently resolved by these tests:

- The shared frontend fixture has `facts` as a list; Python `BusinessClaims` and `validate_contract_input` expect an object containing `{"facts": [...]}`. The Python compatibility test supplies that explicit wrapper. A future adapter must choose the wire shape.
- Frontend `ProjectFact` uses `id/category/claim/originalClaim/revisions/status/source`; backend `BusinessFact` uses `fact_id/field/value/provenance/review_state/supersedes_fact_id`. The frontend-shaped claim schema is not directly accepted as `BusinessFact`; the test demonstrates that a mapping layer is required. The frontend source type currently permits only `illustrative-placeholder`, while Python's schema additionally accepts `manual`, `website`, and `model_suggestion`. Frontend revision strings do not preserve backend supersession IDs or per-revision provenance.
- TypeScript types and the demo editor impose no text or collection size caps. Python imposes the limits listed above (including 32 scenes, 20 revisions, 240-character claim text, and bounded brief/scene fields). These are still proposed integration limits and require agreement before UI/backend integration. Python also constrains fact and scene IDs more narrowly than the frontend's `string` declarations.
- Frontend pre-production validation reports some conditions as readiness findings while Python's structural schemas treat them as valid: `requirementsConfirmed: false`, empty storyboards, and empty narrative purpose. The Phase 6E.2 backend evaluator now emits the corresponding brief-confirmation, empty-storyboard, and missing-purpose findings after schema validation. Python also accepts an empty storyboard structurally but reports its runtime as unavailable. Invalid enum values, missing required brief fields, duplicate IDs, and invalid durations remain schema errors on the API; these readiness-style checks are not performed by TypeScript's erased types.
- Python rejects extra keys and coercible types. The frontend helper ignores unknown object properties at runtime; compile-time excess-property checking applies only in certain typed literal contexts and is not an input security boundary. The helper's current numeric duration check rejects fractional values, strings, and values outside 1–60.

Automated frontend evidence is limited to the valid fixture's TypeScript assignability and execution of current frontend helper functions from Node after compiling them with the existing compiler. Invalid JSON fixture variants are not typechecked against compile-time types because the frontend has no runtime schema validator; the runtime readiness helper was exercised for the documented mutations. Python Pydantic tests exercise actual runtime acceptance/rejection. These checks do not establish authorization or claim verification. The validation API now accepts the documented Python schema; no frontend/backend network connection exists.

### 5A. Implemented pre-production validation endpoint (Phase 6E.1)

`POST /validate/preproduction` is the only business-data HTTP endpoint. It is read-only, deterministic, and evaluates each request independently. The server is still bound to `127.0.0.1` by default. The endpoint accepts only the following top-level keys; each nested object is checked by the existing `BusinessClaims`, `CreativeBrief`, and `StoryboardInput` schemas through `validate_contract_input`:

```json
{
  "facts": { "facts": [] },
  "brief": {
    "objective": "awareness",
    "targetAudience": "People looking for a considered everyday cup",
    "productOrOffer": "Small-batch roasted coffee",
    "keyMessage": "A good cup, made simple.",
    "valueProposition": "",
    "platform": "instagram",
    "aspectRatio": "9:16",
    "duration": 15,
    "tone": "Warm, considered, and clear",
    "callToAction": "Learn more",
    "reliedUponFactIds": [],
    "requirementsConfirmed": false
  },
  "storyboard": {
    "scenes": [
      {
        "id": "scene-one",
        "title": "Opening",
        "narrativePurpose": "Set the tone",
        "visualDirection": "Illustrative visual direction",
        "onScreenText": "",
        "narration": "",
        "durationSeconds": 15,
        "transitionNote": ""
      }
    ]
  }
}
```

The `facts` wrapper is required because the pure helper validates `BusinessClaims`; its `facts` list may be empty. When supplied, all facts and provenance are caller-provided and are not independently verified. The endpoint does not load the frontend's in-memory state. It accepts `requirementsConfirmed` as a structural boolean only; `false` is valid and `true` is not evidence that the brief is factual. Caller-provided review status is likewise not verification or authorization.

A schema-valid response uses this shape. This representative response is grounded in the shared Northstar fixture with one fact marked approved in the submitted input, the brief confirmation signal set, and a 15-second scene. Runtime is calculated from every submitted scene duration by `calculate_storyboard_runtime`; findings and counts are recomputed from the request on every call:

```json
{
  "requestSchemaValid": true,
  "evaluationStatus": "evaluated-with-limitations",
  "readinessStatus": "ready-for-human-review",
  "briefConfirmationSignal": "caller-declared-confirmed",
  "factualVerification": "not-performed",
  "findings": [{
    "id": "grounding.exact-match-limitations",
    "severity": "info",
    "category": "grounding",
    "title": "Claim matching is intentionally limited",
    "explanation": "Only exact text matches after lowercase conversion and whitespace normalization are associated with facts. Unmatched copy and paraphrases are not analyzed and are not thereby verified or safe.",
    "resolution": "Manually review all creative text against source evidence; this endpoint does not independently verify supplied sources.",
    "destinationRoutes": ["/projects/sample-northstar/storyboard", "/projects/sample-northstar/review"],
    "blocksReadiness": false,
    "affectedFactId": null,
    "affectedSceneId": null
  }, {
    "id": "production.checks-unavailable",
    "severity": "info",
    "category": "production",
    "title": "Additional production checks are not evaluated",
    "explanation": "This deterministic evaluation does not independently verify sources or claims, analyze semantic meaning, assess legal or advertising policy, persist data, or generate media.",
    "resolution": "Treat this result as planning support only; human review remains necessary.",
    "destinationRoutes": ["/projects/sample-northstar/creative"],
    "blocksReadiness": false,
    "affectedFactId": null,
    "affectedSceneId": null
  }],
  "summary": {"blockerCount": 0, "warningCount": 0, "infoCount": 2},
  "factSummary": {
    "total": 1,
    "callerMarkedApproved": 1,
    "unreviewed": 0,
    "rejected": 0,
    "invalidStatus": 0,
    "eligibleFactIds": ["product"]
  },
  "storyboardSummary": {
    "sceneCount": 1,
    "plannedRuntimeSeconds": 15,
    "targetRuntimeSeconds": 15,
    "runtimeDifferenceSeconds": 0,
    "runtimeUnavailableReason": null
  }
}
```

The example finding and summaries are from the shared Northstar fixture. Finding entries also contain `affectedFactId` and `affectedSceneId` when applicable. An empty scene list is schema-valid, returns a `storyboard.empty` blocker, and has `plannedRuntimeSeconds: null` with `runtimeUnavailableReason: "empty"`. Invalid scene data makes the request schema invalid; no readiness findings are returned and no partial runtime is reported. Invalid nested contract data returns HTTP 422 with the existing sanitized issue semantics:

```json
{
  "requestSchemaValid": false,
  "evaluationStatus": "not-evaluated",
  "detail": "Request does not match the supported pre-production contract.",
  "issues": [
    {
      "path": "storyboard.scenes.0.durationSeconds",
      "code": "greater_than_equal",
      "message": "Value does not match the supported contract."
    }
  ],
  "plannedRuntimeSeconds": null
}
```

Malformed JSON, missing top-level fields, wrong top-level types, and unknown top-level fields return HTTP 422 with `requestSchemaValid: false`, `evaluationStatus: "not-evaluated"`, no issue details, and a null runtime. Error responses do not echo submitted values or exception text. Unexpected validation failures are logged only with a fixed event and exception class, and return HTTP 500 with `evaluationStatus: "failed"` and `{"detail":"Pre-production validation could not be completed."}`. `GET /health` is unchanged.

`PreproductionFinding` fields are `id`, `severity` (`blocker`, `warning`, `info`), `category` (`brief`, `facts`, `storyboard`, `runtime`, `grounding`, `production`), `title`, `explanation`, `resolution`, `destinationRoutes`, `blocksReadiness`, and nullable affected IDs. The summary's blocker count is derived from `blocksReadiness`; warning and info counts are derived from severity. Finding IDs are deduplicated and ordered by severity, category, affected entity ID, and ID. `readinessStatus` is `needs-attention` if any blocker exists, otherwise `ready-for-human-review`; that status never means production readiness. `evaluationStatus` is always `evaluated-with-limitations` for valid requests. The brief confirmation signal is reported separately as `caller-declared-confirmed` or `not-confirmed`. `factualVerification` is always `not-performed`.

A 200 response means the request matches the structural contract and the supported deterministic rules were evaluated. It does not mean the brief is factually correct, caller-marked approvals are independently reviewed or verified, claims are semantically grounded, or an ad is ready. No client-supplied runtime, readiness, finding, or count is accepted. The endpoint does not cross-check `reliedUponFactIds` against facts or compare scene IDs against a client-supplied fact relationship because no such relationship exists in the models. It associates only exact normalized copy matches in on-screen text and narration, as the frontend does. No HTTP client, filesystem, subprocess, persistence, scanning, generation, rendering, export, or frontend integration is used.

#### Frontend rule mapping and parity limits (Phase 6E.2)

The reference is `frontend/src/app/projects/sample-northstar/preproduction-validation.ts`, with the fact status helpers in `review/demo-facts.ts`, the brief types in `creative-brief.ts`, and scene types/runtime helpers in `storyboard-model.ts`. The backend evaluator is `backend/adforge_renderer/preproduction_validation.py`. This table records where the backend mirrors behavior and where strict request-schema errors take precedence:

| Frontend rule / trigger | Frontend outcome | Backend behavior and parity |
| --- | --- | --- |
| Required brief text empty; invalid choices; non-string optional value proposition | Blocker finding with brief destination | These values violate strict Pydantic schemas and return sanitized 422 schema issues; they are not readiness findings. |
| `requirementsConfirmed` is not `true` | `brief.confirmation.required`, blocker | Same stable ID, blocker, category, and brief destination. Wording is generic because the API cannot know whether inputs were prefilled demo defaults. The output separately labels the value as caller-declared confirmation. |
| Brief demo-default notice | `brief.demo-defaults`, info | Not emitted: the request has no field proving the values originated as Northstar demo defaults. |
| Fact ID/status invalid or IDs duplicated | Blocker findings in the frontend’s defensive runtime validator | Strict schema rejects these with 422 before evaluation; valid input therefore has zero invalid statuses. |
| Unreviewed or rejected fact | Per-fact warning; rejected copy must not be used | Same stable IDs/severity/routes. Finding text says these are caller-supplied states. Neither state establishes truth; approval is only a submitted status. |
| No approved facts | `facts.none-approved`, warning | Same condition and warning; summary exposes caller-marked counts and eligible IDs, not verified facts. |
| Empty storyboard | `storyboard.empty`, blocker; runtime unavailable | Same blocker. Runtime is null and unavailable reason is `empty`. |
| No usable visual direction, on-screen text, or narration across scenes | `storyboard.no-usable-content`, blocker | Same condition, severity, and storyboard route. |
| Blank narrative purpose | Per-scene blocker | Same finding where the schema permits an empty narrative-purpose string. |
| Missing visual direction when any scene has previewable content | Per-scene blocker | Same global trigger and per-scene finding. |
| Blank title, malformed scene, duplicate/invalid IDs, invalid duration | Defensive readiness blockers in frontend | Strict schema errors return 422 instead of a readiness finding. For invalid duration the runtime remains null in the error response. |
| Runtime differs from target | `runtime.target-mismatch`, warning | Exact comparison: any nonzero difference warns. Frontend defines no tolerance; backend uses zero tolerance and makes no automatic changes. |
| On-screen text or narration exactly matches a valid fact after trim, ECMAScript-whitespace collapse, and lowercase | Approved match is info; unreviewed/rejected match is warning; affected fact and scene IDs included | Same channels and normalized exact-match rule; no visual-direction, semantic, paraphrase, or unsupported scene-to-fact inference. Caller status controls the label only; matching does not verify truth. |
| Exact-match limitation notice | `grounding.exact-match-limitations`, info | Same stable ID and limitation. |
| Demo-only production boundary notice | `production.demo-only-boundary`, info | Adapted to `production.checks-unavailable`, info. API input is not necessarily demo content, so the evaluator does not label the submitted content demo-only. |
| Findings order/deduplication and counts | Derived; status uses blocker count | Same severity/category/entity ordering, stable IDs and deduplication; all counts are derived from returned findings. |

The backend evaluator only runs after schema validation. Therefore, frontend defensive findings for malformed IDs/statuses, missing required brief fields, invalid brief selections, missing titles, or invalid durations are represented as HTTP 422 issues, not successful evaluation findings. Source provenance is required and structurally validated but not fact-checked. Frontend-specific data limitations also remain: no project-default origin marker, no authenticated reviewer identity, no semantic claim grounding, and no per-scene fact relationship. A caller can submit `requirementsConfirmed: true` or `status: "approved"`; those values are not authenticated, authorized, or treated as factual verification.

## 5. Frontend/backend compatibility matrix

| Workflow/data | Status | Evidence and gap |
| --- | --- | --- |
| Submit website URL from browser and receive candidates | **No HTTP support; unsafe to expose currently** | Python `scan_cli` scans a URL and writes a local JSON file. `/scan` is deliberately absent because DNS preflight does not pin HTTPX's connection resolution, there is no deployment egress isolation or service concurrency cap, parsing has no CPU deadline, and raw rejected URLs can be echoed. |
| Website provenance and extraction limits | **Supported in local backend model** | `BusinessFact`/`FactProvenance` and `extract_facts` capture provenance/evidence. The frontend demo source is an illustrative placeholder, not this backend schema. |
| Human review and fact corrections | **Partial / incompatible shape** | Backend `BusinessFacts.approve`, `.reject`, and `.correct` model decisions and linked superseding IDs; frontend uses `id/category/claim/revisions[]`. No API maps these shapes or persists review decisions. |
| Brief editing and confirmation | **Validation signal only** | The API validates the brief and reports the caller-submitted confirmation signal; it does not provide editing, persistence, reviewer identity, or authoritative confirmation. |
| Storyboard editing and scene timing | **Partial / incompatible** | Backend `CreativeScene` supports ordered role, on-screen text, support description, and fact IDs. It has neither the frontend scene schema nor its duration/timing validation. |
| Pre-production readiness findings | **Supported deterministic subset** | `POST /validate/preproduction` returns supported frontend-aligned findings, derived counts/status, and runtime. Schema-invalid data remains a 422. Project-default origin, semantic grounding, verified evidence, policy review, and other production checks remain unsupported. |
| Deterministic creative generation | **Supported locally, not as a service** | `generate_creative` and `creative_cli` operate on `BusinessFacts` JSON. No HTTP generation endpoint; output schema is not the frontend storyboard. |
| MP4 rendering | **Supported locally, not as a service** | `render_ad` and CLI produce a local MP4 from `BusinessInput`; fixed output profile/time does not match editable frontend target aspect ratio/runtime. |
| Persistent projects, jobs, artifacts, auth | **Missing** | No project-management API, persistence, job model, identity, or artifact download endpoint appears in the backend package. |

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
