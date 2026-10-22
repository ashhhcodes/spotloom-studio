# Website extraction (Milestone 3)

The local scan CLI fetches at most one public page and returns deterministic, unreviewed fact candidates. It does not use a browser, execute page content, follow asset references, approve facts, or start creative generation/rendering.

## Fetch boundary

- Input must be an absolute `http` or `https` URL without credentials, a malformed host, or an invalid port. IP literals and every resolved hostname address must be globally routable. IPv4-mapped IPv6 addresses are checked as IPv4 too.
- DNS is resolved immediately before each request. Any non-public answer blocks the request. HTTPX automatic redirects, environment proxies, cookies, and browser state are disabled. Each redirect is resolved relative to the prior URL and independently validated before it can be requested; at most four redirects are followed.
- Each request has a 3-second connect timeout and an 8-second HTTPX timeout, with a 20-second total scan deadline. A response is limited to 1,000,000 bytes. Page content types are `text/html` and `application/xhtml+xml`; robots accepts `text/plain`, `text/html`, or `application/octet-stream`.
- The request User-Agent is `AdForgeAI/0.1 (local business website fact extractor)`. No authentication is supplied. Server errors and non-success HTTP statuses become safe errors.
- `/robots.txt` is fetched from the submitted origin before the page, through the same URL, redirect, timeout, and byte checks. It must return a parseable non-empty policy containing a `User-agent` directive and only recognized directives. A disallowed path, unavailable policy (including 404), malformed policy, or ambiguous policy fails closed and prevents the page request. Robots redirects are followed only after validating each redirect destination; cross-origin robots redirects fail closed.

### SSRF limitation

The hostname is checked immediately before HTTPX connects, but the normal HTTP stack resolves the hostname again for the connection. This leaves a DNS rebinding/time-of-check-to-time-of-use gap: application checks alone cannot guarantee the connection uses the validated IP. Do not expose this local CLI as a public service. A deployment needs network egress isolation or a hardened transport that pins the validated destination, plus defense-in-depth restrictions. No claim of complete SSRF protection is made.

## Extraction and fact review

Only the fetched HTML is parsed, using BeautifulSoup's built-in `html.parser`. Script, style, template, noscript, iframe, SVG, canvas, navigation, forms, hidden, and `aria-hidden` nodes are excluded from visible text. No referenced resources are fetched.

Deterministic precedence and evidence:

1. Business name: `og:site_name`, `application-name`, document title, then first `h1`.
2. Product/service description: `meta[name=description]`, `og:description`, then first non-empty paragraph.
3. Selling-point candidates: visible list items (deduplicated after whitespace normalization; at most three reach the existing model).
4. CTA candidates: visible text matching a small explicit phrase list (for example “Contact Us” or “Book Now”).
5. Contact: visible email and phone-shaped text; address: explicit `itemprop=streetAddress`; price: explicit product price metadata or a visible currency amount; offer: promotional `og:description` only when it contains explicit offer language.
6. Brand colors: valid `theme-color` metadata then six-digit hex colors in inline `style` attributes, at most two. External stylesheets and screenshots are not inspected.
7. Website: the final validated page URL.

Values are whitespace-normalized, capped at 240 characters, and facts are capped at 32. Identifiers are stable hashes of the source URL, field, and normalized value. Every fact records `source=website`, source URL, extraction method, and a bounded evidence snippet. The optional `FactProvenance.extraction_method` and `evidence` fields extend the existing Milestone 2 schema without changing manual/creative construction. All scan candidates begin in `unreviewed`; the creative generator continues to accept only approved facts. Extraction is literal and does not establish semantic truth. Page text is untrusted content and is never interpreted as instructions.

An empty or irrelevant page is `partial`, not success. Result statuses are `success`, `partial`, `blocked_by_policy`, `unsupported_content`, and `failed`. User-facing errors are short and do not contain stack traces or resolver details.

## CLI and offline tests

```powershell
python -m adforge_renderer.scan_cli https://example.com --output .\artifacts\example-scan.json
python -m pytest .\backend\tests -v
```

Exit codes: 0 success, 1 partial/no business facts, 2 policy rejection, 3 unsupported content, operational failure, or inability to write the requested output. Automated scanner tests use `httpx.MockTransport` with injected deterministic DNS answers and do not connect to public or arbitrary targets. The complete test suite also includes the existing renderer tests; its real FFmpeg/FFprobe test runs when both tools are on `PATH`.
