# Trusted Asset Pipeline — Architecture Proposal

**Status: proposal for review; not implementation authorization.** This document
distinguishes current pure code from proposed trust boundaries. It does not
select a storage provider, production limit, retention period, or deployment
topology. Individual-user, owner-only v1 tenancy, Clerk selection, and the
canonical internal user ID direction are approved policy only; exact token
validation and implementation details remain open. Items marked
**OPEN — APPROVAL REQUIRED** remain gates. The repository has an existing
local website-extraction implementation in
`backend/adforge_renderer/website_scan.py` and `scan_cli.py`; the API route
`/scan` is not registered and remains unavailable. This proposal adds no URL
fetching or scanner capability. The existing CLI has a documented DNS
rebinding/TOCTOU gap and is not safe to expose publicly; see
`backend/WEBSITE_EXTRACTION.md` and `docs/website-fetching-threat-model.md`.

## 1. Existing foundation and limits

- `backend/adforge_renderer/asset_contract.py` defines project-bound asset
  declarations, immutable version-shaped records, lifecycle states, evidence
  shapes, CAS preconditions, and lease shapes. Those Python/Pydantic objects
  are caller-constructible and do not persist state or prove trust.
- `backend/adforge_renderer/asset_resolution.py` matches an exact
  `VersionedRenderPlan` against caller-supplied asset records and returns an
  all-or-nothing snapshot. It does not authenticate records, authorize a
  project, access storage, or prove bytes exist or were inspected.
- `backend/adforge_renderer/wav_validation.py:validate_wav_bytes` parses
  bounded immutable in-memory bytes for a narrow WAV profile. It returns byte
  size and observed properties only. Its 25 MiB and 60-second defaults are
  provisional development defaults, not production limits. The parser is not
  connected to storage or evidence issuance; its chunk compatibility is
  recorded as a proposal in `docs/wav-compatibility-matrix.md`.
- `backend/adforge_renderer/production_package.py` defines strict v1 and v2
  package contracts. V2 has a package `projectId`, immutable `assetVersionId`
  declarations, and package-local segment references by `assetId`.
- `backend/adforge_renderer/render_plan.py:compile_render_plan` is the legacy
  v1 compiler; `compile_versioned_render_plan` compiles v2 into a plan carrying
  project and version pins. No renderer consumes a trusted asset-resolution
  result or lease today.
- `backend/adforge_renderer/api.py` registers `/health`,
  `/validate/preproduction`, and `/validate/production-package`; it has no
  authenticated asset, upload, or render route. `backend/tests/test_api.py`
  asserts GET and POST `/scan` return 404.
- `docs/asset-trust-policy-decisions.md` contains approved directions and open
  decisions. In particular, project-bound immutable versions, exact-version
  resolution, trusted byte validation, CAS acceptance, logical deletion
  blocking new use, and valid existing lease behavior are approved directions;
  their implementation and necessary operational details remain pending.

## 2. Proposed trust boundaries

### Identity and project authorization

**Proposed:** authenticate at a future user-facing API boundary, then authorize
the principal against the project before creating, listing, reading, deleting,
resolving, or rendering an asset. Perform authorization server-side on every
operation, including job submission; do not infer it from `projectId`, `assetId`,
`assetVersionId`, or a package. Keep assets project-bound and cross-project
sharing disabled, consistent with the existing approved direction.

The trusted repository/service—not the HTTP payload—must assign canonical
identity and enforce uniqueness. A caller-provided owner or tenant field is
metadata until the approved identity model says otherwise. Authentication
direction and Clerk selection are approved; exact token verification,
persistent principal mapping, administrative ownership-transfer safeguards,
and deployment configuration remain **OPEN — APPROVAL REQUIRED**. No current
API authentication or tenant isolation is implied.

### Storage and immutable versions

**Proposed:** use private quarantine storage and a provider adapter that can
write a new immutable object version, read that exact version, and return a
provider-neutral reference. Allocate a new `assetVersionId` for replacement
content. Never overwrite an existing version or resolve `latest`. Do not expose
raw storage keys as authorization tokens or treat IDs as secrets.

The metadata repository should bind `(projectId, assetId, assetVersionId)` to
one exact private object-version reference and record lifecycle revision. It
must reject an identity rebind. Private storage, stable immutable versions,
exact-version reads, conditional writes, and controlled deletion/retention are
approved requirements. Provider selection and deployment-specific proof of
these capabilities, plus encryption/KMS configuration, remain
**OPEN — APPROVAL REQUIRED**.

### Digest and validation evidence

**Proposed flow:** after upload finalization, a constrained validation worker
reads the exact immutable object version. It enforces actual byte and duration
limits, computes SHA-256 and actual byte count over the exact byte stream it
parses, and validates those same bytes against an approved media profile. It
emits a versioned result binding project, asset, immutable object version,
digest, actual byte count, observed media properties, profile ID/version,
validator identity/build, timestamp, and validation-attempt ID to that exact
inspection. Evidence revision/revocation is recorded separately and auditable.
Every later reread for resolution or rendering must use the pinned immutable
object version and verify both its actual byte count and SHA-256 against the
recorded evidence before use; a mismatch fails closed.

Only the trusted validation service may cause an authoritative readiness
transition. A public request, caller-created Pydantic model, matching digest
string, or `state="ready"` is not evidence of origin. Prefer an authenticated,
private service/repository boundary for v1. Signatures are not assumed; whether
the process boundary and credential custody are sufficient, who can revoke
evidence, and evidence schema versioning are **OPEN — APPROVAL REQUIRED**.

Evidence becomes unusable if identity, exact object version, digest/size,
profile, or required validation policy no longer matches, if the validation
attempt is stale, or if the evidence has been revoked. A changed byte stream is
a new immutable asset version. Revalidation may issue new evidence for the
same immutable version only after exact-version verification. The concrete
revalidation workflow and persistence remain open.

### Lifecycle and concurrency

The existing `AssetState` set is `uploading`, `quarantined`, `validating`,
`ready`, `failed`, `rejected`, `deletion_pending`, `deleted`, and `expired`.
`_ALLOWED_TRANSITIONS`, `transition_asset`, and
`check_asset_transition_preconditions` are pure/in-memory checks, not durable
state transitions.

**Proposed lifecycle:**

1. Create an `uploading` record and unique version identity under an authorized
   project operation.
2. Stream bytes to private quarantine with a configured actual-byte limit; do
   not make partial uploads addressable as ready assets.
3. Finalize one exact immutable object version and CAS to `quarantined`.
4. Create a unique validation attempt and CAS to `validating`.
5. The isolated worker reads that exact object version and returns a bounded
   typed result. The repository accepts it only if project, asset, version,
   expected state, state revision, attempt ID, evidence revision, object
   reference, digest and profile still match.
6. CAS to `ready` only from an accepted trusted result. Malformed or unsupported
   media becomes `rejected`; infrastructure failure becomes `failed` only under
   an approved retry policy. A stale/duplicate worker result is a no-op.
7. Logical deletion enters `deletion_pending` and immediately blocks new
   resolution and leases. Physical deletion waits for approved retention and
   all valid leases to release or expire, then records a minimal tombstone.

Deletion during a valid already-authorized render lease may permit that job to
finish under the approved direction. Expiration behavior during an active job,
retry rules, rejected-version revalidation, evidence revocation, and the
duration and mechanics for lease expiry, renewal, recovery, and release remain
**OPEN — APPROVAL REQUIRED**. The policy direction requires bounded leases and
abandoned-job recovery.
All durable transitions require compare-and-swap or equivalent transactions;
the pure helper alone is not an atomicity guarantee.

### Retention, quotas, audit and resource controls

The policy record lists 25 MiB, 60 seconds, two validation jobs, and 500 MiB per
project as provisional development values only; only the WAV validator uses the
first two as configurable defaults. None is workload-validated or
production-approved. The repository has no upload quota, worker concurrency,
retention, backup deletion, or persistent audit implementation.

**Proposed:** fail closed when required production limits are absent or invalid;
enforce byte limits while streaming, then duration after trusted parsing;
separate global, per-project, and per-principal quotas/concurrency; account for
quarantined and retained versions explicitly. Keep audit records for security
and lifecycle transitions with bounded, redacted fields. Never log media bytes,
credentials, full untrusted filenames, or raw parser exceptions. Production
quota size and product/plan considerations beyond approved reject-on-exceed
behavior, failed-upload cleanup, backup deletion, audit retention, privacy
jurisdiction, and production resource budgets are
**OPEN — APPROVAL REQUIRED** and deployment-specific where infrastructure or
legal controls are involved.

## 3. Renderer and job handoff

**Proposed:** accept only a successful v2 `VersionedRenderPlan` at the future
resolution boundary; reject legacy v1 plans, raw package objects, and validation
results. Authorize the authenticated principal for the plan project before
resolution. Require each plan asset pin to match exactly one project-owned
version record in `ready`, with current non-revoked evidence and exact immutable
object version/digest/profile. Never substitute a newer version.

Create an immutable resolution snapshot containing every required package
`assetId`, `assetVersionId`, object version, digest, profile, and lease reference.
Partial resolution yields no snapshot. Acquire leases and create the complete
job input snapshot atomically (transactional outbox or equivalent); a digest
alone does not prevent object deletion or guarantee availability. The renderer
reads only pinned object versions under a constrained worker identity and
rechecks actual byte count and digest against the evidence before use. A
missing, expired, deleted, revoked, mismatched, or unavailable pin fails closed.
V1 packages remain inspectable/validatable but
must never enter asset resolution or rendering.

The current pure matcher is not this boundary: its output is caller-constructible
and it has no authorization, storage, lease, transaction, or worker guarantees.
Database/queue design, atomic lease/job handoff, maximum job lifetime, and
whether existing jobs survive evidence revocation are **OPEN — APPROVAL
REQUIRED**.

## 4. Threat model and abuse cases

| Threat | Required control and acceptance evidence |
| --- | --- |
| Cross-project ID substitution / IDOR | Authenticate a principal and authorize project access on every operation; tests prove foreign project IDs cannot upload, enumerate, read, delete, resolve, or render. |
| Caller forges `ready`, digest, or evidence | Only trusted service writes authoritative evidence/readiness; request schemas reject trust fields; tests prove caller models cannot change repository state. |
| Object replacement or `latest` substitution | Immutable version references and exact-version reads; tests replace current aliases and prove old pins resolve only to old versions or fail. |
| Upload truncation, oversized body, duplicate finalization | Incremental bounded ingestion, actual byte count, idempotent finalization, unique attempt/version; tests at/beyond limits and interrupted streams. |
| Malformed WAV / parser denial of service | Isolated parser with CPU/memory/wall-clock limits plus bounded pure parser; adversarial RIFF/chunk corpus, fuzz/property tests, no parser crash or unbounded allocation. |
| Late worker result / retry race | CAS over state revision, exact version and attempt ID; race tests prove stale completion cannot restore readiness after retry, deletion, or revocation. |
| Stale or revoked evidence | Bind evidence to exact bytes/profile/build and check revocation/current revision at resolution; tests change every binding independently and fail closed. |
| Delete/render TOCTOU | Atomic leases/job creation and exact immutable object-version pin; concurrency tests race deletion, expiry, resolution, and job handoff. |
| Storage credential compromise | Separate least-privilege API, validator, and renderer identities; isolated worker and no credentials in untrusted parser process; deployment security verification. |
| Secret/media leakage in errors or logs | Stable sanitized failures and redacted audit fields; sentinel secrets, filenames, payloads and exception strings never appear in responses/logs. |
| SSRF or URL-fetch reintroduction | Do not add URL fetching to the asset pipeline. The existing `website_scan.py` / `scan_cli.py` are local website-extraction code, not an asset-ingestion route; `/scan` remains unregistered and GET/POST return 404. Preserve the documented DNS rebinding/TOCTOU limitation and public-deployment warning in `backend/WEBSITE_EXTRACTION.md`; do not expose the CLI as a service. |

## 5. Approval register and implementation order

Before code depends on them, resolve the existing **OPEN — APPROVAL REQUIRED**
items in `docs/asset-trust-policy-decisions.md`, especially:

- Remaining OD-01/OD-02 details: administrator ownership-transfer safeguards,
  persistent ownership mapping, exact token type/claims/verification, and
  deployment authorization configuration. The owner-only v1 direction and
  Clerk selection are approved, but no integration is implemented.
- Storage provider and enforceable immutable-version, private-read, deletion,
  encryption and backup guarantees.
- Trusted validator identity, evidence authenticity/version/revocation, and
  revalidation semantics.
- WAV compatibility against supported client media, including the narrow v1
  16-byte `fmt ` restriction and ancillary-chunk behavior.
- Production upload/duration/concurrency/quota limits, retention, deletion and
  backup policy, lease lifetime/recovery, audit retention, and privacy controls.
- Database/queue transaction boundary and job behavior under deletion or
  evidence revocation.

Recommended dependency order, pending approval:

1. Resolve the remaining identity/token contract, storage guarantees, evidence
   authority, WAV compatibility, resource limits, retention and deletion/lease
   policies without reopening approved policy directions absent an explicit
   policy change.
2. Finalize versioned durable metadata/evidence and CAS contracts without
   conflating caller declarations with trusted observations.
3. Implement private immutable quarantine storage and bounded upload
   finalization behind authenticated project authorization.
4. Implement an isolated validator worker that reads the exact object version,
   computes digest/size over parsed bytes, emits authenticated results, and
   supports stale-attempt rejection and readiness revocation.
5. Implement lifecycle persistence, quotas, audit, cleanup and deletion rules
   with concurrency/race tests.
6. Implement authenticated versioned resolution, leases, atomic job/outbox
   handoff, then renderer reads of exact pinned versions.
7. Verify deployment security: storage isolation, credentials/KMS, worker
   resource limits, backups, log redaction and failure behavior.

No implementation milestone is authorized by this proposal. `/scan` remains
unavailable throughout. This does not remove or endorse the existing local
website scanner; its DNS rebinding/TOCTOU limitation and public-deployment
warning remain in force.
