# AdForge AI — Project Documentation Pack

> Independent website-to-video advertising studio. This repository contains product and engineering context, not application source code.

## How to use this folder

Read these files in order before implementing or handing work to another LLM:

1. `LLM_CONTEXT.md` — short, portable project brief and operating rules.
2. `PRD.md` — product requirements, personas, stories, scope and acceptance criteria.
3. `ARCHITECTURE.md` — system design and implementation boundaries.
4. `API_CONTRACTS.md` — proposed API contract and data shapes.
5. `AI_RELIABILITY_EVALUATION.md` — fact-grounding strategy, metrics and test dataset.
6. `SECURITY.md` — security requirements and threat model.
7. `ROADMAP.md` — seven-day delivery plan and release gates.
8. `DECISIONS.md` — decisions made, assumptions and open questions.
9. `DESIGN_SYSTEM.md` — frontend visual direction and UI principles.
10. `DEPLOYMENT_OPERATIONS.md` — local development, deployment and operations requirements.

## Source of truth

- This folder is the canonical planning context for the project.
- When a decision changes, update `DECISIONS.md` and the affected specification.
- Mark implementation status explicitly: `PLANNED`, `IN PROGRESS`, `IMPLEMENTED`, `VERIFIED`, or `DEFERRED`.
- Never claim a feature, test result, performance metric, deployment, or security property is complete until it has been demonstrated.
- Keep secrets out of Markdown, Git history, screenshots, logs, and examples.
- Do not copy another project's code or documentation. Use the shared Adsify description as product inspiration and a source of requirements only.

## Product summary

AdForge AI turns a public business website (or manually entered business details) into a short branded MP4 advertisement. The pipeline extracts business facts and media, creates a grounded creative brief, validates the output, renders a video with deterministic media tools, and exposes preview/download with clear status and warnings.

## Initial technical direction

- Frontend: Next.js, React, TypeScript, Tailwind CSS.
- Backend: Python, FastAPI, Pydantic.
- Extraction: HTTPX + BeautifulSoup; Playwright only where justified.
- AI: provider adapter with schema-constrained output where supported; deterministic fallback.
- Rendering: FFmpeg + Pillow; generated video-provider integration is optional and must be isolated behind an adapter.
- Persistence: SQLite for the first single-instance MVP; design repository interfaces so migration is possible.
- Testing: pytest, frontend lint/type checks, API integration tests, FFprobe-based media checks, browser smoke tests.
- Deployment: Docker-compatible, HTTPS in production, non-root containers, persistent artifact storage, explicit quotas and access control before public use.

## Critical product principle

The product must create a valid video without requiring a paid LLM or paid video API. Paid/provider-based generation may improve output but cannot be the only path through the demo.
