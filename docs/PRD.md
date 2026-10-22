# Product Requirements Document (PRD)
## AdForge AI — Website-to-Video Advertising Studio

- Status: Draft for approval
- Version: 0.1
- Last updated: 2026-10-22
- Product owner: Project author
- Initial delivery target: 7 days from implementation start
- Intended use: internship evaluation + public portfolio/GitHub project

---

## 1. Executive summary

AdForge AI is a web application that converts a business website—or manually entered business information—into a short, branded video advertisement. It combines website extraction, structured business facts, AI-assisted creative generation, deterministic validation, and programmatic video rendering.

The product is not merely an LLM prompt wrapper. Its value is an end-to-end workflow with visible evidence, explicit user control, reliable fallback behavior, measurable output quality, and a valid downloadable MP4.

The initial release is a single-instance MVP with production-minded security and modular boundaries. It is not intended to be a fully scaled commercial SaaS in week one.

## 2. Problem statement

Small businesses often lack the time, skills, or budget to create short video ads for social platforms. Creating one requires collecting brand information and assets, writing copy, designing scenes, editing video, placing accurate business details, and exporting platform-specific formats.

Existing AI workflows can produce attractive but inaccurate content, require paid providers, or fail opaquely. AdForge AI aims to simplify creation while preserving factual accuracy and clearly communicating what was generated, what was extracted, and where fallback behavior occurred.

## 3. Goals

### Product goals
1. Convert a supported public business website into a short ad through one guided workflow.
2. Allow a user to review and correct extracted facts before creative generation.
3. Produce a playable MP4 with branding, readable text, CTA, and supported aspect ratios.
4. Work without paid API credentials using deterministic creative templates and FFmpeg rendering.
5. Explain partial extraction, fallback use, provider failure, and output warnings.
6. Demonstrate software-engineering maturity through tests, documentation, security controls, and measured evaluation.

### Portfolio goals
- Clear modular architecture and typed API contracts.
- Reproducible setup from a clean environment.
- Automated tests for core paths and failure cases.
- A small, disclosed evaluation dataset and reproducible results.
- Clean commit history, screenshots, short demo video, architecture diagram, and limitations.
- Demonstrable personal understanding of every major component.

### Non-goals for the first release
- Real-time video streaming.
- Training or hosting a custom foundation/video model.
- Full multi-tenant SaaS billing.
- Team collaboration, approval workflows, or organization administration.
- Complex distributed infrastructure, Kubernetes, or microservices.
- Guaranteeing conversion lift or advertising performance.
- Automatically bypassing bot protection, CAPTCHA, login walls, or robots restrictions.
- Fully autonomous publication to social platforms.

## 4. Target users and personas

### Persona A — Small business owner
Wants a quick promotional video using their actual business information and images. Needs an understandable workflow and a downloadable result.

### Persona B — Marketing generalist
Creates variants for social placements. Needs different hooks, CTA options, platform aspect ratios, and clear control over copy and assets.

### Persona C — Developer/evaluator
Wants to assess product completeness, code quality, reliability, factual safety, and ability to explain design choices. Needs tests, setup instructions, architecture documentation, and reproducible output.

## 5. Core user journeys

### Journey A — Website to ad
1. User opens Create Ad.
2. User pastes a website URL.
3. System validates scheme and destination before fetching.
4. System extracts homepage information and candidate media; additional page crawling is bounded.
5. UI shows extracted fields with provenance and missing-field warnings.
6. User edits/approves the facts and selects an image.
7. User selects format, duration, tone, style, and CTA.
8. System creates a structured creative brief and validates claims.
9. User reviews the brief before rendering.
10. System renders, validates, and stores the MP4.
11. UI shows preview, download, warnings, and composition details.

### Journey B — Manual creation
1. User enters business name, description, offer (optional), CTA, and contact details.
2. User uploads a permitted image/logo or selects a sample asset.
3. System validates files and form fields.
4. Creative generation and rendering proceed without website scraping.
5. User previews and downloads the result.

### Journey C — Partial/failed extraction
1. Site is unreachable, blocked, JavaScript-heavy, or missing facts.
2. System returns a clear status and any safe partial results.
3. User can correct details manually or use manual mode.
4. System must not invent missing business facts to make the flow appear successful.

### Journey D — Provider failure
1. Optional LLM/video provider times out, rate-limits, or returns invalid data.
2. System applies bounded retries only where safe.
3. It falls back to a deterministic script/render path when configured.
4. The result explicitly identifies fallback usage.
5. The UI does not label a fallback clip as AI-generated footage.

## 6. Functional requirements

Priority definitions: P0 = required for first release; P1 = valuable if time remains; P2 = post-MVP.

### FR-001 — Start screen and input (P0)
- Provide URL-based and manual creation paths.
- Explain supported formats and limitations.
- Validate inputs server-side even if frontend validation exists.
- Show actionable validation errors.

Acceptance:
- Invalid URL formats are rejected before fetching.
- Manual mode can complete without a website URL.
- Form values survive ordinary navigation within the flow.

### FR-002 — Safe website extraction (P0)
- Support public HTTP/HTTPS pages only.
- Extract title, description, business name where confidently available, services, contact details, address, offers, brand colors, logo candidates, and image candidates.
- Track source URL and extraction method for extracted fields.
- Bound crawl depth, page count, response bytes, and total time.
- Handle redirects safely and revalidate every destination.
- Return `ok`, `partial`, `blocked`, `unreachable`, `invalid_url`, `timeout`, or `internal_error` as appropriate.
- Respect site access controls and do not attempt CAPTCHA bypass.

Acceptance:
- Test fixture produces expected structured data.
- A timeout produces a bounded failure response.
- Missing facts remain missing.
- Unsafe destinations are rejected.

### FR-003 — Fact sheet and human review (P0)
- Display extracted values, missing fields, source/provenance, and warnings.
- Let users correct business facts before generation.
- Distinguish website-extracted, user-provided, and model-generated values.
- User-provided values take precedence over extracted values.
- The UI must not silently convert model suggestions into verified business facts.

Acceptance:
- Edits are persisted with the job or request.
- A user can remove an incorrect offer/contact detail.
- The creative engine receives the approved fact sheet, not raw unreviewed website text alone.

### FR-004 — Creative brief and script (P0)
- Generate a structured result containing hook, message, scene list, on-screen copy, CTA, visual direction, and optional negative prompt.
- Support configurable tone, objective, duration, and aspect ratio.
- Validate the result against a versioned schema.
- Use an optional LLM provider behind an adapter.
- Provide a deterministic fallback that requires no API key.
- Do not put phone numbers or addresses into generative video prompts; render them as deterministic text overlays.

Acceptance:
- Valid structured output is generated with and without provider credentials.
- Malformed LLM output is rejected or corrected once, then falls back.
- Unsupported offers, guarantees, prices, contact details, or other high-risk claims are rejected or flagged.

### FR-005 — Creative review (P0)
- Show the script, scenes, selected image, CTA, and rendering settings before video creation.
- Allow editing of copy and selection of an approved image.
- Display whether an external AI video provider will be called and whether that could consume credits.

Acceptance:
- User can inspect the creative before starting rendering.
- The UI clearly identifies provider-dependent features.

### FR-006 — Video rendering (P0)
- Generate a valid MP4 using FFmpeg and Pillow.
- Baseline renderer supports image-based motion (pan/zoom), transitions, text overlays, business name, CTA, and optional logo.
- Support 9:16 and 16:9 initially; 1:1 may be added if the core pipeline is stable.
- Use actual user-approved or website-sourced assets; do not fabricate business imagery and present it as a real business photo.
- Keep text overlays separate from model-generated video frames.
- Validate output using FFprobe and a playable-file smoke test.

Acceptance:
- At least one full sample workflow produces a playable MP4.
- Output dimensions match selected aspect ratio.
- Business name and CTA appear in the final composition.
- Failed rendering does not produce a success state.

### FR-007 — Optional AI video provider (P1)
- Integrate a provider only behind a defined adapter.
- Make provider configuration explicit.
- Enforce timeouts, limits, and failure handling.
- Do not expose API keys to the browser.
- Clearly label actual AI footage versus FFmpeg motion graphics.
- Provider errors may fall back only if configured and the result is labeled accurately.

Acceptance:
- Missing credentials disable provider-dependent UI or clearly explain fallback.
- A provider timeout is represented in job status and logs without exposing secrets.

### FR-008 — Job status and progress (P0)
- Track states: `queued`, `running`, `completed`, `completed_with_warnings`, `failed`, `cancelled`.
- Track stages such as `scanning`, `fact_review`, `creative`, `rendering`, `validating`.
- Expose safe progress and warnings to the UI.
- Persist final job status so refresh does not lose the result.

Acceptance:
- Status transitions are validated.
- Completed jobs have a verified artifact reference.
- Failed jobs expose an actionable, non-sensitive error.

### FR-009 — Result page (P0)
- Provide video preview, download, creation settings, composition summary, warnings, and whether AI video was used.
- Use opaque IDs and safe file serving.
- Avoid exposing server filesystem paths.
- Apply retention policy to old files.

Acceptance:
- Preview and download work after page refresh.
- Invalid artifact IDs do not reveal other users' files or internal paths.

### FR-010 — Upload handling (P1)
- Support approved image/logo uploads.
- Validate size, type by content, image dimensions, and decode safety.
- Store under generated IDs rather than original filenames.
- Never execute uploaded content.

### FR-011 — Evaluation report (P0)
- Include a reproducible test dataset with expected outcomes.
- Measure extraction correctness, critical claim errors, end-to-end success, render validity, and latency.
- Clearly report sample size and limitations.

### FR-012 — Operational safety (P0 before public deployment)
- Keep secrets in environment/secret manager.
- Configure request limits, per-IP/per-user quotas, generation caps, timeouts, and safe logs.
- Require authentication or access protection before exposing paid provider credentials publicly.
- Use HTTPS in production.
- Provide health/readiness endpoints that do not leak configuration secrets.

## 7. Non-functional requirements

### Reliability
- No unbounded crawling, retries, or rendering.
- Every job reaches a terminal state or is recoverable after restart.
- Failed providers must not corrupt job records.
- A failed render must not be marked complete.

### Performance
- Record stage timings separately.
- Do not set a strict end-to-end SLA until the first baseline is measured.
- Use bounded crawl and rendering budgets.
- Keep the UI responsive while long-running work executes.

### Security and privacy
- SSRF protection on every fetch and redirect.
- File upload validation and path traversal protection.
- No secrets in frontend bundles, logs, Git, screenshots, or test fixtures.
- Clear retention behavior for business data and generated videos.
- Treat scraped website content as untrusted prompt input.
- Do not store more user data than needed for the MVP.

### Accessibility and usability
- Keyboard-usable forms and controls.
- Labels and useful error messages.
- Responsive design for desktop and mobile.
- Visible focus states and sufficient contrast.
- Respect reduced-motion preferences where practical.

### Maintainability
- Typed API schemas and frontend types.
- Small modules with explicit responsibilities.
- Automated formatting/lint/type checks.
- Tests for core business logic and dangerous failure paths.
- Documentation kept in sync with actual implementation.

### Portability
- Fresh local setup documented.
- Environment configuration uses `.env.example` with placeholders.
- Docker support is a target if it does not endanger the one-week core pipeline.

## 8. Product analytics and evaluation

No third-party analytics are required for the MVP. Collect internal stage timings and outcomes without storing sensitive page contents unnecessarily.

Minimum metrics:
- Supported-site end-to-end success rate.
- Field-level extraction precision/recall on labeled examples.
- Unsupported critical claim count.
- Schema-valid creative output rate.
- Valid MP4 rate.
- Median and p95 stage timings once enough runs exist.
- Provider failure and fallback rates.
- Cost/credit usage when an external provider is enabled.

Initial target hypotheses are in `AI_RELIABILITY_EVALUATION.md`. They are targets, not established results.

## 9. UX requirements

Main screens:
1. Landing/Create.
2. Business source input (website/manual).
3. Extracted facts review.
4. Creative configuration.
5. Creative/script review.
6. Generation progress.
7. Result and download.
8. Optional job history.

Avoid a generic chatbot interface. The product should feel like a focused creative studio with a visible workflow, business facts, media selection, a preview area, and clear controls.

## 10. Release acceptance criteria

Release candidate is acceptable when:
- Fresh setup instructions work.
- A supported test website can be processed end-to-end.
- Manual mode works without scraping.
- A deterministic creative fallback exists.
- A valid MP4 is produced and downloadable.
- Facts are reviewable and missing facts are not invented.
- Critical SSRF cases are covered by tests.
- Failure states are understandable.
- Evaluation results and limitations are documented.
- No credentials or private artifacts are committed.
- A short demo can be reproduced by another person.

## 11. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope too large for one week | Ship P0 only; defer integrations and history polish |
| Free provider limits | Deterministic fallback; optional provider adapter |
| Scraping variability | Fixtures, bounded crawl, manual correction path |
| Unsupported claims | Evidence/provenance, fact checks, human review |
| Video toolchain issues | Validate FFmpeg early; create a render-only vertical slice by Day 4 |
| Public abuse/credit drain | Do not expose paid provider keys without access control and quotas |
| Vibe-coded visual result | Design tokens, reference-led design, real-browser visual review |
| Agent-generated mistakes | Inspect diffs, run tests, keep milestones small, document decisions |

## 12. Future roadmap (not first-week commitments)

- Multiple ad concepts with selection/ranking.
- More formats and platform-specific safe areas.
- Better asset relevance ranking.
- Optional AI video generation.
- Postgres and durable job queue for multiple workers.
- Object storage for artifacts.
- User accounts, project history, usage limits and audit logs.
- Human approval and brand-kit support.
- Evaluation dashboard and A/B testing.
- Deployment pipeline, observability and backups.
