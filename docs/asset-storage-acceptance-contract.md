# Provider-Neutral Asset Storage Acceptance Contract

**Status: proposed acceptance criteria; not a provider selection or implementation authorization.**

This document defines evidence required before a future storage adapter can be
accepted. It does not select a provider, claim that a storage service exists,
resolve an open policy decision, or authorize implementation. The authoritative
policy decisions remain in `docs/asset-trust-policy-decisions.md`.

## 1. Current boundary

The current `backend/adforge_renderer/asset_storage.py` defines
`ExactVersionObjectReader`, `observe_exact_version`, and typed missing/read
errors. The interface takes a `PrivateObjectVersionReference`, expects the
reader to return the exact version's complete `bytes`, and computes SHA-256
and byte count from those returned bytes. Its in-memory tests exercise interface
semantics only.

`PrivateObjectVersionReference` is an opaque, caller-constructible value. Its
type does not prove that a reference identifies an immutable object version,
that an object exists, or that access is private. `ExactVersionObservation` and
a matching digest do not authenticate a reader, establish provenance, authorize
access, or establish readiness. No provider-backed storage adapter or
authorization call path is implemented.

OD-10 (provider and immutable object-version guarantees) and OD-11 (SHA-256 and
byte-size verification) remain **OPEN — APPROVAL REQUIRED** for unresolved
provider, infrastructure, streaming, interruption, persistence, retry, and
production-integration details. This document does not resolve either entry.

## 2. Required adapter behavior

### 2.1 Explicit immutable-version retrieval

- Every read must receive one explicit opaque immutable-version reference. A
  missing reference, mutable object key, `latest`/current alias, or inferred
  version is invalid.
- The adapter must request that exact version from the provider. It must return
  bytes for that version or fail closed; it must never substitute a newer,
  current, or otherwise available version.
- Preserve the reference exactly across the application/provider boundary;
  do not trim, case-fold, decode/re-encode, or otherwise normalize it unless a
  provider-specific representation rule is separately approved and shown to be
  lossless and unambiguous.
- A successful read must identify the same provider version requested. If the
  provider cannot identify or retrieve that exact version, the asset version is
  unavailable for trusted use.

The current `ExactVersionObservation` echoes the requested opaque reference; it
does not report or independently verify the provider version actually read.
Provider-backed acceptance must capture provider response metadata or
equivalent instrumented integration evidence that ties the requested opaque
reference to the actual provider version returned. This evidence is not present
in the current local interface or fake tests. Keep the application reference
distinct from a provider's version identifier when they use different
representations.

Provider-backed immutability evidence must include a controlled test that
creates version A, writes or creates a newer/replacement version B, then reads
the explicit A reference and demonstrates that the returned bytes and provider
version identifier remain A. If A is no longer retrievable, the read must fail;
it must not return B. Tests must also attempt an overwrite or identity rebind
and show that it is rejected or creates a distinct immutable version.

This is distinct from an interface test. An in-memory fake can show that code
passes a requested key and does not choose a fallback in that fake. It cannot
prove that a provider adapter, provider configuration, or deployed credentials
preserve immutable-version semantics.

### 2.2 Authorization and private access

- A future protected application operation must authenticate its user and
  authorize project ownership before asking storage to read an asset. The
  identity and authorization contract is separate from storage access; an
  asset ID, project ID, opaque object reference, unguessable value, or digest is
  never a credential.
- Storage must remain private by default. User clients must not receive
  provider credentials or direct unauthenticated access to stored objects.
- Backend, validation-worker, and renderer access must use separately scoped,
  least-privilege service identities under the approved deployment design.
  Service credentials must not be interchangeable with user credentials.
- Unauthorized principals and unauthorized project/object combinations must
  be denied without returning object bytes, provider response bodies, or
  sensitive object metadata. Denial must fail closed.
- Authorization ownership and the exact approved principal-to-project check
  remain blocking decisions for protected integration. This document does not
  assign that ownership or define an identity provider contract.

Acceptance must include both application-level cross-project denial and
provider/deployment evidence that object access cannot bypass the trusted
backend boundary. A fake reader cannot establish either property.

### 2.3 Exact-byte integrity and bounded reads

- Compute SHA-256 and actual byte count from the complete byte sequence
  returned by the requested exact-version read. The count and digest must refer
  to the same bytes.
- A later read must be compared with trusted, previously recorded digest and
  byte count for that exact project, asset, immutable version, and validation
  attempt. Caller-provided expected values are not trusted evidence by
  themselves.
- A missing object, short/truncated/interrupted transfer, oversized object, or
  digest/size mismatch must yield no successful storage observation. Partial
  bytes or partial hashes must never be represented as a complete successful
  read.
- The adapter must establish that the transfer completed, including reaching
  the provider's completion/EOF signal and verifying an authoritative object
  length or equivalent completion signal. Hashing a returned prefix is not a
  complete read. If completeness cannot be established, fail without an
  observation.
- Media validity is a separate layer: malformed WAV or other media bytes may
  still be the complete bytes of an object. The appropriate media validator
  evaluates those bytes; malformed/unsupported media must not produce valid
  media-validation evidence or readiness, even if storage integrity observation
  succeeds.
- Production reads must be bounded before untrusted data can cause unbounded
  memory or work. The currently implemented interface returns a complete
  `bytes` value, so it alone does not demonstrate bounded streaming or a
  pre-allocation size check. Before production integration, an explicitly
  approved maximum object size and bounded-read strategy are required. The
  implementation must either establish an enforceable provider-side/object
  size bound before materialization or define and test a bounded streaming read
  path that hashes and counts incrementally and fails on limit excess or
  incomplete EOF.
- The maximum object size and any read-buffer/resource limits are
  **OPEN — APPROVAL REQUIRED**. No numeric production limit is established by
  this contract; provider documentation or infrastructure configuration alone
  does not approve a product limit.

A digest detects disagreement with a trusted expected digest. It does not
prove who created the object, that a particular validator inspected it, that a
reference is immutable, that a caller is authorized, or that the object remains
available.

### 2.4 Errors, retries, and privacy

The future adapter must map expected provider failures to a stable internal
error contract. At minimum, distinguish:

| Provider condition | Required internal behavior |
| --- | --- |
| Exact version missing or deleted | Return a sanitized unavailable/not-found failure; no fallback. |
| Access denied | Return a sanitized denial; expose no bytes or provider details. |
| Throttling | Return a typed retryable condition only if retry policy is approved; no implicit unbounded retry. |
| Timeout or interrupted read | Fail the observation; discard partial success and return a sanitized read failure. |
| Transient network/provider failure | Return a typed retryable condition only under approved retry/deadline rules. |
| Digest or byte-count mismatch | Fail closed with no observation; do not repair or substitute. |
| Unexpected programming error | Preserve as a distinguishable internal failure for operators; do not misclassify as missing data or silently suppress it. |

Externally visible messages must be fixed, bounded, and sanitized. Logs must
not contain credentials, signed URLs, raw asset bytes, untrusted filenames,
secret-bearing provider bodies, or unnecessary raw object references. Logs may
use a bounded correlation/reference identifier only under an approved privacy
and audit policy.

The current local helper converts only its documented not-found, read-error,
and `OSError` cases to result issues; unexpected exceptions propagate so
programming errors remain distinguishable. This is not an external error
boundary. A future adapter/service or job boundary must classify expected
provider failures, record a safe internal category without provider exception
text, and return only a sanitized external error. Unexpected exceptions may be
retained for protected diagnostics only under approved logging/redaction
controls; credentials, signed URLs, provider response bodies, and asset bytes
must not be exposed. No such adapter or service/job sanitization boundary is
implemented today.

Retry count, backoff, idempotency, operation deadline, cancellation behavior,
and which failures are retryable remain **OPEN — APPROVAL REQUIRED**. Do not
retry until those assumptions and the exact-version read semantics are defined.

### 2.5 Lifecycle and operations

Before production acceptance, document and verify provider/deployment behavior
for:

- Version retention and exact-version availability after replacement.
- Logical deletion versus physical deletion, including behavior when a pinned
  version is requested after deletion.
- Retention, backup/recovery, cleanup grace, and how deletion interacts with
  active leases/jobs.
- Durability and availability claims, including their authoritative evidence
  source; do not infer guarantees from a successful local test.
- Access logging, monitoring, alert ownership, incident response, and audit
  access/retention.
- Credential rotation, least-privilege scope, private-network/access controls,
  encryption/key-management configuration, and recovery procedures.

If a pinned version is deleted, expired, inaccessible, or otherwise unavailable,
the read fails closed. No newer version may be substituted. Whether a retained
version remains readable under an existing valid lease is governed by the
approved lifecycle and lease decisions, not by this adapter contract alone.

Retention duration, backup deletion, durability/availability targets,
operational ownership, monitoring, and deployment controls remain open where
the policy register marks them **OPEN — APPROVAL REQUIRED**.

## 3. Evidence and acceptance test matrix

The following test layers are separate and cannot substitute for one another.

| Requirement | Evidence layer | Proof required to pass |
| --- | --- | --- |
| Explicit A remains distinct after B is created | Interface test, then provider integration test | Fake: call uses A and digest matches A bytes, labeled local-only. Provider: record requested opaque reference and provider-returned version metadata; prove they bind to A and returned bytes are A, or fail without fallback. |
| No overwrite or identity rebind | Provider integration test | Attempt overwrite/rebind of A; provider rejects it or assigns a distinct version. Read A afterward and verify its actual provider identity and bytes are unchanged. |
| Unknown, missing, or deleted version | Interface test and provider integration test | No matching version returns a sanitized failure and no observation; never return another/current version. Deletion behavior must match approved retention policy. |
| Private access and project authorization | Application tests plus provider/deployment evidence | Cross-project and unauthorized user/service requests are denied; least-privilege backend access succeeds; no public/unmediated object access exists. |
| Digest and actual byte count | Interface test and provider integration test | Hash and count match known exact returned bytes. Matching expected values succeed; either mismatch yields no observation. Repeat with provider-returned exact-version bytes. |
| Transfer completion and truncation | Adapter/provider integration test | Verify authoritative length or provider completion/EOF signal. Truncated, interrupted, or partial reads yield no observation, even if the returned prefix has a valid digest. |
| Media validity | Media-validator tests, separate from storage tests | Complete bytes may yield a storage observation; malformed/unsupported WAV or other media yields no valid media-validation evidence/readiness. |
| Maximum size and bounded reads | Owner approval, adapter design review, and provider integration/resource test | Approve a maximum object size and bounded strategy first. Demonstrate rejection before unbounded materialization and bounded memory/work at and beyond the approved limit. |
| Read errors and provider error mapping | Adapter tests and provider integration tests | Map missing, denied, throttled, timeout, and transient failures to documented categories; no partial observation or provider details escape. Unexpected programming errors remain distinguishable internally and are sanitized at the service/job boundary. |
| Retry and deadline behavior | Owner approval plus adapter/job tests | After idempotency and deadline policy is approved, demonstrate only the approved retryable cases, bounded retries, cancellation/deadline handling, and no duplicate side effects. |
| Retention, deletion, durability, and availability | Infrastructure-owner evidence and deployment verification | Demonstrate configured behavior in the target deployment and document evidence source, limits, access logs, backup/recovery, and unavailable-version behavior. Do not infer these from fake tests. |
| Audit, monitoring, and incident response | Operations/security/privacy-owner evidence | Demonstrate approved redaction, access, retention, alerts, ownership, and response procedures without exposing credentials, signed URLs, provider bodies, or asset bytes. |

The existing `backend/tests/test_asset_storage.py` tests are interface tests
with an in-memory fake. The fake's duplicate-key behavior and exact-key lookup
are useful contract checks but are not provider integration or infrastructure
evidence. Provider-backed tests require an explicitly selected provider,
isolated test resources, approved credentials/configuration, and safe cleanup.

## 4. Decision and evidence gates

No storage adapter implementation should be treated as trusted or production
integrated until the applicable gates below are resolved. Unknown accountable
owners remain **TBD**; this document does not assign them.

| Gate | Current status / required decision | Proposed owner role (unconfirmed) | Evidence required before dependent implementation |
| --- | --- | --- | --- |
| Provider selection and immutable versions (OD-10) | **OPEN — APPROVAL REQUIRED**; no provider selected. | Infrastructure/storage owner — **TBD**; security reviewer — **TBD**. | Provider/configuration evidence for private exact-version reads, no overwrite/rebind, retention, deletion behavior, and target-deployment tests. |
| Digest and actual byte count (OD-11) | SHA-256/exact-byte policy direction is recorded; streaming, interruption, persistence, retry, and production integration remain **OPEN — APPROVAL REQUIRED**. | Backend/architecture owner — **TBD**; infrastructure/storage owner — **TBD**. | Bounded complete-read design, known-byte tests, partial-read failure tests, expected digest/size mismatch tests, and evidence binding to exact version/attempt. |
| Identity and project authorization | **OPEN — APPROVAL REQUIRED** for exact token contract, persistence, and enforcement details. | Identity/security owner — **TBD**; product owner — **TBD**. | Approved principal/project authorization boundary and negative cross-project access tests. |
| Private access and service identity (OD-17 and related decisions) | **OPEN — APPROVAL REQUIRED** for concrete controls and deployment proof. | Security/infrastructure owner — **TBD**. | Least-privilege service credentials, private access configuration, denied-access tests, rotation/custody and deployment evidence. |
| Size and resource bounds (OD-08/OD-09 and related policy) | Production limits remain **OPEN — APPROVAL REQUIRED**; development defaults are not production approvals. | Product and infrastructure/operations owners — **TBD**. | Approved byte/read limits and capacity/abuse review, plus proof of enforcement before materialization. |
| Retry/deadline/error policy | **OPEN — APPROVAL REQUIRED** where policy register requires owner input; exact mechanics not established here. | Operations/reliability and backend owners — **TBD**. | Approved deadlines, retry/idempotency rules, cancellation behavior, error mapping and bounded sanitized logs. |
| Retention, deletion, backups, leases (OD-12/OD-13/OD-14/OD-16) | **OPEN — APPROVAL REQUIRED** for durations, backup behavior, lease mechanics and deployment guarantees. | Product/privacy/legal, infrastructure, and operations owners — **TBD**. | Approved retention/deletion rules and race/recovery tests plus target-deployment evidence. |
| Audit, monitoring, incident response (OD-18 and related decisions) | **OPEN — APPROVAL REQUIRED** for privacy/legal and operational details. | Privacy/legal and operations/security owners — **TBD**. | Approved event scope, redaction/access/retention rules, monitoring ownership, incident and recovery procedures. |

This table summarizes gates; it does not replace or resolve the authoritative
decision matrix. OD-10 and OD-11 remain open, as do related decisions wherever
implementation or deployment evidence is outstanding.

## 5. Pre-integration acceptance checklist

- [ ] A provider and target deployment configuration are explicitly approved.
- [ ] Exact-version creation, replacement, read, and missing-version behavior
  pass provider-backed tests; no latest/current fallback exists.
- [ ] Authorization owner and server-side project check are approved and tested
  separately from storage service credentials.
- [ ] Storage is private and least privilege is demonstrated in the target
  deployment.
- [ ] Approved maximum object/read size is enforced before unbounded
  materialization; truncated and interrupted reads cannot succeed.
- [ ] SHA-256 and byte count are computed from the complete exact-version bytes
  and checked against trusted version-bound values on every required reread.
- [ ] Expected provider errors are mapped and sanitized; retry/deadline policy
  and unexpected-error handling are documented.
- [ ] Deletion, retention, backups, leases, audit, monitoring, and recovery
  requirements are approved and supported by evidence.
- [ ] Tests distinguish fake-reader contract behavior from provider integration
  and infrastructure guarantees.
- [ ] The resulting implementation has separately authorized code review and
  deployment approval; this document grants neither.

The `/scan` API remains unavailable. This contract adds no URL fetching,
storage implementation, endpoint, authentication, authorization, or renderer
integration.
