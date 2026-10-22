# Deployment and Operations

- Status: Proposed operational requirements
- First goal: reproducible local run; deploy only after the app is stable.

## 1. Environment configuration

Provide `.env.example` with placeholder values only. Expected categories:
- application environment and public base URLs
- database path/URL
- artifact directory and retention hours
- LLM provider name, base URL, model and secret key
- optional video provider configuration
- request limits, crawl limits and timeouts
- rate limits and generation caps
- CORS origins
- logging level

Never put secrets in `NEXT_PUBLIC_*` variables. The frontend should call the backend through a controlled API base URL or same-origin reverse proxy.

## 2. Local development
Document:
- supported Python and Node versions
- package manager and lockfile commands
- FFmpeg install and verification
- optional Playwright browser installation
- environment setup
- start commands for backend and frontend
- test commands
- how to run a fixture-based demo
- where artifacts are stored and how to clear them

## 3. Containers
If included:
- separate frontend and backend services
- non-root runtime users
- pinned image versions where practical
- health checks
- persistent volume for database and artifacts
- resource limits for renderer and browser
- no credentials in image layers
- internal-only backend network when possible
- avoid privileged mode

## 4. Public deployment gates
Before exposing publicly:
- HTTPS and restrictive proxy config.
- Authentication or trusted access proxy.
- Per-user or per-IP quotas.
- Generation concurrency and daily caps.
- Secure artifact authorization.
- Request body and upload limits.
- SSRF egress restrictions.
- Secrets injected through platform secret manager.
- Logs sanitized.
- Retention and deletion configured.
- Health/readiness endpoints checked.
- Rollback path documented.

## 5. Observability
Record:
- request ID and job ID
- job kind and current stage
- timestamps and stage duration
- provider name, not credentials
- retry count and fallback used
- outcome/error code
- artifact validation result

Do not log raw API keys, full HTML, full user uploads, or sensitive fields by default.

## 6. Health and recovery
- `/health` confirms process liveness.
- `/ready` checks critical dependencies.
- Startup should identify stale jobs and mark/reconcile them safely.
- Retention cleanup must not delete artifacts for active jobs.
- Backups are required if users depend on stored jobs; test restore, not only backup creation.

## 7. Deployment recommendation
For the first week, local reproducibility is mandatory and a live deployment is optional unless explicitly required by the evaluator. Do not expose an unauthenticated endpoint backed by paid generation keys. If the host does not support FFmpeg or persistent storage, choose a different host or keep rendering local for the demo.
