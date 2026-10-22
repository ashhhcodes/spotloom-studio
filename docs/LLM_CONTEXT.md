# LLM Context — AdForge AI

## Mission
Build an independent, portfolio-grade website-to-video ad creation product from scratch. It must also serve as a credible internship evaluation submission. Prioritize a reliable end-to-end MVP first, then improve quality and production readiness.

## One-line product description
Turn a business website or manually supplied business facts into a short, branded, downloadable MP4 ad using a traceable, fact-grounded AI workflow.

## Primary user flow
1. User submits a public website URL or chooses manual business details.
2. Backend validates the URL and extracts structured business facts and candidate images.
3. UI shows facts and allows correction/approval.
4. Creative engine generates a structured ad brief, script, scene plan and CTA.
5. Deterministic validators check factual claims and schema correctness.
6. Renderer creates an MP4 using images, motion, typography, optional audio and branding.
7. Output validator checks file integrity and required overlays.
8. UI shows progress, warnings, preview and download.

## Constraints
- First delivery target: one week.
- Use Codex as the primary coding agent; other agents may critique or review but must not silently create conflicting architecture.
- Keep all project context in Markdown in this folder.
- Do not start with microservices, Kubernetes, a custom video model, or multi-agent orchestration.
- The baseline workflow must work without paid API credentials.
- Do not make unsupported claims about quality, speed, accuracy, or security.
- Never store credentials in source control.
- Public URL fetching must be protected against SSRF; do not bypass CAPTCHA or access restrictions.
- Do not claim “hallucination-free”; use evidence, conservative rules, human review, and measurable evaluation.
- Do not use an external website's content or images in a way that violates access terms, copyright, or user permissions. The user is responsible for having rights to supplied assets; product guidance should be clear.

## Initial stack
Next.js + React + TypeScript + Tailwind CSS; FastAPI + Pydantic; HTTPX + BeautifulSoup; optional Playwright; SQLite; FFmpeg + Pillow; pytest and frontend checks.

## Core engineering principle
LLM output is untrusted input. LLMs suggest creative text and scene plans. Deterministic code owns validation, asset fetching, rendering, job state, quotas, file paths, and final artifact verification.

## Work instructions for any LLM
1. Read this file and the relevant specifications before editing.
2. Inspect the actual repository before assuming a feature is missing.
3. Propose a small plan and list files to change before large edits.
4. Implement one bounded milestone at a time.
5. Run the relevant tests and report exact commands/results.
6. Update docs and `DECISIONS.md` when behavior or architecture changes.
7. Do not fabricate test results, screenshots, benchmark numbers, or implementation status.
8. Keep a concise handoff note in `PROGRESS.md` (create it when implementation starts).
9. Do not begin coding while the user is still approving product/architecture specifications.
