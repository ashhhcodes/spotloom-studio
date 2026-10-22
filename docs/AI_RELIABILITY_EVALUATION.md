# AI Reliability and Evaluation Plan

## 1. Purpose

Evaluate whether AdForge AI extracts relevant business information, produces grounded creative content, and renders a valid video. Do not describe the product as hallucination-proof.

## 2. Evidence model

Every business fact should carry:
- `field`
- `value`
- `source_kind`: `website`, `user`, `model_suggestion`
- `source_url` or null
- `extraction_method`
- `review_state`: `needs_review`, `approved`, `rejected`
- optional confidence score only if calibrated or clearly labeled heuristic

Source precedence:
1. User-confirmed value.
2. Website-extracted value with provenance.
3. Model-generated suggestion, which is not a verified business fact.

Conflicting values should be shown to the user rather than silently resolved when they materially affect the ad.

## 3. LLM output contract

Use a versioned structured schema with:
- hook
- objective
- tone
- scene array
- each scene's duration, visual direction, on-screen text and asset reference
- CTA text and destination
- optional negative prompt
- list of claims and the fact IDs supporting each claim

Treat all LLM output as untrusted. Parse schema, validate references, and reject unsupported high-risk claims. Limit repair attempts to one or another fixed small number; then use deterministic fallback.

Phone numbers, addresses, exact prices, guarantees and other critical factual strings should be injected as deterministic overlays from approved fields rather than generated into footage.

## 4. Evaluation dataset

Create a small, versioned dataset of approximately 10 labeled cases:
1. Conventional business website with complete details.
2. Restaurant/cafe site with several services and images.
3. Professional service site with clear contact page.
4. JavaScript-rendered site.
5. Website with missing phone/address.
6. Website with conflicting business descriptions.
7. Site with a promotion/price explicitly present.
8. Site with no offers, to verify none is invented.
9. Unreachable or timeout fixture.
10. Invalid/private-network URL, expected to be rejected safely.

Prefer controlled local fixtures for deterministic integration tests. For public websites, document when snapshots were captured and avoid depending on mutable content for core CI tests.

## 5. Metrics and initial targets

Targets are hypotheses for acceptance, not measured results.

### Extraction
- Field-level precision and recall for business name, description, phone, address, offer and services.
- Target: 100% correctness on critical fields in the labeled supported fixture set before claiming release readiness.
- Missing field must not be counted as a fabricated success.
- Record `unknown` separately from `incorrect`.

### Grounded creative
- Schema-valid output rate.
- Unsupported critical claim count.
- Claim-evidence coverage: percentage of material business claims linked to an approved fact or explicit user-provided input.
- Target: zero unsupported critical claims in the evaluation set; any violation is a release blocker until corrected or appropriately flagged.

### Video
- Valid MP4 rate among jobs marked completed.
- Dimensions and duration match requested configuration.
- Business name and CTA visible in the rendered composition.
- Font/encoding checks for supported scripts.
- Output can be opened and seeked.

### Reliability
- End-to-end success rate for supported fixtures.
- Correct handling of expected failures.
- Retry count and fallback frequency.
- Job state transitions and stale-job recovery.
- Target: at least 9/10 supported end-to-end cases is a stretch target; report actual denominator and exclude deliberately invalid/blocked cases only with an explicit reason.

### Performance
Record:
- scan time
- extraction time
- LLM latency
- render time
- total wall-clock time
- artifact size

Establish a baseline before optimizing. Do not advertise a latency SLA based on a handful of runs. If reporting p95, collect enough observations to make it meaningful.

## 6. Test layers

### Unit tests
- Fact precedence and provenance.
- Schema validation.
- Claim guard.
- Prompt construction and untrusted-data boundaries.
- URL normalization and IP classification.
- Duration/aspect-ratio calculations.
- File naming and path safety.
- Job state transitions.

### Integration tests
- Scan fixture → fact sheet.
- Approved fact sheet → deterministic creative.
- Creative → renderer → FFprobe verification.
- Invalid LLM output → fallback.
- Provider timeout → clear failure/fallback.
- Missing assets → useful warning.
- Cancelled job → terminal status.

### End-to-end tests
- Submit test URL through API/UI.
- Review facts.
- Generate creative.
- Render video.
- Preview/download.
- Confirm result survives refresh.

### Visual QA
- Inspect 9:16 and 16:9.
- Check text safe areas and contrast.
- Test long business names and missing optional fields.
- Test loading, error, partial scan and fallback states.

## 7. Reporting template

For every evaluation run, record:
- Git commit SHA.
- Dataset version.
- Environment and provider configuration (never secret values).
- Number of cases and expected outcomes.
- Pass/fail counts.
- Critical claim violations.
- Valid MP4 count.
- Stage timing distribution.
- Known limitations.
- Remediation items.

Never fabricate benchmark results. If the dataset is small, call it a smoke/evaluation suite rather than a statistically representative benchmark.
