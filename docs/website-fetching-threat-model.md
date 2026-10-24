# Website Fetching Threat Model and Architecture Decision

**Status:** design proposal; no website-fetching HTTP endpoint or infrastructure is implemented.
**Decision:** **No-go** for exposing website scanning through the API in the current repository or in any deployment that cannot enforce the controls in this document.

## 1. Executive summary

The repository contains a local CLI scanner and a FastAPI application with `GET /health`, `POST /validate/preproduction`, and `POST /validate/production-package`. The validation routes do not expose website fetching; `POST /scan` is not registered. The scanner has useful URL checks, redirect checks, robots handling, response-size limits, and timeouts, but these do not establish a safe network boundary for an internet-facing service. In particular, it resolves and checks a hostname before asking HTTPX to connect by hostname; HTTPX then resolves again. A changed answer can therefore bypass the checked address (DNS rebinding/TOCTOU). There is no configured deployment egress isolation, service-level concurrency cap, or separate CPU/memory limit for synchronous HTML parsing.

Keep scanning CLI-only for local development. For a controlled demonstration, enable scanning only if the environment can enforce outbound network policy and isolate the fetcher from application data. For public or multi-user use, prefer an egress-restricted worker with destination enforcement at connection time, resource isolation, authentication/authorization, and operational controls. A separate fetch service can provide a stronger boundary where network policy is centrally enforceable, but is more operationally complex. Direct application-process fetching is not recommended for public exposure.

No endpoint should be implemented until the owner can demonstrate the enforcement boundary, agree on proposed limits, and pass the readiness checklist in §11. The architecture and suggested limits below are proposals, not current behavior or approved product requirements.

## 2. Verified current implementation

This section describes inspected code, not guarantees inferred from planning documents.

### API and invocation boundary

- `backend/adforge_renderer/api.py`: `app` disables docs and OpenAPI routes and defines `GET /health`, `POST /validate/preproduction`, and `POST /validate/production-package`; there is no `/scan` route. The CLI `main` defaults Uvicorn to `127.0.0.1:8000`; `_loopback_host` accepts `localhost` or a loopback IP only. This is a local launch guard, not a deployment firewall or authentication boundary. The app can be embedded by another process, so deployment exposure must be controlled separately.
- `backend/tests/test_api.py`: tests the liveness response, confirms it does not invoke network/subprocess services or return a test secret/path/traceback, confirms imports do not launch work, tests loopback startup validation, and asserts `/scan` GET and POST return 404. These tests establish behavior of the in-process app under test; they do not prove production routing or firewall policy.
- `backend/adforge_renderer/scan_cli.py`: `main` accepts a positional URL and required caller-selected `--output` path, runs `scan_website`, and writes serialized `ScanResult`. It is a local command, not an HTTP interface. The caller controls filesystem permissions and output path. It prints the chosen output path. No scan was run against an external site for this review.
- Dependencies in `backend/pyproject.toml` are pinned: Python `>=3.11,<3.12`, HTTPX `0.28.1`, BeautifulSoup `4.13.3`, FastAPI `0.115.12`, Uvicorn `0.34.0`, Pydantic `2.10.6`. Dependency pins aid reproducibility, not runtime isolation.

### URL parsing and destination checks

- `backend/adforge_renderer/website_scan.py`: `normalize_and_validate_url` requires a string no longer than 2,048 characters; accepts only HTTP/HTTPS; rejects missing authority, embedded username/password, invalid host syntax, backslashes/control/space characters in host, and ports outside 1–65,535. It lowercases the scheme and IDNA-encodes/lowercases the hostname, removes a trailing dot, defaults an empty path to `/`, preserves query, and removes fragments.
- IP literals are parsed by Python `ipaddress`; IPv4-mapped IPv6 is reduced to IPv4 by `_public_ip`. The current predicate requires `is_global` and rejects private, reserved, loopback, link-local, multicast, and unspecified addresses. Hostnames are resolved with `socket.getaddrinfo`; empty answers or any non-public answer reject the URL. The tests cover representative IPv4/IPv6 special ranges and a hostname with mixed public/private answers. They do not exhaust all parser/runtime/platform address interpretations.
- IDN normalization is tested for `BÜCHER.example`; this does not prove equivalence of every URL parser, proxy, resolver, or HTTP client interpretation. Ambiguous numeric host spellings and scoped IPv6-zone syntax are not an explicit accepted-input contract and are not comprehensively tested. A future service should reject ambiguous forms unless its entire parsing and connection stack has one verified interpretation.
- DNS preflight does not pin the socket destination. `SafeFetcher` passes a normalized hostname URL to HTTPX, which performs connection-time resolution separately. The tested resolver is injected and the tests use `httpx.MockTransport`; they cannot prove which address a real socket connects to. A DNS answer changing after validation remains a concrete bypass risk. No metadata-service address should ever be used in tests; private/link-local literals are tested locally without network access.
- The URL validator accepts any syntactically valid port from 1 to 65,535. It does not restrict ports to 80/443. Port reachability and allowed services are not separately controlled.
- `normalize_and_validate_url` returns generic policy/validation messages for expected failures. `scan_website` catches unexpected exceptions into a generic `scan_failed` result. However `ScanResult.original_url` is populated with the submitted string even on validation failure; a URL containing userinfo can therefore be echoed in CLI JSON. Do not reuse this object as a public response without redaction. No scanner logging framework is configured or exercised by tests.

### Requests, redirects, robots, TLS, and limits

- `SafeFetcher._request` validates each URL before each request, disables HTTPX automatic redirect following, and follows 301/302/303/307/308 manually via `urljoin`. It checks loops and allows at most `max_redirects` (default 4); each next destination is sent through URL validation before its request. This is useful defense in depth, but each check still has the DNS TOCTOU gap. It does not restrict redirect destinations to the original origin; a redirect to any destination that passes the same public-address policy can be requested.
- Before the page, `SafeFetcher.fetch` requests `/robots.txt` from the starting origin using the same request path, then requires a nonempty parseable policy with recognized directives and checks `RobotFileParser.can_fetch`. It fails closed if robots is unavailable/disallowed. It compares the final robots response origin with the original origin only after `_request` has followed redirects and fetched that response. Thus a cross-origin public robots redirect can be contacted before the later same-origin check rejects the scan. Private destinations are still subject to the per-hop address check (with the same DNS gap). This ordering should be changed or constrained before service exposure.
- HTTPX is instantiated with `follow_redirects=False`, `trust_env=False`, and `timeout=httpx.Timeout(8, connect=3)`. No cookies, credentials, or browser state are supplied. HTTPX's default TLS certificate verification is in effect because the code does not set `verify=False` or a custom TLS context. There is no dedicated TLS-failure regression test. HTTPX verification is a library default, not a separately configured pinning policy.
- `asyncio.timeout(20)` in `scan_website` wraps `fetcher.fetch`, including robots and page network work. It ends before `extract_facts` runs. HTTPX's 8-second timeout and 3-second connect timeout apply to individual request operations; they are not an end-to-end parse deadline.
- `MAX_BODY_BYTES` is 1,000,000 bytes per response. Declared `Content-Length` above the limit is rejected, and the accumulated `response.aiter_bytes()` output is counted before joining. HTTPX `aiter_bytes()` yields decoded bytes, so a compressed response is bounded by decoded size as accumulated; a small compressed stream can still consume decompression CPU before the cap is reached. Compression ratio, decompression CPU, and aggregate bytes over robots plus page/redirect responses have no separate budget. The body is then held in memory.
- Page responses allow `text/html` and `application/xhtml+xml`; robots responses allow `text/plain`, `text/html`, and `application/octet-stream`. Unsupported types fail. Content-Type is checked as a header, not by file-signature validation. Malformed/missing content-type fails as unsupported. No charset allowlist is applied.
- Up to 4 redirects are followed per `_request`; the scanner makes a robots request and then a page request, each potentially redirecting. The total timeout limits network duration, but no aggregate outbound-request counter independent of redirect settings exists.
- `extract_facts` uses synchronous `BeautifulSoup(html, "html.parser")`; it removes selected element classes, extracts literal values and caps result facts at 32. It calls `soup.get_text()` before clipping normalized text to 20,000 characters. Thus the 20,000-character text limit is not a limit on bytes parsed, DOM node count, nesting, parser CPU, or peak memory. Parsing is synchronous and cannot be preempted by the async fetch timeout. There are no process CPU/memory quotas, parser worker isolation, or concurrency controls.
- No request rate limit, job queue, cancellation contract, per-user quota, or service concurrency semaphore is configured. Multiple CLI processes can run independently; the local CLI is not a concurrency-control mechanism.

### Extraction, provenance, and approval

- `extract_facts` in `website_scan.py` extracts literal values and stores website source URL, method, and a bounded evidence string in `BusinessFact.provenance`. It does not execute page scripts, fetch assets, or establish truth. Page text remains attacker-controlled; the test explicitly demonstrates that instruction-like text may be preserved as literal business copy, so downstream systems must treat it as untrusted data.
- Every extracted candidate is `ReviewState.UNREVIEWED`. Backend `BusinessFacts` review transitions and `generate_creative` use approved facts, but approval is a human workflow status and not independent verification (`backend/adforge_renderer/facts.py`, `backend/adforge_renderer/creative.py`). Extraction, provenance, human approval, and factual verification must remain separate concepts.

## 3. Threat model

### Assets to protect

- Cloud or host control planes, metadata endpoints, internal services, loopback services, private networks, and other tenants' infrastructure.
- Application credentials, environment variables, source code, local files, databases, worker credentials, and service-to-service identities.
- Availability and cost of the API, worker, DNS, network egress, parser, memory, CPU, and outbound bandwidth.
- User-submitted business URLs, page content, extracted evidence, project data, and any credentials accidentally embedded in input.
- Integrity of source provenance, candidate facts, review state, generated copy, and audit records.
- Internal topology, filesystem paths, resolver details, stack traces, and secrets in responses or logs.

### Attacker capabilities and trust boundaries

Assume a caller can submit arbitrary strings and control the content and behavior of a public website they operate. The site can return redirects, slow/partial/chunked data, misleading content types, compressed payloads, malformed or adversarial HTML, and instruction-like text. It may change DNS answers over time or return different answers by resolver, client, or query. A caller may submit repeated or concurrent scans if a future service permits it.

The browser/client and submitted URL are untrusted. Public DNS, page contents, redirect locations, response headers, and extracted text are untrusted. The API process, worker, internal network, cloud metadata, filesystem, credentials, and other projects are protected boundaries. An egress gateway/policy enforcement point (if introduced) is a security boundary and must be tested and monitored. Robots directives are a crawler-policy input, not an SSRF control or authorization mechanism.

Primary threats are SSRF/DNS rebinding, redirect abuse, parser/decompression resource exhaustion, concurrency/cost exhaustion, sensitive URL reflection, error/log disclosure, and downstream prompt/content injection. TLS verification protects server identity in transit but does not make returned content trustworthy. Authentication and project authorization are currently absent and must be designed before multi-user use.

## 4. Architecture comparison

These are candidate designs, not implemented components. A container alone is not an egress policy: the host/network must deny private, loopback, link-local, reserved, metadata, and internal destinations at the actual connection path, including IPv4/IPv6 and alternate routes. Policy must account for DNS, proxies, NAT, service mesh, and redirects.

| Dimension | A. Egress-restricted worker | B. Controlled outbound-fetch service | C. Direct API-process fetching |
| --- | --- | --- | --- |
| Shape | API submits a bounded scan job to a separate worker/process; worker fetches under network and OS limits. | API requests a narrow operation from a dedicated fetch service; fetch service owns URL policy, DNS/connection enforcement, and egress. It returns bounded bytes or structured scan output. | API process uses application-level URL validation and HTTP client to fetch pages itself. |
| SSRF/rebinding | Strong when the worker has enforceable egress denies and binds each checked destination to connection, including each redirect. Defense in depth still required. | Potentially strongest central policy point if the service's network path enforces destination rules and its connection logic revalidates/pins every hop. A service with ordinary preflight DNS followed by hostname fetch has the same flaw. | Weakest boundary. Application checks alone cannot prevent DNS changes between validation and connection. Requires a hardened pinned transport plus an external egress boundary to be considered. |
| Redirect handling | Worker must own redirect handling, disable automatic redirects, and apply policy to every hop. Network policy must block prohibited destinations even if application validation fails. | Fetch service must validate every redirect and enforce policy at connection time. API should not fetch redirected URLs itself. | More complex to get right in-process; per-hop checks still vulnerable without address pinning and egress restrictions. |
| Isolation/failure containment | Separate OS/process identity, filesystem permissions, CPU/memory/time limits, and network policy can contain parser/fetch failures. Queue/process lifecycle adds operational work. | Strong central enforcement and policy reuse; service compromise/outage affects all callers unless isolated and quota controlled. Returned HTML still needs safe bounded parsing or untrusted parsing in a worker. | Shares process memory, credentials, event loop, and failure domain with API. A parser hang or resource attack can degrade API service. |
| Complexity | Moderate implementation; moderate operational burden for worker lifecycle, queue, patching, monitoring, and network rules. | Highest service/deployment complexity: another authenticated service, network path, service identity, availability, versioned contract, quotas, and central policy. | Lowest initial code complexity, but unacceptable security/operational trade-offs for a public multi-user API. |
| Resource controls | Natural place for process CPU/memory/FD limits, task concurrency, deadlines, bounded queue, and kill-on-timeout. | Can enforce centralized request/body/deadline/concurrency quotas; parsing may be kept separate from network fetching. | Requires in-process semaphore/timeouts plus separate process isolation to make synchronous parser work containable. Async timeouts alone do not preempt sync parsing. |
| Windows development | Keep current CLI for local workflow; optionally run a local isolated worker only if its security limits are explicit. Windows Firewall or a local policy may help but does not emulate cloud egress guarantees automatically. | Usually requires a separately run service or a managed endpoint; less convenient for a single-developer Windows setup. | Convenient for local tests, but convenience must not be confused with production safety. Existing API does not do this. |
| Best fit | Recommended baseline for a portfolio project moving toward controlled demonstrations or production, provided enforceable egress and process isolation exist. | Appropriate when multiple applications need one centrally governed outbound-fetch boundary and an operator can maintain it. | Acceptable only as a local non-exposed experiment, or with equivalent enforceable protections that remove its normal direct-egress risk; not recommended here for public exposure. |
| Tests/residual risk | Mock policy tests plus isolated integration and deployment firewall tests. Egress policy misconfiguration, worker vulnerabilities, DNS/TLS issues, and untrusted content remain risks. | Contract tests, isolated integration tests, policy service tests, and deployment path verification. Service compromise, policy drift, availability, and content risks remain. | Unit tests can verify code paths but cannot establish network egress safety. A missed parser edge, client behavior change, or bypass remains in the API failure domain. |

## 5. Recommended phased architecture

### Phase 0: current local development

Keep `adforge-scan` as an explicitly local CLI for trusted developer use and mocked tests. The API currently exposes `/health`, `/validate/preproduction`, and `/validate/production-package`; keep website scanning unavailable because `/scan` is not registered. Do not run scans against internal destinations or use real external targets for security tests. Local developer consent to invoke the CLI is not an isolation boundary; output files and logs remain the developer's responsibility.

### Phase 1: controlled demonstration

Only consider a demo scan flow after a separate worker or fetch boundary is available and the demo environment can enforce outbound network restrictions at the network layer. The worker should have no access to application secrets or arbitrary filesystem paths, run with a constrained identity, and apply per-job resource limits. Use synthetic/test domains in a controlled environment, and make the feature opt-in. If the host cannot enforce and verify egress policy or address pinning, scanning remains disabled; a local Windows dev run does not demonstrate cloud safety.

### Phase 2: public/multi-user production

Prefer architecture A initially: a queue or narrow authenticated local service dispatches work to a separate egress-restricted worker. The worker should make outbound connections only through an enforcement point that blocks private/internal destinations and binds each request to an approved public destination; redirects must be re-authorized at each hop. Isolate parser work with CPU/memory/time quotas and enforce global and per-user concurrency/rate controls. The API must authenticate and authorize project ownership, validate request size, and return only a bounded, sanitized operation result. The frontend must never directly fetch arbitrary business URLs.

Architecture B is a valid later choice if a central outbound-fetch service is operationally justified and can enforce the same contract. It must not merely centralize the current HTTPX flow. Architecture C is not the public-production recommendation.

The future API should enqueue or dispatch a scan operation and return a job/result reference through a versioned contract; it should not directly expose the scanner CLI. The worker/fetch service response should be typed and bounded, with unreviewed candidates and provenance. This is a communication pattern proposal only: there is no implemented `/scan`, queue, worker, fetch service, or job API in the repository.

## 6. Future security contract (testable requirements)

The following are acceptance requirements for a future implementation. Where numerical values are suggested, they are explicitly proposed starting points requiring confirmation against deployment, user experience, and resource budgets.

### URL and destination policy

1. Accept absolute `http` and `https` only. Canonicalize scheme/host consistently; reject credentials, control characters, backslashes, invalid/empty hosts, malformed ports, scoped IPv6 zones, ambiguous numeric address spellings, and parser-differential forms. Preserve the user-visible submitted value only in a redacted form; strip fragments and define default-port normalization.
2. Restrict ports to an explicitly approved set. **Proposed starting set:** 80 and 443 only, unless a documented product requirement justifies more. This is a proposal, not current policy.
3. Resolve all A/AAAA answers using the resolver policy that the connection will honor. Reject if any answer is not globally routable, including private, loopback, link-local, multicast, reserved, unspecified, IPv4-mapped IPv6, metadata/control-plane ranges, and organization-specific internal ranges. Maintain explicit IPv4 and IPv6 policy tests.
4. Close DNS rebinding/TOCTOU: the actual socket destination must be the address that was validated, while preserving correct Host header and TLS SNI/certificate hostname validation. Alternatively, enforce a network egress layer that independently blocks prohibited destinations at connection time. DNS preflight followed by ordinary hostname resolution is insufficient. Test the actual connection path, not just a resolver mock.
5. Revalidate every redirect destination and bind its connection independently. Disable automatic redirects. Set a strict maximum redirect count and reject loops. **Proposed starting value:** 3 redirects, pending product confirmation. Prefer same-origin redirects by default; any cross-origin redirect must be an explicit policy decision and must not carry credentials or sensitive headers.
6. TLS certificate chain and hostname verification must remain enabled. Reject invalid certificates; do not silently fall back to plaintext or disable verification. Do not forward user credentials, cookies, proxy authorization, or internal headers.

### Time, bytes, parsing, and concurrency

7. Set connect, read-idle, and wall-clock deadlines. A total deadline must include DNS, robots, all redirects, body transfer, decompression, parsing, and result serialization, enforced by a process-level timeout when synchronous code cannot be safely interrupted.
8. Enforce a maximum response size while streaming, after decompression, before buffering; cap both compressed transfer and decoded output. Also cap aggregate bytes across robots and page responses. Avoid unbounded joins/buffers.
9. Accept only documented content types and reject missing/malformed types; define whether content sniffing is used. Do not execute scripts or fetch secondary resources. Reject unsupported encodings and malformed documents safely.
10. Parse in an isolated worker/process with CPU, memory, wall-clock, and process limits. Bound DOM nodes/depth or use a parser with documented complexity behavior; truncate input before expensive parse only if truncation semantics remain explicit. Do not rely on async cancellation to stop synchronous parser work.
11. Apply global and per-user concurrency/rate limits and a bounded queue. Define queue saturation behavior, cancellation, job expiry, retry policy, and idempotency. **Proposed starting values for evaluation only:** 2 concurrent fetches per worker, 10 queued jobs per user, and one scan request per user per minute. These values require workload confirmation and are not agreed requirements.
12. Do not infer that a 20-second network deadline or 1 MB response cap is sufficient for service exposure. Current values are CLI implementation constants, not approved service budgets.

### Safe results, provenance, and approvals

13. Map internal failures to stable machine-readable codes and safe client messages. Never return raw exception text, stack traces, resolver results, internal IPs, filesystem paths, credentials, or submitted userinfo. Redact URLs in application, proxy, tracing, and access logs; avoid logging full query strings by default. Correlation IDs must be opaque and non-secret.
14. Treat URL, headers, HTML, extracted text, and evidence as untrusted. Return only bounded fields and evidence. Provenance should identify source URL, final page URL, extraction method/version, and capture time as appropriate, with a retention policy. Do not fetch linked assets.
15. Every extracted fact remains `unreviewed`. Extraction does not verify truth; human approval is a separate explicit transition, and a correction invalidates approval while preserving history. Rejected facts must not be promoted to positive claims. Server-side generation must recompute fact eligibility.
16. Health checks should reveal only service health/dependency readiness required by operators, not secrets, environment, internal routes, resolver answers, raw URLs, or user content. Operational metrics may include counts, latency buckets, rejection categories, byte totals, timeout and queue saturation totals; avoid high-cardinality labels and URLs.
17. Fail closed if egress policy, destination pinning, TLS validation, resource limiting, or required policy service is unavailable or cannot be verified. Do not offer a permissive fallback.

## 7. Adversarial test plan

All local tests must use mock transports, stub resolvers, synthetic fixtures, or isolated controlled hosts. Never send probes to real cloud metadata endpoints, production internal services, or arbitrary real websites. A passing unit test is not deployment evidence for firewall or socket-destination guarantees.

| Case | Setup | Expected safe behavior | Guarantee evidenced | Test level |
| --- | --- | --- | --- | --- |
| Malformed URL / unsupported scheme | Property/parameter cases: missing authority, control chars, backslash, overlong input, `file:`, `ftp:`, malformed IPv6 brackets. | Reject before network request with generic code/message. | Parser rejects known malformed inputs; no external request in mocked test. | Local unit/mock |
| Credentials and unusual ports | User/password, empty userinfo, encoded userinfo, port 0/out of range, approved and unapproved valid ports. | Reject userinfo and disallowed ports; errors/logs do not echo secrets. | URL policy and response/log redaction. | Local unit; log integration |
| IDN and ambiguous numeric hosts | Unicode/punycode equivalence; integer/octal/hex/short IPv4-like host forms; trailing dot; scoped IPv6. | One canonical interpretation or reject ambiguous input before connect. | Parser/connection stack agreement for enumerated cases. | Local unit plus client integration |
| IPv4/IPv6 edge destinations | Literal and resolver-answer fixtures for RFC1918, loopback, link-local, multicast, reserved, unspecified, CGNAT, documentation, IPv4-mapped IPv6, metadata ranges represented as fixtures only. | Reject all prohibited answers; do not open a socket. | Address-policy behavior for test matrix. | Local unit/mock |
| DNS changes between check and connect | Controlled resolver returns public then private; instrumented connection transport records destination; include public-to-public changes. | Connection uses the validated address or an egress control blocks the changed prohibited destination; fail closed. | Actual connection-time binding/egress enforcement (mock alone is insufficient). | Isolated integration + deployment-level verification |
| Public hostname resolves to prohibited address | Stub DNS returns any mixed public/private A/AAAA answers and empty/error answers. | Reject if any prohibited answer, no answers, or required resolver unavailable. | All-answer policy and fail-closed resolver behavior. | Local unit/mock |
| Redirect to disallowed address | Mock public response redirects to private, loopback, link-local, or disallowed port; no request handler for prohibited target. | Reject before target request; automatic redirects disabled. | Per-hop validation at application layer. | Local mock; socket-boundary test separately |
| Cross-origin redirect / robots redirect | Robots response redirects to a different public origin; page response cross-origin redirect. | Apply explicit origin policy; under proposed default reject cross-origin before contacting target. | Redirect origin policy and no unintended target request. | Local mock |
| Redirect loop/excess | Loop and chain over limit. | Stop with stable policy result within request cap. | Loop detection and maximum request count. | Local mock |
| Oversized body | Missing/false/large `Content-Length`, many chunks exceed wire and decoded caps; aggregate robots+page exceed budget. | Abort streaming and release resources; no unbounded buffering. | Streamed/aggregate byte budget. | Local mock; compressed integration |
| Compressed/decompression bomb | Synthetic gzip/br payload with small encoded size but large decoded output, malformed stream, unsupported encoding. | Enforce both transfer and decompressed caps; terminate within CPU/time budget. | Decompression/resource behavior. | Local mock plus isolated resource-limited integration |
| Malformed/unsupported content type | Missing, invalid, misleading header; binary body; HTML under unsupported type. | Reject as unsupported without parsing; safe error. | Declared content policy. | Local mock |
| Slow/partial response | Mock delayed headers/chunks, stalled body, slow DNS; exercise connect, read-idle, and total deadlines. | Terminate within configured deadline, release socket/process, report safe timeout. | Individual and whole-operation timeout handling. | Local async mock; isolated network integration |
| Parser resource exhaustion | Deep nesting, huge node count, pathological malformed HTML, many entities/long attributes within allowed bytes. | Isolated parser hits CPU/memory/deadline cap and is killed without affecting API; returns safe failure. | Failure containment for parser work. | Isolated process integration; deployment limit verification |
| Concurrent requests/rate limits | Saturate worker slots and per-user/global queue with synthetic jobs. | Enforce quotas, bounded queue, predictable overload response, no unbounded task growth. | Service concurrency/rate control. | Local service integration; load/deployment test |
| TLS verification failure | Local test CA/host mismatch/expired cert in controlled test server. | Reject connection; never disable verification or retry plaintext. | TLS verification path. | Isolated integration |
| Secret redaction | Submit URLs containing username/password/token query; inject resolver and HTTP exceptions with sentinel secrets/paths. Inspect response, logs, tracing fields. | No secret, raw credentials, stack, path, or internal address in exposed output. | Redaction across all observable sinks tested. | Unit + log/HTTP integration |
| Provenance and approval separation | Extract synthetic HTML containing literal claims; serialize result and attempt downstream eligibility. | Preserve bounded source/method/evidence; candidates stay unreviewed; no verification assertion. | Provenance preservation and approval-state boundary. | Local unit/contract |
| Missing/misconfigured egress enforcement | Start worker in isolated environment with policy absent, bypassed, IPv6 open, proxy route open, or metadata range blocked. | Startup/readiness fails or all scans fail closed; never silently fetch directly. | Egress controls apply to actual traffic and fail closed. | Deployment-level only |

## 8. Deployment and observability considerations

- Put the worker on a network segment whose egress rules are explicit and independently verified for IPv4 and IPv6. Deny private, loopback, link-local, metadata/control-plane, organization, and service ranges at the enforcement point. Permit only the intended public-web path; account for DNS, NAT, proxy, service mesh, and alternate interfaces. A container without host/network policy does not satisfy this requirement.
- Separate worker identity and filesystem from the API. Mount no application secrets unless absolutely required; do not provide arbitrary output paths. Use ephemeral work directories, least privilege, read-only roots where practical, and cleanup on completion/failure.
- Bound workers, queue, concurrency, CPU, memory, open files, outbound bandwidth, bytes, deadlines, and retries. Ensure worker termination actually stops outstanding sockets and parser work.
- Authenticate API clients, authorize project ownership, and separately authorize scan, review, generation, and rendering actions. Define consent, retention, deletion, jurisdiction, and privacy expectations before accepting real business content.
- Record only operationally necessary events. Useful metrics include policy rejection category, request duration bucket, byte bucket, worker saturation, queue depth, timeout count, parser failure count, and worker restart count. Do not label metrics with full URL, hostname, query, business name, or user ID unless protected/aggregated policy explicitly allows it.
- Health/liveness must not perform arbitrary outbound fetches. Readiness can report whether mandatory policy configuration is loaded without returning its details. Alert on unexpected egress denials, policy bypass indicators, parser timeouts, queue saturation, and repeated TLS failures.
- Verify network policy using controlled test infrastructure and packet/flow observation. Document the tested deployment revision and IPv4/IPv6 routes. Unit tests cannot establish cloud firewall behavior.

## 9. Residual risks and open decisions

Even with egress isolation, a public website can return misleading or malicious content, abuse allowed public destinations, change content between scans, or exploit parser/TLS/client bugs. Extraction remains an untrusted-candidate workflow. A public domain may host user-controlled content or proxy/tunnel services; destination allow/deny policy alone does not establish content safety. Human approval does not prove factual truth. TLS verifies a certificate identity under the trust store, not business claims. Rate limits and resource limits reduce but do not eliminate availability/cost risk.

Before implementation, decide:

1. Which environment and operator own network egress policy and its verification?
2. Is destination pinning required, or will a forced egress proxy/firewall enforce destination policy at connection time? How are redirects handled there?
3. Is cross-origin redirect allowed? Is robots policy mandatory, and must its redirects remain same-origin before any redirected request is made?
4. What URL ports, public address exceptions, domain policy, and IPv6 behavior are acceptable?
5. Which proposed byte, redirect, timeout, parser, concurrency, and rate limits fit real workloads?
6. Is content returned to the API as bounded HTML for isolated parsing, or are structured candidates returned by the worker? Which service identity authenticates that channel?
7. What authentication, project ownership, user consent, retention, deletion, and audit model applies?
8. What response schema and safe error mapping is versioned and tested? What is the URL redaction policy for access logs and traces?
9. How are worker patching, vulnerability response, policy drift, availability, and cost operated?

## 10. Readiness checklist before authorizing implementation

- [ ] Threat owner and deployment owner are identified.
- [ ] Egress boundary is implemented outside application URL checks and verified for IPv4 and IPv6.
- [ ] Destination is pinned to the validated address or a forced egress control independently blocks prohibited destinations at connection time.
- [ ] Redirects are manual, bounded, and destination policy is re-applied before every connection; robots cross-origin handling cannot contact a forbidden origin before rejection.
- [ ] TLS verification and host identity checks are tested; no fallback disables verification.
- [ ] Proposed URL, port, byte, aggregate-byte, timeout, redirect, parser, concurrency, rate, and queue limits are confirmed and enforced.
- [ ] Parser runs under enforceable CPU, memory, and wall-clock limits in a separate failure domain.
- [ ] Errors, URLs, logs, traces, and metrics have tested secret/path/internal-address redaction.
- [ ] Authentication, authorization, user consent, retention, deletion, and project ownership are defined.
- [ ] Adversarial unit, mocked, isolated integration, and deployment-level egress tests pass; the guarantee tested at each layer is documented.
- [ ] Provenance is preserved; extracted facts remain unreviewed until explicit human review; no approval implies independent verification.
- [ ] Operational monitoring, incident response, policy drift checks, and safe shutdown/fail-closed behavior are owned.
- [ ] API contract and frontend behavior are versioned and tested. No scan endpoint is enabled before the preceding items are complete.

## 11. Evidence reviewed

Implementation and tests inspected: `backend/adforge_renderer/website_scan.py` (`normalize_and_validate_url`, `_public_ip`, `SafeFetcher._request`, `SafeFetcher.fetch`, `extract_facts`, `scan_website`, `ScanResult`); `backend/adforge_renderer/scan_cli.py` (`main`); `backend/adforge_renderer/api.py` (`app`, `health`, `_loopback_host`, `main`); `backend/adforge_renderer/facts.py`; `backend/adforge_renderer/creative.py`; `backend/tests/test_website_scan.py`; `backend/tests/test_api.py`; and `backend/pyproject.toml`.

Documentation inspected: `backend/README.md`, `backend/WEBSITE_EXTRACTION.md`, `docs/integration-contract.md`, plus the relevant `.gitignore` rules. The integration contract and architecture documents contain proposals and examples; they were not treated as evidence that routes, workers, or infrastructure exist.
