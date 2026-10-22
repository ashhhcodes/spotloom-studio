# Implementation Roadmap — First Week

## Planning rule
Do not attempt all optional features. Ship a complete, tested URL/manual-input-to-MP4 path first. Every day ends with a demonstrable artifact and a short update to `PROGRESS.md`.

## Day 0 — Before coding
- Approve PRD, architecture and design direction.
- Create repository and copy these docs into `/docs`.
- Choose package managers and supported OS/runtime versions.
- Confirm FFmpeg and browser availability on the development machine.
- Define a small fixture dataset and expected outcomes.
- Add `.gitignore`, `.env.example`, formatter/linter/test setup.
- Do not add real secrets or provider dependencies yet.

Exit gate: project skeleton runs and docs are committed.

## Day 1 — Vertical slice foundation
- Create FastAPI app, config, schemas, health endpoints.
- Create Next.js app shell and design tokens.
- Add basic URL/manual form and typed API client.
- Add job model and initial persistence.
- Build one deterministic sample path using a fixture business.

Exit gate: frontend talks to backend; health and basic job APIs work.

## Day 2 — Website extraction
- URL normalization and SSRF defenses.
- HTTPX + BeautifulSoup extraction.
- Candidate image discovery and bounded extraction.
- Provenance-aware fact schema.
- Partial/blocked/timeout outcomes.
- Add fixtures and unit/integration tests.

Exit gate: supported fixtures return expected fact sheets; unsafe URLs are rejected.

## Day 3 — Creative engine
- Define versioned creative schema.
- Deterministic creative template.
- Optional LLM adapter with timeout and schema validation.
- Fact guard and explicit user approval.
- Review screen for facts and creative output.

Exit gate: valid creative output works with no provider key; malformed provider output falls back safely.

## Day 4 — Video renderer (critical checkpoint)
- FFmpeg/Pillow render from a fact sheet/creative JSON.
- Motion effects, title/CTA overlays and logo placeholder.
- Support 9:16 and 16:9.
- FFprobe output validation.
- Add sample fixture assets and render tests.

Exit gate: valid MP4 can be generated from prepared data without frontend. If this gate fails, defer optional LLM/video-provider work.

## Day 5 — End-to-end UI
- Connect scan, fact review, creative review, render job and result page.
- Show progress and clear error/warning states.
- Preview/download MP4.
- Refresh-safe result state.
- Validate long text and missing optional facts.

Exit gate: a supported website goes from URL to downloadable MP4 through the UI.

## Day 6 — Evaluation and hardening
- Run labeled dataset.
- Add negative tests for SSRF, timeouts, malformed LLM output, missing assets and render failures.
- Fix highest-severity bugs.
- Check responsive UI, keyboard flow and accessibility basics.
- Measure timings and output validity.

Exit gate: report actual metrics and known limitations.

## Day 7 — Packaging and demo
- Fresh-install verification.
- Docker setup if feasible without destabilizing local setup.
- README, architecture diagram, API docs and security notes.
- Screenshots and 60–90 second demo recording.
- Clean Git history, secret scan and final smoke test.
- Produce a concise handoff note for the internship evaluator.

Exit gate: another person can follow the instructions and reproduce the demo.

## Cut line if behind schedule
Defer in this order:
1. Multiple creative variants.
2. QR code and audio polish.
3. AI video provider integration.
4. Job history UI.
5. Online deployment.

Do not defer:
- Valid MP4.
- Manual fallback for missing facts.
- Safe URL fetching.
- Honest failure/fallback labels.
- Tests for core behavior.
- Setup documentation.

## Later production-hardening phase
After the one-week deliverable:
- Authentication and per-user authorization.
- Postgres and durable background queue.
- Object storage and signed URLs.
- Observability, alerts, backups and restore tests.
- Usage/credit accounting and billing controls.
- More robust SSRF isolation and browser sandbox.
- Broader evaluation dataset and human review tooling.
- Deployment pipeline and rollback process.
