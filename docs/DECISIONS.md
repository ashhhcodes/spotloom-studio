# Architecture Decision Record (ADR) Log

This file is the source of truth for decisions that affect product scope or architecture. Add a dated entry when a decision changes.

## ADR-001 — Independent implementation
- Date: 2026-10-22
- Status: Accepted
- Decision: Build an independent website-to-video advertising product inspired by the shared Adsify description. Do not copy its codebase or claim its features as our own.
- Rationale: The project must demonstrate the author's own engineering and be portfolio-appropriate.
- Consequences: We define our own structure, contracts, UI, tests and implementation history.

## ADR-002 — Balanced internship and portfolio scope
- Date: 2026-10-22
- Status: Accepted
- Decision: Optimize for a working internship demo and a maintainable portfolio foundation, with a one-week first-delivery target.
- Consequences: P0 features must form a complete end-to-end pipeline. Optional features are deferred if they threaten the core.

## ADR-003 — Codex as primary coding agent
- Date: 2026-10-22
- Status: Accepted
- Decision: Use Codex as the primary codebase owner. Other tools such as Grok or Antigravity may provide bounded critiques or alternate implementations, but must not independently change architecture without review.
- Rationale: A single source of truth reduces conflicting code and context drift.
- Consequences: All tools must read `LLM_CONTEXT.md` and relevant docs. Human reviews changes and runs tests.

## ADR-004 — Frontend quality is design-led
- Date: 2026-10-22
- Status: Accepted
- Decision: Do not depend on a particular model to avoid generic AI-generated UI. Establish a design system, real screen requirements and visual QA before accepting the frontend.
- Consequences: Screenshots and browser review are part of acceptance. Grok is optional, not required.

## ADR-005 — Modular monolith
- Date: 2026-10-22
- Status: Proposed
- Decision: Use a Next.js frontend and FastAPI backend with modular services. Avoid microservices in the first release.
- Rationale: Lowest operational complexity for a one-week project.
- Consequences: Keep boundaries clean enough to extract workers/services later.

## ADR-006 — Deterministic renderer as baseline
- Date: 2026-10-22
- Status: Proposed
- Decision: The app must produce a valid MP4 using FFmpeg and approved assets without paid video generation.
- Rationale: Guarantees an end-to-end demo and avoids provider-credit dependence.
- Consequences: AI video generation is optional and must be accurately labeled.

## ADR-007 — Facts have provenance and user review
- Date: 2026-10-22
- Status: Proposed
- Decision: Extracted facts carry provenance; users can correct/approve them; LLM suggestions are not verified facts.
- Rationale: Marketing claims must be grounded and reviewable.
- Consequences: Fact review and validators are part of the core workflow.

## ADR-008 — SQLite for initial single-instance MVP
- Date: 2026-10-22
- Status: Proposed
- Decision: Use SQLite initially, with repository boundaries for future Postgres migration.
- Rationale: Minimal local setup and sufficient for a single-instance demo.
- Consequences: Do not claim horizontal scalability. Move jobs to a durable queue before multi-instance production.

## Open questions
1. Is a live public deployment required for the internship evaluation, or is a local demo sufficient?
2. Which runtime environment must be supported first: Windows native, WSL, macOS or Linux?
3. Are there existing brand assets or visual references for AdForge AI?
4. Is the first deliverable expected to include actual generative video, or is a polished deterministic renderer acceptable?
5. Which hosting provider is available, and does it support FFmpeg and persistent storage?
6. Will any business data or generated output be private/sensitive, and what retention expectations apply?
7. What exact deadline date/time did the evaluator give?
