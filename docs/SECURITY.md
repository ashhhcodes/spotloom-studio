# Security Requirements and Threat Model

## 1. Threat model

AdForge AI accepts arbitrary URLs, untrusted website text, uploaded media, and optional external AI/video provider calls. Main risks:
- SSRF to internal services or cloud metadata endpoints.
- DNS rebinding and redirect-based SSRF.
- Browser-based fetches initiated by page scripts.
- Prompt injection inside scraped website content.
- Unsupported or deceptive business claims.
- Malicious/oversized uploads and decompression/resource exhaustion.
- Path traversal and unauthorized artifact access.
- Abuse of paid provider credits.
- Secret leakage through Git, logs, frontend bundles, or error messages.
- Denial of service via crawling, rendering, or excessive polling.

## 2. SSRF controls — P0

- Permit only `http` and `https`.
- Reject credentials embedded in URLs.
- Normalize and parse hosts carefully; reject malformed or ambiguous IP forms.
- Resolve DNS and reject loopback, private, link-local, multicast, reserved, unspecified, and metadata-service destinations.
- Revalidate the destination after every redirect and every DNS resolution.
- Bind the connection to the validated destination where the HTTP client allows it, reducing DNS rebinding risk.
- Limit redirects, connect/read timeouts, total fetch time, response bytes, crawl page count and crawl depth.
- Block non-web schemes such as `file:`, `ftp:`, `gopher:`, and custom schemes.
- Do not expose internal resolver errors or private IPs to users.
- Add network-level egress restrictions in deployment as defense in depth.
- Playwright can make subrequests independently; run it in a restricted environment with egress controls and no access to internal services.

Do not rely solely on a one-time DNS lookup or URL string checks.

## 3. Scraped content and prompt injection

- Treat all fetched HTML/text as untrusted data, never as system instructions.
- Extract a bounded, normalized fact sheet before calling an LLM.
- Keep instructions and data clearly separated in prompts.
- Do not allow website content to choose tools, API endpoints, local files, or provider credentials.
- LLM outputs must pass schema and business-rule validation.
- Do not rely on model self-reporting that a claim is grounded.
- Never send secrets or unnecessary personal data to a provider.

## 4. Upload and media controls

- Enforce request-size limits before full buffering.
- Validate file content and decode using trusted libraries.
- Generate storage IDs; do not use original filenames as paths.
- Restrict supported formats and media duration/dimensions.
- Use FFprobe/decoders in resource-limited processes.
- Store uploads outside executable/static source directories.
- Prevent arbitrary file path input in API routes.
- Avoid shell-string interpolation; pass subprocess arguments as arrays.
- Set render timeouts and memory/CPU limits.
- Do not automatically fetch arbitrary user-provided asset URLs without the same SSRF protections.

## 5. Secrets and provider usage

- Commit only `.env.example` placeholders.
- Keep `.env` in `.gitignore`.
- Never expose provider credentials through `NEXT_PUBLIC_*` variables or frontend responses.
- Use secret manager/environment injection in deployment.
- Rotate any credential that has been committed or shared.
- Set per-minute and per-day limits, concurrent-job limits, and provider spending caps where supported.
- Authenticate and authorize users before exposing paid provider credentials to a public app.
- Redact authorization headers, keys and tokens from logs.

## 6. Authentication and artifact access

For local development, access can be restricted to localhost. Before public deployment:
- Add authentication or place the app behind a trusted access proxy.
- Check authorization on every job, asset and artifact read/download.
- Use opaque IDs and avoid sequential identifiers.
- Prevent cross-user IDOR if accounts are added.
- Use signed, expiring object-storage URLs if using object storage.
- Apply a retention policy and deletion process.
- Configure secure cookies, CSRF protection where relevant, and restrictive CORS.

CORS is not authentication and does not prevent direct API abuse.

## 7. Logging and privacy

- Log request/job IDs, stage timings, outcome codes and sanitized provider errors.
- Avoid logging full website HTML, user uploads, phone numbers, tokens, or raw prompts by default.
- Document retention duration.
- Make deletion behavior predictable.
- Avoid sending full business pages to external providers when a smaller fact sheet is sufficient.

## 8. Deployment hardening

- HTTPS only.
- Non-root container user.
- Minimal base images and pinned dependencies where practical.
- No privileged containers.
- Read-only filesystem where possible; dedicated writable data volume.
- Egress/network restrictions for scraper and browser.
- Health/readiness endpoints with safe output.
- Rate limiting and request-size caps at proxy and app layers.
- Automated dependency scanning and secret scanning.
- Backups and restore test if user data becomes important.
- Review license and terms for any provider and scraped assets.

## 9. Security release gates

Do not call a public deployment production-ready until:
- SSRF tests cover direct private IPs, encoded IPs, redirects, DNS rebinding considerations, IPv6 and metadata targets.
- File uploads and artifact paths are validated.
- Provider secrets are absent from frontend bundles and logs.
- Authentication/access protection and quotas are in place.
- Render/crawl resource limits are enforced.
- Errors do not expose stack traces or sensitive infrastructure details.
