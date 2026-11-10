# Asset Trust-Policy Decision Record

**Purpose:** Prepare the unresolved trust-boundary and operational choices for approval before trusted storage, uploads, media validation, leases, or rendering are implemented.

**Status distinction:** Approved policy below records approved direction only; it does not mean controls exist. Every recommendation in the matrix is a proposal, not approved policy. Provisional development limits are not production approval. This document authorizes no implementation or API exposure.

## Existing implementation and previously approved policy

| Area | Current implementation evidence | Previously approved policy (implementation pending) |
|---|---|---|
| Project ownership and sharing | `AssetDeclaration` in `backend/adforge_renderer/asset_contract.py` requires `project_id` and permits optional `tenant_id` and `owner_id`. `resolve_versioned_assets` checks project identity. `backend/adforge_renderer/api.py` has no authentication or project-authorization dependency. | Assets are project-bound in v1; cross-project sharing is disabled. Resolution matches exact project, asset, and version. IDs are identifiers, not credentials. |
| Asset/version identity | `ManagedAsset` combines a declaration with `asset_version_id`; no persistent uniqueness registry exists. V2 packages and `compile_versioned_render_plan` carry version pins. | Replacements create new immutable versions. Never overwrite a version or resolve “latest.” |
| Validation evidence | `AssetValidationEvidence` and `VersionBoundValidationEvidence` are caller-constructible. `compare_version_bound_evidence` checks fields against a supplied `AssetVersionBinding`; neither it nor the existing `_evidence_matches_asset` authenticates evidence or verifies bytes. No trusted worker or revocation record exists. | A controlled trusted worker inspects the exact immutable stored-object version and issues authoritative evidence binding project, asset, version, object reference, SHA-256, actual byte count, observed media properties, profile, and validation-attempt ID to the exact bytes inspected. Only the trusted validation service may issue it; callers cannot set trusted `ready`. Any later reread must match the recorded digest and byte count before use. V1 authenticity relies on a private trusted backend-service boundary. Defer signatures unless that boundary is insufficient. |
| Lifecycle | `_ALLOWED_TRANSITIONS` and `transition_asset` model in-memory states. `check_asset_transition_preconditions` revalidates values and checks identity/state/revision/attempt CAS fields, but there is no persistent repository or atomic CAS. | Accept validation results only with CAS matching immutable version, expected state, state revision, and worker-result attempt ID. Discard stale results; they cannot restore readiness after deletion, replacement, or a newer attempt. |
| Media profile | `asset_contract.py` defines `ObservedWavProperties`; `wav_validation.py:validate_wav_bytes` parses bounded in-memory bytes and returns observed WAV properties. It is not connected to storage or trusted evidence. Package timing uses 24 fps. | WAV signed 16-bit little-endian PCM, 48 kHz stereo. A trusted service must inspect exact stored bytes before issuing evidence. Sample count must divide evenly into 2,000 samples per video frame; reject non-aligned duration without rounding. |
| WAV compatibility | `docs/wav-compatibility-matrix.md` and `backend/tests/wav_fixture_factory.py` describe the implemented pure parser behavior: strict RIFF extent; one 16-byte PCM `fmt ` before one `data`; opaque structurally valid ancillary chunks; `LIST`, RF64, RIFX, extensible PCM and malformed chunks rejected. The compatibility matrix remains proposed and has no real client-media corpus validation. | The parser behavior is a narrow v1 compatibility proposal, not trusted validation or production approval. Review against supported client media before relying on it in a trusted worker. Reject malformed, truncated, unsupported, or inconsistent media regardless of filename/MIME. |
| Limits | `MAX_DECLARED_DURATION_FRAMES` and package JSON byte limits are structural limits, not media upload policy. No media upload, quota, or worker-concurrency controls exist. | Provisional development defaults only: 25 MiB audio, 60 seconds, two concurrent validation jobs, and 500 MiB per project. Configurable, server-enforced, and fail closed if required configuration is absent/invalid. Not production approved. |
| Deletion and retention | Lifecycle states are in-memory; there is no storage deletion, retention, backup, tombstone, or render lease implementation. | Logical deletion immediately blocks new resolution and leases. Already-authorized jobs may finish with valid existing leases. Physical deletion waits for lease release and approved retention. Lease recovery must prevent abandoned jobs blocking deletion indefinitely. |
| Leases | Immutable lease request/record/transition shapes exist. `bind_lease_request_to_resolution` checks complete pin equality, and `asset_lease_is_valid_at` checks a lease against explicit time. All values remain caller-constructible; no lease/job repository or storage pin exists. | A valid existing lease may let an authorized job finish after logical deletion. Abandoned leases must not block deletion indefinitely. |
| Security and deployment | The API has no authenticated principal/project check or asset storage API. The repository does contain local `website_scan.py` / `scan_cli.py` extraction code; `backend/WEBSITE_EXTRACTION.md` documents its DNS rebinding/TOCTOU gap and warns against public deployment. `docs/website-fetching-threat-model.md` records that API `/scan` is not registered. | Authenticate user-facing asset operations; authorize project access for upload/read/delete/resolve/render; separate least-privilege asset, validation, and render identities; private storage; transit/at-rest encryption with deployment-approved KMS; audit sensitive actions without media/secrets; keep privileged storage credentials away from untrusted parsers. Do not expose the existing scanner or add URL-fetching functionality under this asset-pipeline proposal. |

## Decision 1 — Initial Tenancy, Authentication and Project Ownership

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval scope:** Initial Spotloom Studio v1 policy direction only.
- **Approved direction:** Individual users with personal projects; Clerk as the
  approved managed identity provider under Decision 2; owner-only project
  access with no project sharing.
- **Implementation authorization:** Not granted.

### Proposed direction

- **Initial tenancy:** Individual users with personal projects.
- **Authentication:** Use Clerk, the provider approved in Decision 2. Exact
  token validation and production integration remain unresolved.
- **Project sharing:** Disabled in v1. Only the authenticated project owner may
  access that project.
- **Asset ownership:** Every asset belongs to exactly one project. Cross-project
  sharing remains disabled.
- **Authorization:** Every user-facing asset operation must enforce project
  ownership server-side. Project IDs, asset IDs, version IDs, and other
  identifiers are not credentials.
- **Ownership assignment:** The trusted backend assigns project ownership.
  Client-supplied owner or tenant fields are not authoritative.
- **Future expansion:** Team workspaces, collaborators, and organization roles
  are outside v1 scope and require a separately reviewed policy change.

### Required security behavior

Before allowing a user-facing operation, the backend must establish the
authenticated principal and verify that the principal owns the target project.
This applies to project and asset creation, listing, reading, uploading,
deletion, resolution, and render-job submission. Unauthorized and cross-project
requests must fail closed without exposing protected asset data.

Internal asset-validation and rendering services must use separately scoped,
least-privilege service identities. User authentication does not establish
trust in validation evidence or authorize internal service operations.

### Decisions still open

The following remain **OPEN — APPROVAL REQUIRED** before dependent
implementation:

1. Exact Clerk token-validation contract and production verification
   configuration.
2. Canonical project identifier model and persistent ownership mapping,
   including schema and constraints; canonical user identity direction is
   recorded in Decision 3.
3. Project creation, deletion, ownership transfer, account deletion, recovery,
   and orphaned-project behavior.
4. Authentication assurance, session/token expiry, revocation, and
   account-disable behavior.
5. Internal service identities, credential custody, and the trusted
   validation-service boundary.
6. Deployment-specific security controls, audit requirements, and operational
   recovery behavior.

This policy direction does not select an asset-storage provider, establish
production security controls, or authorize implementation. Clerk is the
approved v1 identity provider under Decision 2; exact token validation,
production integration, and infrastructure/deployment guarantees remain
open. The corresponding identity and tenancy implementation details in the
decision matrix below remain open until explicitly approved.

## Decision 2 — Managed Identity Provider and Token-Validation Contract

**Status: Provider approved — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval scope:** Selection of Clerk as Spotloom Studio's managed identity
  provider for v1 only.
- **Approved provider:** Clerk.
- **Implementation authorization:** Not granted.

Approval of Clerk alone did not approve the token-validation contract. The
later project-level OD-02 approval records the proposed v1 contract and its
limitations; unresolved production configuration, revocation, identity
persistence, lifecycle, service-security, and deployment decisions remain
open.

### Proposed provider

- **Preferred provider:** Clerk.
- **Rationale:** Strong Next.js integration, managed authentication flows,
  maintained server-side verification support, and operational simplicity for
  Spotloom Studio's individual-user v1. This is not a claim that Clerk is
  inherently more secure than alternatives.
- **Alternatives considered:** Auth0, Supabase Auth, and WorkOS AuthKit.

The proposed v1 verifier contract is approved at project level under OD-02.
Deployment-specific production configuration and session/revocation behavior
remain **OPEN — APPROVAL REQUIRED**.

### Proposed token-validation requirements

1. Validate authentication on the server for every protected request.
2. Use the selected provider's maintained verification SDK or an explicitly
   approved standards-based verifier.
3. Validate the token signature, permitted algorithm, issuer, expiry,
   not-before time, and audience or authorized-party claims where applicable to
   the selected token type and provider contract.
4. Accept only the intended token type. User-session tokens, OAuth access
   tokens, and service credentials are not interchangeable.
5. Map the verified provider subject to a canonical internal Spotloom user ID.
6. Authenticate the user and authorize project access as separate checks.
7. Verify project ownership server-side for every protected project and asset
   operation. Fail closed on invalid credentials or failed authorization.
8. Keep internal validation and rendering service identities separate from
   user authentication.
9. Do not treat authentication tokens as proof of asset validation, trusted
   evidence, or asset readiness.

### Decisions that remain open

The following remain **OPEN — APPROVAL REQUIRED** before dependent
implementation:

1. Exact token type, issuer, audience, authorized-party rules, verification
   configuration, and token-validation contract.
2. Canonical internal user IDs and provider-subject mapping.
3. Session/token expiry, revocation, account disabling, account recovery, and
   account/project lifecycle.
4. Internal service identities, credential custody, and the trusted
   validation-service boundary.
5. Deployment-specific security controls, audit requirements, and operational
   recovery.

This approval does not claim that a provider plan or security feature has been
verified for production. Decision 1's approved scope is unchanged. OD-02's
decision-matrix row remains **OPEN — APPROVAL REQUIRED** for unresolved
production configuration and session/revocation details; all other unresolved
matrix items remain open.

## Decision 3 — Canonical Internal User ID and Clerk Subject Mapping

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval scope:** Canonical internal user identity and Clerk
  subject-mapping policy direction for Spotloom Studio v1.
- **Approved direction:** Stable internal Spotloom user IDs; verified Clerk
  issuer (`iss`) and subject (`sub`) mapping; atomic, idempotent,
  concurrency-safe server-side user creation or retrieval after successful
  authentication; automatic account linking disabled in v1; separate
  server-side project-ownership authorization.
- **Implementation authorization:** Not granted.

This approval establishes the policy direction only. It does not approve the
exact token-validation contract, full persistence schema or database
constraints beyond the scoped identity-mapping requirements below, session and
account lifecycle, recovery and identity replacement, account deletion and
retention, internal service identities, credential custody, or
deployment-specific controls. These and all other unresolved decision-matrix
items remain **OPEN — APPROVAL REQUIRED**.

**Project-level identity-mapping approval (2026-11-01):** Ashishkumar Maurya —
Project Owner and Maker — approved mapping the exact verified Clerk
`(issuer, subject)` pair to a backend-generated stable internal user ID, with
database uniqueness, transactional creation, and idempotent repeat lookup.
Email and client-supplied identity are not ownership authorities. This records
the approved approach, not an implemented mapping. Detailed schema,
provider/deployment configuration, and failure handling remain open.
Implementation remains subject to the separately recorded OD-01/OD-02 scope
and its open prerequisites.

### Proposed direction

#### 1. Canonical internal user identity

- Spotloom maintains a stable, canonical internal `user_id` for each user.
- The trusted backend generates and controls this identifier.
- Project ownership references the internal `user_id`, never an email address
  or client-supplied owner identifier.
- The internal user ID remains independent of the identity provider's user
  identifier.

#### 2. External identity mapping

- Map a verified Clerk identity to the internal user using the verified issuer
  (`iss`) and subject (`sub`) pair.
- Treat the issuer-subject pair as the external identity key, subject to the
  final approved Clerk token-validation contract.
- Enforce uniqueness for the external identity mapping so one verified
  external identity cannot silently map to multiple internal users.
- Never create or assign ownership based on unverified claims, email addresses
  alone, or client-supplied identity fields.

#### 3. Internal user creation

- On first successful authentication, the trusted backend may create or
  retrieve the internal user and identity mapping through an atomic,
  server-side upsert.
- The operation must be idempotent and concurrency-safe to prevent duplicate
  users or mappings during simultaneous requests.
- Do not provision an internal user until the authentication token has been
  successfully verified under the approved token-validation contract.
- The precise database constraints and failure-handling behavior remain
  subject to implementation design and review.

#### 4. Account linking

- Automatic account linking is disabled in v1.
- An existing internal user must not be linked to another external identity
  based solely on a matching email address.
- Any future account linking or identity replacement requires a separately
  authenticated, verified recovery/linking flow.
- Account recovery, identity replacement, and exceptional administrative
  recovery rules remain unresolved and require separate approval.

### Security and authorization requirements

- Authentication establishes the verified external identity; it does not by
  itself authorize project access.
- Resolve the verified external identity to the canonical internal `user_id`
  on the server.
- Check project ownership server-side before every protected project or asset
  operation.
- Fail closed if identity verification, identity mapping, or authorization
  fails.
- Do not allow client-supplied user, owner, tenant, or project fields to
  override trusted ownership records.
- Do not treat an identity mapping as proof of asset validation, trusted
  evidence, or asset readiness.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following remain **OPEN — APPROVAL REQUIRED** before dependent
implementation:

1. The exact Clerk token-validation contract, including token type,
   issuer/audience rules, authorized-party checks, and verification
   configuration.
2. The canonical user/project persistence schema and database constraints.
3. Session expiry, revocation, account disabling, account recovery, identity
   replacement, and account/project lifecycle.
4. Account deletion, orphaned projects, and data retention.
5. Internal service identities, credential custody, and the trusted
   validation-service boundary.
6. Deployment-specific security controls, audit requirements, and operational
   recovery.
7. Every other unresolved item in the decision matrix.

## Decision 4 — Clerk Token-Validation Contract

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval scope:** Token-validation policy principles for Spotloom Studio v1
  only.
- **Approved direction:** Browser requests use Clerk session tokens verified
  server-side; required token checks and applicable issuer, audience,
  authorized-party, expiry, not-before, signature, and algorithm requirements
  must be explicitly documented; invalid, expired, unverifiable, or mismatched
  credentials fail closed; only verified identity claims resolve the canonical
  internal Spotloom user; authentication and project-ownership authorization
  remain separate; provider-supported session state and revocation mechanisms
  are used where required by the subsequently approved security contract; and
  offline JWT verification limitations are documented without claiming
  immediate revocation awareness from cryptographic verification alone.
- **Implementation authorization:** Not granted.

This approval covers these principles only. It does not approve a
production-ready token-validation contract or authorize implementation.

### Proposed direction

#### 1. Browser authentication credential

- For browser requests to the Spotloom web application, the proposed credential
  is a Clerk session token verified server-side.
- Do not treat a decoded token or client-side authentication state as
  sufficient proof of authentication.
- Do not interchange Clerk session tokens, OAuth access tokens, and internal
  service credentials.
- The exact token format, verification configuration, and accepted claims
  remain subject to explicit approval.

#### 2. Token verification and claim expectations

- Protected requests must be authenticated server-side using Clerk's
  maintained verification SDK or another explicitly approved verifier.
- Document the expected issuer and the applicable audience and authorized-
  party (`azp`) requirements for the selected token and application
  configuration.
- Reject tokens that fail signature verification, use an unapproved algorithm,
  are expired, violate applicable not-before checks, or fail configured
  issuer, audience, authorized-party, or other required claim checks.
- Do not assume every claim is present or applicable to every token type.
  Establish the exact contract from the selected Clerk configuration and
  documented verification behavior before implementation.
- Verification must fail closed when required checks cannot be completed.

#### 3. Session termination and revocation

- The proposed policy is to use provider-supported session state and
  revocation mechanisms where required by the approved security requirements.
- Document the limitations of offline JWT verification: a token that passes
  cryptographic and claim checks may not immediately reflect a session that
  has subsequently been revoked or terminated, depending on the verification
  method.
- The acceptable delay for revocation enforcement, online session-state
  checks, and any caching behavior remain unresolved.
- Do not claim that cryptographic verification alone provides immediate
  revocation awareness.

#### 4. Principal resolution and authorization

- Obtain identity claims only from a successfully verified token.
- Resolve the verified issuer (`iss`) and subject (`sub`) to the canonical
  internal Spotloom user ID under approved Decision 3 policy.
- Authentication and project authorization remain separate operations.
- Check project ownership server-side before every protected project or asset
  operation.
- Authentication does not establish asset trust, validation evidence, or
  asset readiness.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following remain **OPEN — APPROVAL REQUIRED** before dependent
implementation:

1. Exact Clerk configuration, token type and format, issuer, audience,
   authorized-party requirements, permitted algorithms, required claims, and
   verification settings.
2. The exact token-validation contract and the verification method to be used
   in production.
3. Session lifetime, token expiry policy, revocation enforcement, session
   termination, account disabling, caching behavior, and acceptable revocation
   delay.
4. Canonical identity persistence, database schema and constraints, and
   identity-mapping failure handling.
5. Internal service identities, credential custody, and the trusted
   validation-service boundary.
6. Deployment-specific security controls, audit requirements, and operational
   recovery.
7. Every other unresolved item in the decision matrix.

## Decision 5 — Session Lifecycle and Revocation Policy

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval scope:** Session lifecycle and revocation policy direction for
  Spotloom Studio v1 only.
- **Approved direction:** Do not rely solely on offline JWT verification when
  prompt session revocation is required; use provider-supported live
  session-state or revocation checks where necessary under the subsequently
  approved security contract; invalid, expired, or revoked credentials must
  not authorize protected requests; once a user's disabled status is enforced,
  deny new protected requests even if the presented token is otherwise
  cryptographically valid; recheck authorization when a render job begins
  execution and at sensitive job transitions; and do not treat prior job
  submission as permanent authorization.
- **Implementation authorization:** Not granted.

This approval does not establish a production revocation mechanism or guarantee
immediate revocation. It does not decide whether already-running jobs are
cancelled, paused, or permitted to finish.

### Proposed direction

#### 1. Session termination and revocation

- Protected requests must not rely solely on successful offline JWT
  verification when prompt session revocation is required.
- Use provider-supported live session-state or revocation checks where
  necessary to enforce the subsequently approved revocation policy.
- Expired, invalid, or revoked credentials must not authorize protected
  requests.
- Do not claim that cryptographic JWT verification alone guarantees immediate
  awareness of session termination or revocation.

#### 2. Disabled accounts

- Once a user's disabled status is enforced, deny new protected requests even
  when the presented token is otherwise cryptographically valid.
- Authentication-provider session state and Spotloom's account-disable
  enforcement must not be assumed to be equivalent without an explicitly
  approved integration contract.
- The mechanism for representing, propagating, and checking disabled-account
  status remains unresolved.

#### 3. Existing render jobs

- Recheck authorization when a render job begins execution and at sensitive
  job transitions, using the applicable approved account and project
  authorization state.
- A previously authorized job submission must not automatically bypass
  authorization checks at execution.
- Whether account disablement or session revocation cancels, pauses, or permits
  an already-running job to finish remains open for explicit policy approval.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following remain **OPEN — APPROVAL REQUIRED** before dependent
implementation:

1. Exact session lifetime, token expiry policy, refresh behavior, and
   provider-specific session semantics.
2. The exact provider-supported session-state or revocation mechanism and its
   consistency guarantees.
3. Acceptable revocation latency and the verification behavior required to
   meet it.
4. Cache policy, including whether session or account-status results may be
   cached and for how long.
5. Account-disable propagation, recovery, account deletion, and related
   account/project lifecycle behavior.
6. Whether revocation or account disablement cancels, pauses, or permits
   in-flight render jobs to finish.
7. Internal service identities, credential custody, and the trusted
   validation-service boundary.
8. Deployment-specific security controls, audit requirements, and operational
   recovery.
9. Every other unresolved item in the decision matrix.

## Decision 6 — Account and Project Lifecycle

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval scope:** Account and project lifecycle policy direction for
  Spotloom Studio v1 only.
- **Approved direction:** Block new protected operations when account deletion
  or disabled status is enforced; mark accounts for deletion through a trusted
  lifecycle process; keep affected projects and assets private while approved
  retention and deletion processes complete; require separately authenticated,
  verified account recovery or identity replacement and never restore
  ownership based solely on an email match; block new render-job submissions
  when deletion or disabled status is enforced; propose cancelling queued
  render jobs associated with the account; recheck authorization at render-job
  execution and sensitive transitions; and do not automatically transfer
  project ownership or expose orphaned projects or assets.
- **Implementation authorization:** Not granted.

This approval establishes the policy direction only. It does not establish
retention periods, authorize physical deletion, finalize recovery procedures,
determine the treatment of already-running render jobs, or authorize
implementation.

### Proposed direction

#### 1. Account deletion

- Immediately block the account from initiating new protected operations when
  deletion is requested and the disabled/deletion state is enforced.
- Mark the account for deletion through a trusted lifecycle process.
- Keep affected projects and assets private and inaccessible to unauthorized
  users while approved retention and deletion processes complete.
- Do not treat a deletion request as authorization to bypass asset-retention,
  lease, audit, or active-job safeguards.
- The retention period and physical-deletion process remain unresolved.

#### 2. Account recovery and identity replacement

- Require a separately authenticated, verified recovery process for account
  recovery or identity replacement.
- Never restore account or project ownership based solely on a matching email
  address.
- Recreated Clerk identities must not automatically inherit ownership from an
  earlier identity.
- The precise recovery, identity replacement, exceptional administrative
  recovery, and account-linking procedures remain unresolved.

#### 3. Queued and running render jobs

- Block new render-job submissions once the account's deletion or disabled
  status is enforced.
- Propose cancelling queued jobs associated with the account during the
  deletion workflow.
- Recheck authorization at job execution and sensitive job transitions,
  consistent with Decision 5.
- Do not assume queued-job cancellation also terminates a job already running.
- The handling of running jobs, cancellation guarantees, cleanup behavior, and
  failure recovery remain unresolved.

#### 4. Project and asset privacy

- Projects remain associated with their canonical internal Spotloom user ID.
- Account deletion or identity loss must not automatically transfer ownership
  or make projects and assets publicly accessible.
- Keep orphaned-project handling, ownership recovery, asset retention, and
  eventual physical deletion subject to separately approved lifecycle rules.
- Preserve trusted asset-version, lease, and deletion safeguards; do not bypass
  them to simplify account deletion.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following remain **OPEN — APPROVAL REQUIRED** before dependent
implementation:

1. Retention periods and the conditions and timing for physical deletion of
   projects, assets, and associated data.
2. Recovery verification, exceptional administrative recovery, identity
   replacement, and restoration of project ownership.
3. Orphaned-project handling and the relationship between account deletion,
   project lifecycle, and asset ownership.
4. Whether running render jobs are cancelled, paused, or permitted to finish;
   cancellation guarantees and transition behavior.
5. Lease expiry, lease cleanup, deletion coordination, and recovery from
   partial cleanup failures.
6. Account deletion state transitions, retries, idempotency, and failure
   recovery.
7. Internal service identities, credential custody, and the trusted
   validation-service boundary.
8. Deployment-specific security controls, audit requirements, and operational
   recovery.
9. Every other unresolved item in the decision matrix.

## Decision 7 — Trusted Validation Boundary and Evidence

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval:** Explicitly approved by the user as a policy direction.
- **Implementation authorization:** Not granted.

This approval does not approve a production evidence format, service-identity
configuration, storage guarantee, CAS implementation, retry policy, or
implementation.

### Proposed direction

#### 1. Trusted evidence issuer

- Only a dedicated trusted validation service may issue authoritative
  asset-validation evidence.
- The validation service must use its own separately scoped, least-privilege
  service identity.
- Clients and untrusted parsing workers must not be able to issue, forge,
  modify, or promote authoritative validation evidence.
- A validation result must not make an asset ready merely because a caller
  supplies a trusted-looking status or payload.

#### 2. Evidence binding

Authoritative validation evidence must bind the result to all of the following:

- Canonical project ID.
- Asset ID.
- Exact immutable asset-version ID.
- Exact immutable object reference.
- SHA-256 digest of the exact inspected byte stream.
- Actual byte count of that byte stream.
- Observed media properties.
- Validation profile or policy version used.
- Unique validation-attempt ID.

The evidence must describe the exact bytes inspected by the trusted validation
service. A later read must verify the expected immutable object version, digest,
and byte count before relying on the evidence.

#### 3. Stale or mismatched validation results

- Accept a validation result for readiness only when it matches the current
  immutable asset version, expected state, expected revision, and
  validation-attempt ID.
- Reject stale, superseded, duplicated where inappropriate, or mismatched
  results for readiness purposes.
- A rejected result must not change the asset's readiness state.
- Validation completion alone does not authorize readiness; the trusted
  backend must verify that the result satisfies the applicable state and
  version conditions.
- Retry behavior and compare-and-swap (CAS) implementation details remain
  unresolved.

#### 4. Separation of trust

- User authentication and project authorization do not establish that an
  asset has been validated.
- The trusted validation service is the only proposed issuer of authoritative
  validation evidence.
- Rendering and other downstream consumers must rely only on evidence that
  passes the approved trust, version, and readiness checks.
- Keep validation-service credentials and other privileged storage credentials
  out of untrusted parsing workers.
- This policy proposal does not establish the final service topology,
  credentials, storage configuration, evidence-signing method, or revocation
  mechanism.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following remain **OPEN — APPROVAL REQUIRED** before dependent
implementation:

1. Exact service identity design, provisioning, permissions, credential custody,
   and rotation.
2. Evidence schema, canonical serialization, integrity protection or signing,
   verification, and revocation.
3. Immutable storage guarantees and the authoritative object-version reference
   model.
4. The exact digest and byte-count verification procedure for uploads,
   validation reads, and subsequent reads.
5. CAS implementation, revision semantics, expected-state transitions, and
   concurrency handling.
6. Validation retries, timeouts, duplicate attempts, idempotency, and failure
   recovery.
7. Lease semantics, deletion coordination, and cleanup of stale or abandoned
   assets.
8. Deployment-specific security controls, audit requirements, and operational
   recovery.
9. Every other unresolved item in the decision matrix.

## Decision 8 — Immutable Asset Storage and Version Identity

**Status: Approved policy direction — implementation pending.** Decision 8 was
not present in the current document, so this section records the approved
principles supplied for this update; it does not authorize implementation.

- **Approval date:** 2026-10-25
- **Approval:** Explicitly approved by the user as a policy direction.
- **Implementation authorization:** Not granted.

### Approved principles

1. Storage is private by default, and access is mediated by trusted backend
   authorization.
2. The backend controls stable asset-version IDs and authoritative
   storage-object version references.
3. Replacements create new immutable versions; existing versions cannot be
   silently overwritten.
4. Validation and subsequent reads retrieve the exact version and verify its
   SHA-256 digest and actual byte count.
5. If exact immutable-version retrieval cannot be guaranteed, the asset cannot
   be promoted to trusted `ready` status.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following implementation and deployment details remain **OPEN — APPROVAL
REQUIRED**:

1. Storage provider, configuration, object-version guarantees, and authoritative
   storage-reference format.
2. Upload and ingestion behavior, permissions, and access-control enforcement.
3. Encryption, key management, credential custody, and service identities.
4. Retention, deletion, leases, and coordination with active or queued jobs.
5. Recovery, cleanup, and failure handling for unavailable versions or storage
   operations.
6. Deployment-specific security controls, audit requirements, and operational
   recovery.
7. Every other unresolved item in the decision matrix.

## Decision 9 — Upload Finalization and Asset Admission

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval:** Explicitly approved by the user as a policy direction.
- **Implementation authorization:** Not granted.

### Approved principles

1. Uploads remain untrusted by default; upload completion alone does not make
   an asset trusted or ready.
2. Finalization is a server-controlled transition that binds the completed
   upload to the correct project, asset, and immutable version.
3. Incomplete, interrupted, or ambiguous uploads cannot be admitted as
   finalized versions or promoted to `ready`.
4. The trusted validation service inspects the exact finalized immutable
   version, following Decision 7's evidence requirements.
5. Missing objects, unexpected versions, digest or byte-count mismatches, and
   uncertain finalization outcomes must fail closed.
6. Duplicate finalization requests and interrupted operations must not
   silently create conflicting state.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following upload and deployment details remain **OPEN — APPROVAL
REQUIRED**:

1. Upload protocol, provider behavior, multipart handling, and upload
finalization interfaces.
2. Size, duration, concurrency, and other resource limits.
3. Cleanup of incomplete or interrupted uploads.
4. Idempotency keys, transaction boundaries, retries, and recovery behavior.
5. Retention, deletion, and coordination with leases or active jobs.
6. Deployment-specific configuration, permissions, and operational recovery.
7. Every other unresolved item in the decision matrix.

## Decision 10 — Validation State Machine and Readiness Transitions

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval:** Explicitly approved by the user as a policy direction.
- **Implementation authorization:** Not granted.

### Approved principles

1. Readiness is never caller-assigned; trusted backend logic may promote an
   asset to `ready` only after verifying authoritative evidence for the exact
   immutable version.
2. State transitions are controlled; clients cannot set trusted states
   directly.
3. Failed, rejected, incomplete, or unverifiable validation cannot result in
   trusted use.
4. Stale results cannot change readiness unless the version, expected state,
   revision, and validation-attempt ID match, consistent with Decision 7.
5. Superseded versions remain distinct; replacement uploads must not silently
   alter an existing version's identity or evidence.
6. Render-job submission and execution recheck authorization and required asset
   version/readiness; historical validation success alone is insufficient.
7. Applicable account, project, disablement, and deletion restrictions take
   precedence over trusted use.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following state-machine and implementation details remain **OPEN —
APPROVAL REQUIRED**:

1. Exact state names, the complete transition table, and which transitions are
   user-, service-, or system-initiated.
2. Retry semantics, timeouts, cancellation, recovery, and late or duplicate
   validation-result handling.
3. CAS fields, revision semantics, transaction boundaries, and concurrency
   mechanics.
4. Revalidation requirements and how readiness or evidence is revoked or
   superseded.
5. Render-job submission, execution, and in-flight job behavior.
6. Lease and deletion coordination, including failure recovery.
7. Persistence, monitoring, audit behavior, and deployment-specific controls.
8. Every other unresolved item in the decision matrix.

## Proposed decisions for review

This section records policy topics and their current status. Candidate A and
Candidate B's policy directions are approved below; neither status authorizes
implementation, and unresolved requirements remain **OPEN — APPROVAL
REQUIRED**.

### Candidate A — Production Render/Output Contract

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval:** Explicitly approved by the user as a policy direction.
- **Implementation authorization:** Not granted.

### Approved principles

1. Define the production output profiles intended to be supported.
2. Define the production media formats intended to be supported.
3. Define output delivery behavior.
4. Define output access behavior.
5. Define user-visible failure expectations.
6. Define user-visible cancellation expectations.

These are approved policy directions, not verified renderer capabilities or
output guarantees. The integration contract describes a proposed profile; the
existing renderer does not establish that profile as a production capability.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following details remain **OPEN — APPROVAL REQUIRED**: exact output
profiles and formats; renderer capabilities and implementation; operational
behavior; storage and delivery design; retention; resource limits; and
deployment configuration. Related matrix topics include production limits,
output retention, deletion during jobs, and lease/job handoff. This approval
does not replace or resolve those entries.

### Candidate B — User Content Rights and Acceptable-Use Handling

**Status: Approved policy direction — implementation pending.**

- **Approval date:** 2026-10-25
- **Approval:** Explicitly approved by the user as a policy direction.
- **Implementation authorization:** Not granted.

### Approved principles

1. Users must confirm they have the necessary rights to uploaded assets.
2. A defined complaint-handling process is required before public launch.
3. Acceptable-use rules must be documented.
4. Review and enforcement rules must be defined.
5. Policy must not be misrepresented as implemented capability.

### Decisions that remain OPEN — APPROVAL REQUIRED

The following legal, policy, moderation, and operational details remain
**OPEN — APPROVAL REQUIRED**:

1. The precise rights confirmation, its scope, and the applicable legal review.
2. Acceptable-use rules and prohibited-content scope.
3. Complaint intake, review, escalation, enforcement, and appeal processes.
4. Privacy requirements, data handling, and retention.
5. Operational ownership, response expectations, and deployment-specific
   implementation.
6. Every other unresolved item in the decision matrix.

This approval does not establish legal compliance or implement automated
moderation or operational complaint handling. The existing audit/privacy/
incident-response matrix topic remains open and is not resolved by this
direction.

## Master architecture register

### Approved policy directions

Decision 1 and Decisions 3–10 have the status **Approved policy direction —
implementation pending**. Decision 2 has the status **Provider approved —
implementation pending** (Clerk selection only). Candidate A and Candidate B
also have **Approved policy direction — implementation pending** status. Each
approval record says implementation authorization is not granted. These
statuses record policy direction, not existing runtime controls.

### Scoped approvals within still-open matrix rows

The following approvals settle only the stated policy direction or technical
principle. They do not resolve the full matrix row or establish implemented
controls. Implementation authorization is stated separately in each approval
record and is limited to its recorded scope. The explicit OD-01–OD-04, OD-07–OD-10,
OD-12–OD-13, and OD-15–OD-18 approvals were provided in the governance
decision lists; those lists supplied no approval dates, so none is inferred
here.

- **OD-01 — Approved scope:** Individual-user ownership and owner-only project
  access in v1; a narrowly controlled administrative project-ownership
  transfer is permitted in principle. **Still open:** administrator
  authorization, identity verification, approvals, audit requirements and
  safeguards; persistent ownership mapping and ID implementation details.
- **OD-01 — Project-level approval record (2026-11-01):** Ashishkumar Maurya,
  Project Owner and Maker, is the decision owner and authorized approver for
  this recorded scope. Approved: backend-generated project IDs (identifiers,
  not credentials); an internal `owner_user_id`; authenticated create/list/get
  with server-side owner checks; no sharing or ownership transfer in the
  initial scope; no seeding or silent assignment of `sample-northstar`; and
  a required trimmed, bounded project `name`; reject client-supplied ownership
  fields. Non-owned and unknown project IDs return the same `404` response,
  with no project data and no mutation. The implementation stack is approved
  as SQLAlchemy 2.x, Alembic and a PostgreSQL driver, subject to repository
  compatibility and dependency review. Use versioned migrations only through
  an explicit controlled setup/release command, never at import, startup or
  per request. Developer-controlled local PostgreSQL is approved for
  development and database integration tests. Keep `sample-northstar`
  illustrative and unseeded; existing demo render and preproduction
  evaluation flows remain unchanged. Implementation is authorized only within
  this recorded scope. The database provider and production deployment
  configuration remain open, as do detailed schema and recovery questions.
- **PostgreSQL approval record (2026-11-01):** Ashishkumar Maurya — Project
  Owner and Maker — approved PostgreSQL as the project's persistence technology
  at project level. This does not select a database provider or deployment
  configuration.
- **Additional OD-01 approvals (2026-11-01):** The same decision owner
  approved `404` for both unknown and non-owned project IDs, with no project
  data or mutation; a required trimmed, bounded `name` with project ID and
  `owner_user_id` generated/derived server-side and client ownership fields
  rejected; SQLAlchemy 2.x, Alembic and a PostgreSQL driver as the proposed
  implementation stack subject to compatibility/dependency review; explicit
  controlled migration execution only; and developer-controlled local
  PostgreSQL for development and integration tests. No hosted provider or
  production deployment configuration is selected.
- **OD-02 — Approved scope:** Server-side Clerk user-session token
  verification with fail-closed behavior; use verified `iss` + `sub` to
  resolve the canonical internal Spotloom `user_id`; keep project
  authorization separate and server-side; align with the approved session
  lifecycle and revocation direction. Clerk remains selected. **Still open:**
  deployment-specific issuer, audience/`azp` and authorized-party values,
  verifier configuration, session/revocation behavior, and deployment settings.
- **OD-02 — Project-level approval record (2026-11-01):** Ashishkumar Maurya,
  Project Owner and Maker, is the decision owner and authorized approver for
  the proposed v1 contract matching the current implementation, subject to the
  documented authentication contract and limitations. This covers
  server-verified Clerk session tokens, fail-closed signature/algorithm,
  issuer, applicable audience/authorized-party, expiry/not-before and
  required identity/time-claim checks; verified `(issuer, subject)` only;
  separate server-side project authorization; and documented offline-JWT
  revocation limitations. Implementation is authorized only within this
  scope. Concrete production configuration and session/revocation behavior,
  and other OD-02 open details remain unresolved.
- **OD-03 — Approved scope:** Only a dedicated trusted validation service
  with its own least-privilege identity may issue authoritative validation
  evidence. Evidence must be protected against forgery and unauthorized
  modification, with authority, integrity and revocation rules defined.
  Parsers and processing workers cannot independently issue authoritative
  evidence or promote readiness. **Still open:** the concrete evidence
  authentication/integrity mechanism, authority configuration, revocation
  mechanics and deployment isolation.
- **OD-04 — Approved scope:** Evidence binds project ID, asset ID, immutable
  version ID, authoritative object reference, SHA-256 digest, actual byte
  count, observed media properties, validation profile/policy version, a
  unique validation-attempt ID, and an evidence revision or equivalent
  lifecycle reference to the exact immutable version and bytes inspected.
  Only the authorized trusted backend lifecycle authority may revoke or
  supersede accepted evidence; preserve historical evidence for audit. Stale
  or mismatched evidence must not promote readiness or overwrite newer
  results. **Still open:** evidence serialization/version mechanics,
  authoritative persistence, credential custody and deployment controls.

- **OD-07 — Approved scope:** Use a bounded parser and a documented allowlist
  of ancillary chunks that can safely be validated and skipped. Reject
  malformed, truncated, inconsistent or unsupported variants until
  deliberately supported. Validate compatibility against the target client
  media corpus before relying on the parser in a trusted validation worker.
  **Still open:** exact corpus and test results, specific supported chunks
  and parser behavior, and engineering verification of bounds and
  compatibility.
- **OD-08 — Approved scope:** Enforce upload byte limits while streaming;
  control validation-worker concurrency separately from upload concurrency;
  fail closed when required limit configuration is missing or invalid.
  **Still open:** production byte/duration and active-upload/concurrency
  limits, infrastructure capacity, abuse-resistance review, and deployment
  configuration/enforcement evidence. 25 MiB, 60 seconds and two concurrent
  validations remain provisional development values only.
- **OD-09 — Approved scope:** Count all stored versions, retained or
  logically deleted bytes not physically removed, and reserved in-flight
  uploads in quota accounting. Reject new uploads or reservations that would
  exceed quota; never silently exceed it. Fail closed when required quota
  configuration is missing or invalid. **Still open:** production quota
  size/capacity, infrastructure and storage-accounting guarantees, exact
  accounting/reservation-release/reconciliation mechanics, and any
  product/plan-specific considerations. 500 MiB remains a provisional
  development default only.

- **OD-10 — Approved scope:** Require private storage, stable immutable
  version IDs, exact-version reads, conditional writes, and controlled
  deletion/retention capabilities. Never substitute a “latest” object for
  the version pinned by validation or rendering. **Still open:** provider
  selection and infrastructure-owner verification of these guarantees.
- **OD-12 — Approved scope:** Logical deletion blocks new leases and
  protected operations. An existing valid lease may permit an already-
  authorized job to finish unless a stronger security or authorization
  restriction requires stopping it. Delay physical deletion until active
  leases no longer require the object and applicable retention obligations
  are satisfied. Preserve enough tombstone state to prevent stale workers
  restoring readiness; bound lease expiry and provide abandoned-job recovery.
  **Still open:** retention periods, backup behavior, legal/privacy
  requirements, and operational guarantees.
- **OD-13 — Approved scope:** Define retention for assets, versions, evidence,
  job records, audit history, outputs, and backups. Logical deletion
  immediately restricts access under the approved deletion policy; physical
  cleanup respects leases, retention obligations, and backup/recovery
  requirements. Primary-object deletion is not represented as erasing every
  backup. **Still open:** durations, legal/privacy requirements, backup
  architecture, and recovery guarantees for responsible owners.
- **OD-15 — Approved scope:** Require authoritative atomic handoff of the
  complete immutable job snapshot and required leases, with an idempotency
  mechanism and exact private object-version pins. Prevent partial job
  creation, duplicate/conflicting leases, stale ownership, or deletion races
  from escaping authoritative coordination. **Still open:** database/queue/
  storage transaction capabilities, outbox mechanics, persistence, and
  engineering implementation design.
- **OD-16 — Approved scope:** Bound lease lifetime; renew only under explicit
  state and authority checks; release on terminal job state; recover
  abandoned work and prevent stale workers from publishing output or
  changing authoritative state; coordinate cleanup with valid leases and
  approved deletion policy. **Still open:** durations, renewal cadence,
  reaper/recovery mechanics, and operational guarantees.
- **OD-17 — Approved scope:** Keep storage private and protect data in
  transit and at rest; require deployment-approved encryption and key
  management; separate asset, validation, and rendering services into
  distinct least-privilege identities; keep privileged storage credentials
  away from untrusted parsing workers. **Still open:** concrete controls,
  deployment configuration, and security/infrastructure-owner verification.
- **OD-18 — Approved scope:** Record bounded, redacted security and lifecycle
  events needed for accountability and incident investigation; do not log
  uploaded media, secrets, or raw caller-supplied filenames; define audit
  access, retention, operational ownership, and incident-response procedures.
  **Still open:** privacy jurisdiction, retention periods, legal obligations,
  and operational specifics for legal, privacy, security, and deployment
  owners.

The following directions were already recorded by their distinct approved
decisions; they are cross-referenced here rather than assigned duplicate
decision identities:

- **OD-05 — Decisions 7 and 10:** Each validation attempt has a unique ID;
  retries are new attempts; only the current matching attempt may change
  readiness; retries are bounded; permanent failures do not retry
  indefinitely; late results cannot bypass rejected/deleted state; uncertain
  state fails closed. Exact retry/failure behavior and CAS mechanics remain
  open.
- **OD-06 — Decisions 7 and 10:** Readiness has an explicit state/evidence
  revision; old evidence is preserved; revalidation may issue new evidence
  for the same immutable version only after exact-version verification;
  changed bytes require a new immutable version; old evidence alone cannot
  restore readiness; lifecycle restrictions take precedence. Remaining
  revalidation and revocation mechanics remain open.
- **OD-11 — Decisions 7 and 8:** SHA-256 covers the exact finalized
  immutable stored bytes; actual byte count comes from that same read; both
  bind to the exact asset version and validation attempt; later reads recheck
  digest and byte count; mismatch or unverifiable reads fail closed. Exact
  streaming implementation, interrupted-read handling, persistence, retries,
  production integration and deployment verification remain open.
- **OD-14 — Decisions 5, 6 and 10:** Logical deletion and expiration prevent
  new leases; an existing job may finish only with a valid lease and under
  applicable policy; a security or authorization revocation takes precedence
  when continued access is prohibited. Lease validity and job behavior
  details remain open.

### Proposed policy topics awaiting approval

There are currently no candidate headings with a proposed/pending-approval
status: Candidates A and B have approved policy directions. Their unresolved
requirements remain open below and in the matrix; approval did not select
profiles, legal rules, moderation mechanisms, or implementation details.

### Open policy decisions

The open matrix contains 18 uniquely identified register entries, `OD-01` to
`OD-18`. Fourteen contain policy or product/legal/security-owner decisions
that require explicit resolution: `OD-01`–`OD-09`, `OD-12`–`OD-14`, `OD-16`,
and `OD-18`. This count refers to entries with policy questions, not to
fourteen separate approval events; details overlap and are cross-referenced in
the routing register below.

### Open technical and deployment choices

All 18 entries also contain or depend on implementation/deployment choices.
The primary technical/deployment-owner choices are `OD-10`, `OD-11`,
`OD-15`, and `OD-17`; the other entries also require engineering design after
their policy constraints are settled. Engineering may choose implementation
mechanics only within approved policy and deployment constraints.

### Deferred or blocked items

The routing register assigns each entry a disposition. Entries awaiting
infrastructure, product, security, or legal-owner facts are marked **Blocked
pending owner input**; entries ready for policy or engineering resolution are
marked **Open**. No matrix entry is marked resolved. No row is currently
proposed for deferral. Team/workspace sharing remains outside v1 under
Decision 1 and would require a separately reviewed policy change.

### Register counts and counting rules

- **Recorded approved policy directions:** 11 — Decisions 1 and 3–10, plus
  Candidates A and B. **Provider approval:** 1 — Decision 2 approves Clerk
  selection only. These are 12 approved recorded directions/selections, not
  implementation approvals.
- **Named topics awaiting policy approval:** 0. Candidates A and B are now
  approved at direction level; their unresolved requirements remain open.
- **Matrix rows with an approved scoped direction recorded:** 18 (`OD-01`–
  `OD-18`). This counts rows with at least one approved principle, not closed
  rows; each remains open for its listed remainder.
- **Open matrix rows:** 18. Each source matrix row is one stable `OD-*`
  register entry. Under this row-level counting rule, there are 18 unique
  unresolved register entries, not 18 independent approval events. The
  overlap notes below identify related entries without deleting or merging
  them.
- **Policy-bearing open entries:** 14 (`OD-01`–`OD-09`, `OD-12`–`OD-14`,
  `OD-16`, `OD-18`). **Primarily technical/deployment-owner entries:** 4
  (`OD-10`, `OD-11`, `OD-15`, `OD-17`). The categories describe the primary
  resolution route and are not extra rows; engineering work remains across
  all entries.
- **Disposition totals:** 4 **Open** (`OD-05`, `OD-06`, `OD-11`, `OD-14`);
  14 **Blocked pending owner input**; 0 **Proposed for deferral**; 0
  **Resolved by explicit recorded approval**. A recorded approval resolves
  only the principle it states, not an entire related matrix row.
- **Implementation workstreams:** 9 dependency-ordered workstreams below.
  They are delivery groupings, not policy decisions or authorization.

## Open decision matrix

Every row remains **OPEN — APPROVAL REQUIRED** for its unresolved remainder.
An approved scoped direction below or above this matrix does not resolve all
sub-decisions in that row. The stable `OD-*` identifier is a register
reference, not a new decision number. Unapproved recommendations remain
proposals. “Deployment-specific” identifies choices requiring
infrastructure/deployment-owner input; it does not select a provider or policy.

| Register ID and decision required | Recorded policy direction / recommended default and rationale | Consequences if unresolved | Deployment-specific? | Implementation that must wait | Approval status |
|---|---|---|---|---|---|
| OD-01 — Canonical tenant/project model, project ownership administration, and ID namespace | **Approved project-level scope (2026-11-01):** backend-generated project IDs and server-derived `owner_user_id`; authenticated create/list/get with owner checks; required trimmed bounded `name`; reject client ownership fields; identical `404` for unknown and non-owned IDs with no data/mutation; no initial sharing/transfer or demo seeding; SQLAlchemy 2.x, Alembic and PostgreSQL driver proposed subject to compatibility/dependency review; explicit controlled versioned migrations; developer-controlled local PostgreSQL for development/tests. Identity mapping follows the scoped Decision 3 approval. Implementation authorization is limited to this scope. Hosted provider and production configuration remain unselected; detailed schema and recovery remain open. | Persistence behavior and owner isolation must be tested; hosted provider and deployment choices must not be inferred from the project-level PostgreSQL approval. | **Yes:** provider/deployment configuration requires infrastructure-owner input; detailed schema and lifecycle questions remain open. | Persistent identity and project records, authenticated project APIs, and migrations. | **OPEN — APPROVAL REQUIRED** |
| OD-02 — Authenticated-principal and token-validation contract | Clerk is approved as the managed identity provider for v1 in Decision 2. **Approved at project level (2026-11-01):** the proposed v1 contract matching the current implementation, subject to the documented authentication contract and limitations: server-verified Clerk session tokens; fail-closed signature/algorithm, configured issuer, applicable audience/authorized-party, expiry/not-before and required identity/time-claim checks; verified issuer/subject only; separate server-side authorization; and documented offline-JWT limitations. Implementation is authorized only within this scope. Concrete production configuration and session/revocation behavior remain open. | Invalid or misinterpreted credentials could permit unauthorized access or cross-project disclosure; no trustworthy attribution. | **Yes:** exact token/configuration and revocation behavior depend on deployment. | Authenticated project APIs and any user-facing asset/resolve/render endpoint. | **OPEN — APPROVAL REQUIRED** |
| OD-03 — Authoritative validation service boundary and evidence authentication | Permit evidence creation only to an isolated, least-privilege trusted validation service; use the approved private service boundary for v1. Add signatures only if trust crosses a boundary that cannot be secured by that service boundary. | Caller-constructed models or compromised callers could falsely assert readiness. | **Yes:** depends on service isolation, deployment boundary, and credential/key custody. | Trusted validation worker, authoritative readiness transition, readiness-based resolver. | **OPEN — APPROVAL REQUIRED** |
| OD-04 — Evidence schema version, binding fields, and revocation authority | Version the evidence envelope and bind project, asset, immutable version, private object version, verified digest/size, observed media profile, validator identity/version, timestamp, and evidence revision. Keep revocation separate and auditable. | Evidence can be stale, detached from bytes, or impossible to revoke safely. | **Partly:** schema is shared; validator identity and evidence storage are deployment-specific. | Trusted evidence contract and worker; readiness revocation. | **OPEN — APPROVAL REQUIRED** |
| OD-05 — Lifecycle retries, rejected-version revalidation, and attempt policy | Give each validation attempt a unique ID; use approved CAS tuple; make stale results no-ops. Define bounded retries and do not allow rejection/deletion to be bypassed by late workers. | Late or duplicate workers may overwrite newer state; retry behavior may be inconsistent or unbounded. | **Partly:** retry policy is product/operations-specific; CAS mechanics are implementation-specific. | Persistent lifecycle service and validation worker. | **OPEN — APPROVAL REQUIRED** |
| OD-06 — Readiness revocation and revalidation of an immutable version | Revoke readiness through an explicit state/evidence revision; never mutate old evidence. Revalidation may issue new evidence for the same immutable version only after exact-version and byte verification; changed bytes require a new immutable version; old evidence alone cannot restore readiness. Implementation, persistence, and revocation mechanics remain unresolved. | Stale evidence may remain usable, or revalidation may accept bytes that differ from the pinned immutable version. | **No, primarily product/security policy.** | Evidence/lifecycle contract and resolver checks. | **OPEN — APPROVAL REQUIRED** |
| OD-07 — RIFF/WAVE ancillary chunks, variants, and parser compatibility | **Approved policy:** use a bounded parser and documented ancillary-chunk allowlist; reject malformed, truncated, inconsistent or unsupported variants until deliberately supported; validate against the target client corpus before trusted-worker use. **Still open:** exact corpus/results, supported chunks and parser behavior, and engineering bounds/compatibility verification. | Permissive parsing creates ambiguity/security risk; overly strict parsing may reject expected user files. | **No, but target corpus and compatibility review require product/media-owner input.** | Trusted validation worker pending corpus review and parser verification. | **OPEN — APPROVAL REQUIRED** |
| OD-08 — Production maximum upload bytes, audio duration, active uploads, and validation concurrency | **Approved principles:** enforce byte limits while streaming, separate upload and validation-worker concurrency controls, and fail closed on missing/invalid required configuration. **Still open:** production values, capacity and abuse review. 25 MiB, 60 seconds and two concurrent validations remain provisional only. | Unbounded cost, storage consumption, parser work, or denial-of-service exposure; arbitrary limits can reject legitimate work. | **Yes:** capacity and abuse envelope depend on deployment. | Production upload API and validator deployment. | **OPEN — APPROVAL REQUIRED** |
| OD-09 — Project quota, quota dimensions, and overage behavior | **Approved policy:** count all stored versions, retained/logically deleted bytes not physically removed, and reserved in-flight uploads; reject over-quota uploads/reservations; never silently exceed quota; fail closed on missing/invalid required configuration. **Still open:** production quota/capacity, accounting guarantees and mechanics, reservation release/reconciliation, and product/plan considerations. 500 MiB is provisional only. | Users may exceed available capacity or receive inconsistent enforcement and billing behavior. | **Yes:** capacity and plan model are deployment/product-specific. | Storage accounting, upload API, quota enforcement. | **OPEN — APPROVAL REQUIRED** |
| OD-10 — Storage provider and immutable object-version guarantees | **Approved principles:** private storage, stable immutable version IDs, exact-version reads, conditional writes, controlled deletion/retention, and no substitution of “latest.” **Still open:** provider selection and infrastructure-owner proof of the required guarantees. | Package pins may resolve to changed bytes or disappear between resolution and use. | **Yes; infrastructure-owner input required.** | Storage adapter, upload finalization, resolver. | **OPEN — APPROVAL REQUIRED** |
| OD-11 — Digest algorithm and byte-size verification | Use SHA-256 over the exact finalized immutable bytes; measure actual byte count from that same read and bind both to the exact version and validation attempt. Reverify subsequent reads and fail closed on mismatch or unverifiable reads. **Still open:** streaming implementation, interrupted-read handling, persistence, retries and production integration. A digest does not provide availability or authorization. | Different components may hash different byte ranges or accept unverified caller declarations. | **Partly:** algorithm is contract-wide; verification path depends on storage/deployment. | Trusted validator, evidence contract, object read path. | **OPEN — APPROVAL REQUIRED** |
| OD-12 — Logical deletion, cleanup grace, tombstones, and physical deletion | **Approved principles:** logical deletion blocks new leases/protected operations; a valid existing lease may permit an already-authorized job to finish unless stronger security/authorization restrictions require stopping it; delay physical deletion until leases no longer require the object and retention obligations are satisfied; preserve tombstone state against stale readiness restoration; bound lease expiry and recover abandoned jobs. **Still open:** retention periods, backup behavior, legal/privacy requirements and operational guarantees. | Deletion promises, privacy obligations, and storage cleanup may conflict or be unverifiable. | **Yes:** legal, privacy, backup, and storage capabilities vary. | Lifecycle persistence, cleanup worker, storage deletion. | **OPEN — APPROVAL REQUIRED** |
| OD-13 — Retention periods and deletion from backups | **Approved principles:** define retention for assets, versions, evidence, job records, audit history, outputs and backups; logical deletion restricts access immediately; physical cleanup respects leases, retention obligations and backup/recovery requirements; deleting a primary object does not imply every backup is erased. **Still open:** durations, legal/privacy requirements, backup architecture and recovery guarantees. | Data may persist longer than intended or be deleted before obligations/jobs end. | **Yes; legal/privacy and infrastructure-owner input required.** | Production storage, backup configuration, cleanup and audit processes. | **OPEN — APPROVAL REQUIRED** |
| OD-14 — Deletion or expiration during a render job | Honor approved rule: an already-authorized job may finish only with a valid existing lease; no new lease after logical deletion. Decide whether expiration follows the same rule and how revocation affects active jobs. | Jobs may lose inputs mid-run, or deleted content may remain available longer than intended. | **Partly:** policy is product/security; enforcement depends on storage/job infrastructure. | Lease service, job handoff, worker reads, cleanup. | **OPEN — APPROVAL REQUIRED** |
| OD-15 — Lease creation/idempotency and atomic job handoff | **Approved principles:** authoritative atomic handoff of the complete immutable job snapshot and required leases; idempotency; exact private object-version pins; no partial or conflicting job/lease creation, stale ownership, or uncoordinated deletion race. **Still open:** database/queue/storage transaction capabilities, outbox mechanics, persistence, and engineering design. | Partial jobs or duplicate leases may escape; assets can be deleted between resolution and use. | **Partly:** transaction boundary depends on chosen database/queue/storage. | Job repository/outbox, lease service, rendering integration. | **OPEN — APPROVAL REQUIRED** |
| OD-16 — Lease expiry, renewal, recovery, release, and cleanup | **Approved principles:** bound lease lifetime; renew only under explicit state and authority checks; release on terminal job state; recover abandoned work; prevent stale workers publishing output or changing authoritative state; coordinate cleanup with valid leases and approved deletion. **Still open:** durations, renewal cadence, reaper/recovery mechanics, and operational guarantees. | Leases may block deletion indefinitely or expire while a legitimate job is running. | **Yes:** worker duration and operational recovery capabilities matter. | Lease service, job lifecycle, physical deletion. | **OPEN — APPROVAL REQUIRED** |
| OD-17 — Encryption, KMS, service identities, and worker isolation | **Approved principles:** private storage, protection in transit and at rest, deployment-approved encryption/key management, distinct least-privilege asset/validation/render identities, and no privileged storage credentials in untrusted parsing workers. **Still open:** concrete controls, deployment configuration and owner verification. | Credential compromise or data exposure can cross project boundaries and undermine evidence trust. | **Yes; security/infrastructure-owner approval required.** | Production storage, upload/validation deployment, authenticated APIs, rendering workers. | **OPEN — APPROVAL REQUIRED** |
| OD-18 — Audit access/retention, privacy jurisdiction, and incident response | **Approved principles:** bounded, redacted security/lifecycle events for accountability and investigation; never log media, secrets, or raw caller filenames; define audit access, retention, ownership and incident response. **Still open:** privacy jurisdiction, retention periods, legal obligations and operational specifics. | Incidents may be untraceable, or logs may expose sensitive data and be retained improperly. | **Yes; security, legal, privacy, and deployment-owner approval required.** | Production APIs, storage/lifecycle services, operations and incident response. | **OPEN — APPROVAL REQUIRED** |

## Open-entry routing and disposition register

The IDs below map one-to-one to the 18 matrix rows above. The matrix's
**OPEN — APPROVAL REQUIRED** statuses remain in force for unresolved details;
the scoped OD-01 and OD-02 approvals below do not close either row.
Dependencies identify prerequisites, not additional approvals. Where owner
input is required, an engineering choice alone is insufficient. “Open” means
the topic can be reviewed against current known facts; it does not imply
implementation readiness.

| ID | Related decisions / dependencies | Resolution authority: user policy, engineering, or owner input | Disposition |
|---|---|---|---|
| OD-01 | Decisions 1 and 3; prerequisite to OD-02, OD-03, OD-10 and user-facing asset operations. | Project access response, creation fields, stack, controlled migration mode and local PostgreSQL development use are approved by Ashishkumar Maurya, Project Owner and Maker, on 2026-11-01; implementation remains scoped. Hosted provider/deployment configuration, detailed schema and other lifecycle items remain open. | **Blocked pending owner input** |
| OD-02 | Decisions 1–5; depends on verified identity mapping in Decision 3 and OD-01. | The proposed v1 verifier contract matching the current implementation is approved by Ashishkumar Maurya, Project Owner and Maker, on 2026-11-01; implementation is authorized within that contract and its documented limitations. Concrete production configuration and revocation/session behavior remain open. | **Blocked pending owner input** |
| OD-03 | Decisions 1, 7 and 8; depends on identity/authorization (OD-01/02), storage boundary (OD-10) and service isolation (OD-17). | Dedicated least-privilege validation-service authority and protection of evidence against forgery/modification are approved. Security/infrastructure owner must establish the concrete integrity/authentication mechanism, service identity and isolation. | **Blocked pending owner input** |
| OD-04 | Decisions 7 and 8; depends on OD-03 and exact-byte/digest procedure OD-11. | Evidence fields, exact-version/bytes binding, historical preservation, and stale/mismatch rejection are approved. Engineering defines serialization and persistence; owner input remains required for authority/integrity and deployment controls. | **Blocked pending owner input** |
| OD-05 | Decisions 7 and 10; depends on durable state/revision design and OD-04 evidence binding. | Unique attempts, retries as new attempts, current-attempt-only readiness changes, bounded retries, no indefinite retries for permanent failures, stale-result rejection, and fail-closed uncertainty are approved. Engineering selects CAS/retry mechanics within those bounds; policy changes require explicit approval. | **Open** |
| OD-06 | Decisions 7 and 10; depends on evidence revisions OD-04 and lifecycle attempts OD-05. | Explicit readiness/evidence revision, preserved historical evidence, exact-version verification for same-version revalidation, new version for changed bytes, and no restoration by old evidence are approved. Engineering specifies transition and revision mechanics; changing the direction requires explicit approval. | **Open** |
| OD-07 | WAV profile in the approved policy and `docs/wav-compatibility-matrix.md`; required before trusted validator acceptance. | Bounded-parser/allowlist direction approved. Product/media owner supplies target corpus and compatibility input; engineering verifies bounds and parser behavior. Approval is required for any policy expansion of supported variants. | **Blocked pending owner input** |
| OD-08 | Decision 9 and deployment capacity; also interacts with OD-09 and validation-worker design. | Streaming bounds, separate concurrency controls and fail-closed configuration approved. Product/security and infrastructure owners must resolve production values, capacity and abuse resistance. | **Blocked pending owner input** |
| OD-09 | Decisions 1, 6 and 9; depends on project ownership (OD-01), OD-08, storage and retention (OD-10/13). | Quota accounting scope, reject-on-exceed and fail-closed principles approved. Product/plan and infrastructure/storage owners must resolve quota size, capacity and accounting/reconciliation guarantees. | **Blocked pending owner input** |
| OD-10 | Decisions 8 and 9; prerequisite to upload finalization, validation reads, OD-11, resolution and leases. | Private storage, immutable version IDs, exact reads, conditional writes, and controlled deletion/retention are approved requirements. Infrastructure owner selects a provider/configuration and proves those capabilities; any weakening requires explicit policy approval. | **Blocked pending owner input** |
| OD-11 | Decisions 7 and 8; depends on exact immutable reads in OD-10 and is required by evidence binding OD-04. | SHA-256 over the exact finalized bytes, byte count from the same read, binding to version/attempt, later-read rechecks, and fail-closed mismatch handling are approved directions. Engineering defines the procedure and infrastructure/security owners verify enforceability; changing the algorithm or weakening the rule requires explicit approval. | **Open** |
| OD-12 | Decisions 6, 8 and 9; depends on retention OD-13 and lease rules OD-16. | Logical-blocking, existing-valid-lease, retention-aware physical-cleanup, stale-worker tombstone, bounded-lease and abandoned-job recovery principles are approved. Legal/privacy requirements, retention periods, backup behavior and storage cleanup guarantees require owner input. | **Blocked pending owner input** |
| OD-13 | Decisions 6, Candidate B and OD-12; applies to source versions, failed uploads, evidence, backups and outputs. | Coverage areas and rule that deletion does not imply all backups are erased are approved. Product/legal/privacy owners must resolve durations and obligations; infrastructure owners confirm backup architecture and enforceability. | **Blocked pending owner input** |
| OD-14 | Decisions 5, 6 and 10; depends on lease and atomic handoff behavior OD-15/16 and OD-12/13. | No new lease after logical deletion/expiration; an existing job may finish only under a valid lease and applicable policy; security/authorization revocation takes precedence when continued access is prohibited. These directions are approved; exact lease validity and job behavior remain open. | **Open** |
| OD-15 | Decisions 5, 6, 8 and 10; depends on storage/version pins OD-10 and transaction capabilities of the chosen persistence/queue systems. | Atomic authoritative handoff, idempotency and complete exact-version job snapshot requirements are approved. Engineering designs mechanics; database, queue and storage owners confirm transaction guarantees. | **Blocked pending owner input** |
| OD-16 | Decisions 6 and 8; required by OD-12, OD-14 and OD-15. | Bounded lease, guarded renewal, terminal release, abandoned-work recovery and stale-worker safeguards are approved. Operations/infrastructure owners define durations and prove recovery/cleanup behavior. | **Blocked pending owner input** |
| OD-17 | Decisions 1, 2, 7 and 8; prerequisite to trusted service boundary OD-03 and protected storage. | Private storage, encryption/key-management requirements, separate least-privilege identities and parser credential isolation are approved. Security/infrastructure owner selects and verifies concrete deployment controls; policy approval is needed for any weakening. | **Blocked pending owner input** |
| OD-18 | Candidate B, Decisions 1, 6 and 7; overlaps privacy/retention OD-13 and deployment controls OD-17. | Bounded/redacted event principles and prohibited log contents are approved. Legal/privacy/security and deployment owners must define jurisdiction, retention, access, ownership and incident-response specifics. | **Blocked pending owner input** |

### Owner, evidence, and phase routing metadata

The OD dependencies and dispositions above remain authoritative and unchanged;
the `Dependencies` column below points back to those entries rather than
repeating their dependency text. Candidate A and Candidate B are added as
separate routing topics and do not alter the OD matrix or its counts. Proposed
roles are suggestions, not assignments. `Proposed` means the role is suggested
but no acceptance is recorded; no row is `Confirmed`. “Decision owner” means a
role expected to resolve policy or owner input, while “contributors” provide
engineering or operational evidence. Phase labels identify affected work,
not blanket blockers for unrelated phases. Isolated prototypes may use only
explicitly provisional development settings and do not establish production
readiness. Proposed decision-owner roles are not accepted assignments. The
review/approval areas below identify required expertise or authority for the
open remainder; they do not identify confirmed reviewers or approvers. No
reviewer, approver, or implementation owner is confirmed for any row:
**UNASSIGNED — OWNER CONFIRMATION REQUIRED**. Implementation ownership is
separate from decision ownership and technical contribution.

| ID / short topic | Proposed decision owner role(s); contributors | Assignment status | Dependencies (reference to existing routing row) | Required evidence / next-action type | Phase affected | Authoritative source reference | Required approval/review area(s) for open remainder |
|---|---|---|---|---|---|---|---|
| OD-01 — Ownership model | Decision owner/approver: Ashishkumar Maurya (Project Owner and Maker); contributors: Identity/security, Backend/architecture | Confirmed for recorded scope | OD-01 row above | Design/evidence: schema constraints, uniqueness, foreign keys and tests; infrastructure-owner confirmation: hosted provider/deployment configuration if needed. | Trusted implementation; render integration; production launch | Decision 1; Decision 3; OD-01 matrix row | Product/policy; Identity/security; Infrastructure/storage |
| OD-02 — Principal/token contract | Decision owner/approver: Ashishkumar Maurya (Project Owner and Maker); contributors: Backend/architecture | Confirmed for recorded scope | OD-02 row above | Evidence: tests for approved verifier contract; owner input: deployment configuration and session/revocation behavior. | Trusted implementation; render integration; production launch | Decisions 2–5; OD-02 matrix row | Identity/security; Product/policy |
| OD-03 — Evidence issuer trust | Decision owner: Identity/security; contributors: Infrastructure/storage, Backend/architecture | Proposed | OD-03 row above | Owner decision: service authority and credential boundary; proof of capability: prevent caller/worker evidence forgery or modification. | Trusted implementation; render integration; production launch | Decision 7; OD-03 matrix row | Security; Infrastructure/storage |
| OD-04 — Evidence envelope/revocation | Decision owner: Backend/architecture; contributors: Identity/security, Infrastructure/storage | Proposed | OD-04 row above | Design: versioned evidence and revocation records; testing: exact bindings, stale/mismatch rejection, history preservation. | Trusted implementation; render integration | Decision 7; OD-04 matrix row | Security; Backend/architecture |
| OD-05 — Attempts/retry policy | Decision owner: Product/policy, Operations/reliability; contributors: Backend/architecture | Proposed | OD-05 row above | Design: CAS/retry contract; testing: bounded retries, permanent failure, duplicate and stale-result races. | Trusted implementation; render integration | Decisions 7 and 10; OD-05 matrix row | Product/policy; Operations/reliability; Backend/architecture |
| OD-06 — Readiness revocation/revalidation | Decision owner: Identity/security; contributors: Backend/architecture | Proposed | OD-06 row above | Design and testing: exact-version/byte revalidation, evidence revisions, and proof that old evidence cannot restore readiness. | Trusted implementation; render integration | Decisions 7 and 10; OD-06 matrix row | Security; Backend/architecture |
| OD-07 — WAV compatibility | Decision owner: Product/policy or media compatibility; contributors: Engineering | Proposed | OD-07 row above | Owner input: target client corpus and supported chunk behavior; testing: parser bounds and compatibility. | Trusted implementation; production launch | Decision 7; OD-07 matrix row; WAV compatibility matrix | Product/policy; Media compatibility; Engineering |
| OD-08 — Upload/concurrency limits | Decision owner: Product/policy, Security, Infrastructure/storage; contributors: Operations/reliability | Proposed | OD-08 row above | Owner decision: production values/capacity; proof/testing: streaming enforcement and separate upload/validation concurrency controls. | Isolated prototype (provisional settings only); trusted implementation; production launch | Decision 9; OD-08 matrix row | Product/policy; Security; Infrastructure/storage; Operations/reliability |
| OD-09 — Project quotas | Decision owner: Product/policy; contributors: Infrastructure/storage, Engineering | Proposed | OD-09 row above | Owner decision: quota/capacity and plan treatment; design/testing: reservations, release, accounting and reconciliation. | Trusted implementation; production launch | Decision 9; OD-09 matrix row | Product/policy; Infrastructure/storage; Engineering |
| OD-10 — Storage provider/version guarantees | Decision owner: Infrastructure/storage; contributors: Security | Proposed | OD-10 row above | Owner decision: provider/configuration; infrastructure verification: private access, immutable exact-version reads, conditional writes and deletion guarantees. | Trusted implementation; render integration; production launch | Decision 8; OD-10 matrix row | Infrastructure/storage; Security |
| OD-11 — Digest/byte verification | Decision owner: Backend/architecture; contributors: Infrastructure/storage, Identity/security | Proposed | OD-11 row above | Design/testing: SHA-256 and byte count over the same exact read; cover interrupted reads, mismatch and subsequent rereads. | Trusted implementation; render integration | Decisions 7 and 8; OD-11 matrix row | Backend/architecture; Infrastructure/storage; Security |
| OD-12 — Logical deletion/cleanup | Decision owner: Product/policy, Legal/privacy; contributors: Operations/reliability, Infrastructure/storage | Proposed | OD-12 row above | Owner decision: retention/legal/backup constraints; testing: tombstones, lease races, cleanup and recovery. | Trusted implementation; render integration; production launch | Decisions 6, 8 and 9; OD-12 matrix row | Product/policy; Legal/privacy; Operations/reliability; Infrastructure/storage |
| OD-13 — Retention/backups | Decision owner: Legal/privacy, Product/policy; contributors: Infrastructure/storage, Operations/reliability | Proposed | OD-13 row above | Owner decision: obligations and periods; infrastructure verification: backup/deletion and recovery behavior. | Trusted implementation; production launch | Decision 6; Candidate B; OD-13 matrix row | Legal/privacy; Product/policy; Infrastructure/storage; Operations/reliability |
| OD-14 — Deletion/expiration during jobs | Decision owner: Product/policy, Identity/security; contributors: Operations/reliability, Backend/architecture | Proposed | OD-14 row above | Owner decision: expiration/revocation treatment of queued and running jobs; testing: lease/deletion races. | Render integration; production launch | Decisions 5, 6 and 10; OD-14 matrix row | Product/policy; Security; Operations/reliability; Backend/architecture |
| OD-15 — Atomic job/lease handoff | Decision owner: Backend/architecture; contributors: Infrastructure/storage, Operations/reliability | Proposed | OD-15 row above | Design/proof of capability: transaction/outbox boundary; testing: idempotency and absence of partial/conflicting job or lease state. | Render integration; production launch | Decisions 5, 6, 8 and 10; OD-15 matrix row | Backend/architecture; Infrastructure/storage; Operations/reliability |
| OD-16 — Lease lifecycle/recovery | Decision owner: Operations/reliability; contributors: Backend/architecture, Infrastructure/storage | Proposed | OD-16 row above | Owner decision: operational bounds; design/testing: renewal, expiry, release, reaping, stale workers and cleanup recovery. | Render integration; production launch | Decisions 6 and 8; OD-16 matrix row | Operations/reliability; Infrastructure/storage; Backend/architecture |
| OD-17 — Encryption/services/isolation | Decision owner: Security, Infrastructure/storage; contributors: Operations/reliability | Proposed | OD-17 row above | Owner decision/verification: encryption and key controls, service identities, credential custody and worker isolation. | Trusted implementation; render integration; production launch | Decisions 1, 2, 7 and 8; OD-17 matrix row | Security; Infrastructure/storage; Operations/reliability |
| OD-18 — Audit/privacy/incident response | Decision owner: Legal/privacy, Security; contributors: Operations/reliability | Proposed | OD-18 row above | Owner decision: jurisdiction, access and retention; design/testing: incident process, redaction and audit-access controls. | Trusted implementation; production launch | Candidate B; Decisions 1, 6 and 7; OD-18 matrix row | Legal/privacy; Security; Operations/reliability |
| Candidate A — Production Render/Output Contract | Decision owner: Product/policy; contributors: Backend/renderer engineering, Operations/reliability | Proposed | Candidate A; related OD-08, OD-12–OD-16 | Owner decision: profiles, delivery/access, failure/cancellation expectations; capability testing/proof for each claimed renderer feature. | Render integration; production launch | Candidate A section; related OD matrix rows | Product/policy; Backend/renderer engineering; Operations/reliability |
| Candidate B — Rights and Acceptable Use | Decision owner: Product/policy, Legal/privacy; contributors: Operations/reliability | Proposed | Candidate B; related Decisions 1 and 6, OD-13 and OD-18 | Owner decision/review: rights confirmation and acceptable-use scope; legal/privacy review; operational design for complaint intake, review and enforcement. | Trusted implementation (user uploads); production launch | Candidate B section; OD-13 and OD-18 matrix rows | Product/policy; Legal/privacy; Operations/reliability |

### Foundational decision briefs for owner confirmation

These briefs prepare OD-01, OD-02, OD-10 and OD-11 for review; their matrix
entries remain **OPEN — APPROVAL REQUIRED** for unresolved details. The
recorded OD-01 and OD-02 approvals authorize implementation only within their
stated scope. Other recommendations are not approvals or implementation
authorization. Proposed technical roles are not accepted assignments. Reviewers
and implementation owners remain **UNASSIGNED — OWNER CONFIRMATION REQUIRED**.

#### OD-01 — Canonical tenant/project model, ownership administration, and IDs

- **Decision to make:** Set the authoritative project-owner binding, canonical
  ID namespace, and conditions for any administrative ownership transfer.
- **Approved direction:** Decision 1 records individual-user personal projects
  and owner-only access with no sharing in v1; the trusted backend controls
  internal identity and project ownership. Decision 1 alone does not authorize
  implementation; the separate OD-01 approval below authorizes only its
  explicitly stated initial project scope.
- **Approved initial project-level scope (2026-11-01):** Ashishkumar Maurya,
  Project Owner and Maker, is the decision owner and authorized approver.
  Project IDs are generated by the backend and are identifiers, not
  credentials. A project record contains its project ID and internal
  `owner_user_id` foreign key. Project creation requires a trimmed, bounded
  `name`; the backend generates the project ID and derives `owner_user_id`.
  Reject client-supplied ownership fields. Expose authenticated create, list,
  and get operations with server-side owner checks. Return the same `404` for
  unknown and non-owned project IDs, with no project data and no mutation. Do
  not seed or silently assign the existing `sample-northstar` demo state. No
  sharing or ownership transfer is included in the initial scope. Keep the
  existing demo render and preproduction evaluation flows unchanged.
  Implementation is authorized only within this scope; recovery/linking,
  deletion policy, and render-job persistence remain deferred/open.
- **Persistence and migrations:** PostgreSQL is approved as the project-level
  persistence technology by Ashishkumar Maurya — Project Owner and Maker — on
  2026-11-01. The infrastructure provider and deployment configuration are
  separate and remain open. The proposed implementation stack is SQLAlchemy
  2.x, Alembic, and a PostgreSQL driver, subject to repository compatibility
  and dependency review. Use versioned migrations executed only by an explicit
  controlled setup/release command, never during import, application startup,
  or ordinary requests. Developer-controlled local PostgreSQL is approved for
  development and database integration tests. Schema details, migration
  runner/identity, hosted provider, production configuration, and recovery
  behavior remain unresolved.
- **Open questions:** Persistent user/project mapping and identifier constraints;
  separately approved recovery handling for account loss, disablement,
  deletion, or ownership restoration; infrastructure confirmation of provider
  and deployment configuration; and migration runner/identity details.
- **Options and trade-offs:** Keep ordinary ownership immutable as approved for
  the initial scope. Any future administrative recovery transfer would require
  a separately verified and audited process; its authority and safeguards
  remain open. No transfer is included in the approved initial scope.
- **Evidence for remaining implementation decisions:** Data/identity mapping
  design, unique identity mapping and project-owner foreign-key constraints,
  project-operation authorization matrix, migration plan and controlled-
  execution permissions, and recovery/deletion threat cases.
- **Dependencies:** Decisions 1 and 3; OD-02 for authenticated principal and
  OD-03/OD-10 for trusted operations.
- **Recommendation — not approval:** Preserve owner-only, project-bound access;
  define any transfer as a separate verified and auditable recovery operation
  rather than an email-based or client-directed reassignment.
- **Approval record:** Explicit project-level approval on 2026-11-01 by
  Ashishkumar Maurya — Project Owner and Maker. Implementation authorization
  is limited to the approved initial scope above. This does not select a
  database provider or deployment configuration, resolve deferred lifecycle
  details, or authorize production deployment.
- **Remaining questions:** Which database provider/environment and production
  configuration will be used? What migration runner/identity is appropriate?
  What separately approved recovery authority/evidence is required?
- **Roles:** Decision owner and authorized approver: Ashishkumar Maurya —
  Project Owner and Maker. Infrastructure owner for provider/deployment
  configuration: **UNASSIGNED — OWNER CONFIRMATION REQUIRED**. Technical
  contributors remain Identity/security and Backend/architecture;
  implementation owner remains **UNASSIGNED — OWNER CONFIRMATION REQUIRED**.

#### OD-02 — Authenticated principal and token-validation contract

- **Decision to make:** Define the exact browser credential and server-side
  verification contract for protected requests, including claim checks and the
  required revocation/session-state behavior.
- **Approved direction:** Decision 2 selects Clerk for v1; Decisions 3–5
  approve verified issuer/subject mapping principles, server-side verification,
  separate project authorization, fail-closed checks, and the principle that
  offline JWT verification alone does not ensure immediate revocation awareness.
  Exact token and production configuration remain open.
- **Approved v1 contract — matching the current implementation (2026-11-01):**
  Ashishkumar Maurya, Project Owner and Maker, approved this contract at
  project level, subject to the documented authentication contract and
  limitations. Accept Clerk session tokens only. Use the maintained Clerk SDK
  for signature verification with RS256, expiry/not-before, configured audience
  and authorized-party checks; compare the verified issuer to the configured
  issuer; require a nonblank subject and numeric `iat`, `nbf`, and `exp`; and
  fail closed. Use only the verified exact `(issuer, subject)` pair for
  Decision 3 mapping. Authentication remains separate from project-owner
  authorization. Document that offline JWT checks do not guarantee immediate
  revocation awareness.
- **Open questions:** Deployment-specific issuer, audience and authorized-party
  values; verifier configuration; session-state or revocation checks, cache
  behavior, and acceptable revocation delay.
- **Options and trade-offs:** The approved v1 contract uses Clerk's maintained
  server verification SDK as stated above. Whether additional provider
  session-state checks are required depends on the still-open revocation
  requirement and demonstrated behavior; no such capability is assumed.
- **Evidence for deployment verification:** Redacted representative claims,
  verifier documentation for the configured deployment, tests for the approved
  signature/algorithm/issuer/expiry/not-before and applicable
  audience/authorized-party checks, plus evidence for revocation and caching
  semantics.
- **Dependencies:** Decisions 2–5; OD-01 for project ownership and OD-17 for
  deployment security and service-identity separation.
- **Recommendation — not approval:** Before enabling protected APIs, verify
  deployment configuration and required session/revocation behavior against
  the approved token contract using evidence from the actual verifier setup.
- **Approval record:** Explicit project-level approval on 2026-11-01 by
  Ashishkumar Maurya — Project Owner and Maker. Implementation authorization is
  limited to the approved contract and its documented limitations; no
  production deployment or broader security claim is authorized.
- **Remaining questions:** Deployment-specific issuer/audience/authorized-party
  configuration, session-state or revocation checks, caching, and acceptable
  revocation delay remain open.
- **Roles:** Decision owner and authorized approver: Ashishkumar Maurya —
  Project Owner and Maker. Technical contributors: Backend/architecture.
  Identity/security and Product/policy reviewers, and the implementation owner,
  remain **UNASSIGNED — OWNER CONFIRMATION REQUIRED**.

#### OD-10 — Storage provider and immutable object-version guarantees

- **Decision to make:** Select a storage approach only after proving that it
  meets the approved private-access, immutable-version, exact-read, conditional
  write, and controlled-deletion requirements.
- **Approved direction:** Decision 8 requires private storage, backend-controlled
  immutable version identity, exact-version reads, and no silent overwrite or
  `latest` substitution. No asset-storage provider is selected.
- **Open questions:** Provider and configuration; exact version-reference
  semantics; private access/IAM, conditional writes, retention/deletion and
  backup behavior; and operational recovery guarantees.
- **Options and trade-offs:** A storage service with native immutable object
  versions may provide explicit version-addressed reads but depends on verified
  provider semantics and configuration. A private store using unique
  application-assigned object keys and enforced create-only writes may avoid
  mutable aliases but requires proof that overwrite/delete paths cannot bypass
  the application rule. Neither option is presumed available or sufficient.
- **Evidence before approval:** Provider-neutral requirements and candidate
  capability evidence; tests showing old pins return only the same version or
  fail, overwrite/conditional-write behavior, private-access enforcement, and
  deletion/retention effects. Infrastructure owner must verify actual
  configuration, not just product documentation.
- **Dependencies:** Decisions 8 and 9; OD-11 for digest/byte verification;
  OD-12/13 for deletion and retention; OD-17 for encryption and service access.
- **Recommendation — not approval:** Compare candidate approaches against
  observable exact-version and access-control tests before selecting a provider
  or beginning trusted storage integration.
- **Approval question:** Which infrastructure-supported storage option can
  demonstrate every required guarantee, and who accepts the deployment evidence?
- **Roles (unconfirmed):** Proposed decision owner: Infrastructure/storage.
  Technical contributors: Security and Backend/architecture. Review areas:
  Infrastructure/storage and Security. Reviewer, approver, and implementation
  owner: **UNASSIGNED — OWNER CONFIRMATION REQUIRED**.

#### OD-11 — SHA-256 and byte-size verification

- **Decision to make:** Specify and verify how actual byte count and SHA-256 are
  computed over the exact immutable bytes inspected, persisted with evidence,
  and rechecked on later reads.
- **Approved direction:** Use SHA-256 over the exact finalized immutable bytes;
  measure actual byte count from that same read, bind both to the version and
  attempt, and fail closed if subsequent reads mismatch or cannot be verified.
- **Open questions:** Streaming and parser integration, complete-read detection,
  interrupted-read/retry behavior, evidence persistence, and how future reads
  prove they retrieved the exact pinned version. The digest alone does not prove
  availability, authorization, or authenticity.
- **Options and trade-offs:** Compute digest/count while the validator consumes
  one complete exact-version stream (strong byte-sequence coupling, but requires
  careful stream completion and parser integration); or perform separate reads
  of the same immutable version and independently verify each read (simpler
  separation, but adds I/O and requires every read to be pinned and checked).
- **Evidence before approval:** Design showing version-pinned reads, actual
  byte-count measurement, full-stream completion, digest over precisely the
  inspected bytes, interrupted-read failure behavior, evidence binding to the
  validation attempt, and mismatch rejection on later reads; exercise these
  cases against the chosen storage semantics.
- **Dependencies:** Decisions 7 and 8; OD-10 for exact-version reads, OD-03/04
  for trusted evidence authority/binding, and OD-05/06 for attempts and stale
  readiness results.
- **Recommendation — not approval:** Prefer one complete pinned byte stream
  whose consumed bytes are both validated and hashed; document and test the
  completion boundary. Treat later reads as separate verifications against the
  recorded digest and byte count.
- **Approval question:** Does the proposed byte-to-evidence procedure satisfy
  the approved exact-bytes requirement, and what proof is required for storage
  reads and interrupted operations? Any change to SHA-256 or exact-byte binding
  requires explicit policy approval.
- **Roles (unconfirmed):** Proposed decision owner: Backend/architecture.
  Technical contributors: Infrastructure/storage and Identity/security. Review
  areas: Backend/architecture, Infrastructure/storage, and Security. Reviewer,
  approver, and implementation owner: **UNASSIGNED — OWNER CONFIRMATION
  REQUIRED**.

### Owner-confirmation checklist

Please identify an accountable person or role and confirm whether they accept
the decision-owner responsibility. These are blank confirmation fields, not
assignments or approvals; reviewer, approver, and implementation-owner roles
must be confirmed separately where applicable.

| Area | Accountable person or role to be confirmed | Acceptance status |
|---|---|---|
| Product/policy | ____________________ | **UNASSIGNED — OWNER CONFIRMATION REQUIRED** |
| Identity/security | ____________________ | **UNASSIGNED — OWNER CONFIRMATION REQUIRED** |
| Infrastructure/storage | ____________________ | **UNASSIGNED — OWNER CONFIRMATION REQUIRED** |
| Backend/architecture | ____________________ | **UNASSIGNED — OWNER CONFIRMATION REQUIRED** |
| Operations/reliability | ____________________ | **UNASSIGNED — OWNER CONFIRMATION REQUIRED** |
| Privacy/legal | ____________________ | **UNASSIGNED — OWNER CONFIRMATION REQUIRED** |

### Readiness implications

OD-01/02 must be resolved before protected, project-scoped user operations;
OD-10/11 before trusted storage reads, validation, or evidence can be relied
on. Their unresolved details do not block unrelated local UI work, pure
contract tests, or isolated fixture-based development that makes no trust or
production claim. Those activities do not satisfy the trusted-path gates.
OD-08/09 production values and capacity evidence are launch gates; only the
explicitly provisional development settings may be used for isolated work.
The other routing entries remain prerequisites for their corresponding
trusted lifecycle, rendering, and production phases as listed in the register.

**Overlap notes:** OD-03/OD-04 cover distinct but related issuer-boundary and
evidence-schema questions. OD-05/OD-06 distinguish attempt/retry handling from
readiness revocation/revalidation. OD-08/OD-09 separate resource limits from
project quotas. OD-12/OD-13 separate deletion mechanics from retention policy.
OD-14/OD-15/OD-16 cover job-time deletion semantics, atomic handoff, and lease
lifecycle respectively. OD-17/OD-18 separate deployment safeguards from audit
and privacy obligations. These links do not merge or resolve any row.

## Approval gates and scope

Approved direction already requires project-bound immutable versions, trusted byte validation, trusted evidence issuance, exact sample alignment, CAS acceptance, fail-closed malformed-media handling, immediate logical deletion blocking new resolution/leases, and leased-job completion subject to valid leases. The pure WAV parser now validates in-memory bytes against a narrow proposed v1 compatibility matrix, but no trusted worker reads stored bytes or issues authoritative evidence. The other trust and lifecycle controls remain unimplemented by the current pure contracts/matcher.

Do not begin trusted storage or upload exposure until the remaining project/ownership mapping, evidence authority, lifecycle retry/revocation semantics, parser compatibility, production limits, retention, and deployment security prerequisites are resolved. Do not begin job handoff or rendering until storage exact-version guarantees, deletion policy, lease semantics, and atomic job creation are resolved. Clerk is selected as the v1 managed identity provider, but no Clerk integration is implemented. No storage provider, production limit, or retention period is selected by this record.

## Implementation workstreams (not authorized)

These workstreams are a dependency map only. Each requires a separately
reviewed implementation milestone after its policy and owner gates are met.

1. **Identity and project authorization** — settle OD-01/02, then implement
   verified-principal mapping and server-side owner checks before protected
   project or asset APIs.
2. **Persistence foundation** — agree the user/project/asset identity schema
   and durable state/revision constraints (OD-01, OD-05, OD-06) before CAS
   lifecycle operations.
3. **Private immutable storage** — obtain provider-owner guarantees and
   security configuration (OD-10, OD-17), then implement exact-version object
   reads/writes, private access and deletion controls.
4. **Upload admission/finalization** — after OD-08/09/10/12 policy and owner
   prerequisites, implement bounded uploads, exact project/version binding,
   idempotent finalization and incomplete-upload cleanup.
5. **Trusted validation and evidence** — after OD-03/04/07/11/17, inspect the
   exact finalized bytes, enforce the approved WAV profile, compute observed
   digest/size and issue trusted version-bound evidence.
6. **Persistent lifecycle/readiness** — after the persistence and evidence
   foundations, implement state transitions, CAS, validation attempts,
   stale-result rejection, revocation and approved recovery behavior.
7. **Resolution and leases** — after storage, evidence and lifecycle are
   trusted, resolve only exact v2 pins, authorize project access and create
   complete leases under OD-12/14/15/16 rules.
8. **Render-job handoff and renderer integration** — after resolution/leases
   and Candidate A's output contract are ready, atomically hand off an
   authorized pinned job, recheck authorization and implement only verified
   output capabilities.
9. **Production operations and launch acceptance** — close OD-08/09/13/17/18
   and Candidate B's operational prerequisites; verify limits, retention,
   audit/privacy, recovery, security tests and deployment acceptance.

## Architecture-phase exit criteria

Exit is evidence-based: a checklist item is complete only when the cited
decision is resolved and its acceptance evidence is recorded. If a prerequisite
remains open, the dependent item remains blocked. These criteria do not assert
that implementation exists and introduce no numerical limits.

- [ ] **Identity:** approved token type/claims/verification/revocation contract
  is documented; provider mapping and canonical IDs are specified; tests
  demonstrate authentication and project ownership are separate and deny
  cross-project access on every protected operation. Depends on OD-01/02.
- [ ] **Storage:** selected deployment provider is shown to provide private
  access and exact immutable-version reads; overwrite/substitution and
  unavailable-version cases fail closed; digest and actual byte count are
  checked on validation and subsequent reads. Depends on OD-10/11/17.
- [ ] **Upload admission:** finalization binds project, asset and immutable
  version; incomplete/interrupted uploads cannot become finalized or ready;
  duplicate and ambiguous finalization is idempotent or safely rejected; race
  and cleanup behavior is tested. Depends on OD-08/09/10/12 and Decision 9.
- [ ] **Evidence/readiness:** only the approved trusted service can issue
  authoritative evidence; evidence binds exact bytes, version, profile and
  validation attempt; caller-created evidence cannot establish readiness.
  Depends on OD-03/04/07/11 and Decision 7.
- [ ] **Concurrency/recovery:** persistent CAS checks expected version, state,
  revision and attempt; stale/duplicate worker results cannot restore
  readiness; retry, timeout, cancellation, partial failure and recovery tests
  match approved behavior. Depends on OD-05/06 and Decision 10.
- [ ] **Jobs/leases/deletion:** submit and execute recheck authorization and
  exact asset readiness; job snapshot and leases are atomic; lease expiry,
  renewal, recovery, cancellation, deletion and in-flight behavior have
  approved rules and race tests. Depends on OD-12/14/15/16 and Decisions 5/6/10.
- [ ] **Limits/retention/deployment:** production limits and quota are approved
  and enforced with fail-closed configuration; retention, backup deletion,
  encryption, key custody, service isolation and recovery are approved for the
  deployment and verified. Provisional development defaults are not accepted
  as production values. Depends on OD-08/09/13/17.
- [ ] **Candidate A output contract:** exact supported profiles/formats,
  delivery/access, failure and cancellation semantics are approved; tests or
  deployment evidence establish each claimed renderer capability. Proposed
  profiles are not represented as supported before that evidence exists.
- [ ] **Candidate B readiness:** rights confirmation, acceptable-use rules,
  complaint intake/review/escalation, enforcement ownership, privacy and legal
  review are documented and operationally assigned before public launch. No
  automated moderation or legal compliance is assumed. Depends on Candidate B
  open details and OD-18.
- [ ] **Audit/privacy/security acceptance:** redaction and access controls are
  tested; incident response and recovery ownership is assigned; security tests
  cover unauthorized access, hostile media, resource exhaustion, stale
  evidence, version substitution and deletion/lease races. Depends on OD-03,
  OD-13, OD-17 and OD-18.
- [ ] **Scanner boundary:** API tests continue to show `/scan` unavailable;
  no asset-pipeline URL fetching is added; the local scanner's documented DNS
  rebinding/TOCTOU limitation and public-deployment warning remain explicit.

No architecture exit criterion authorizes implementation or public launch by
itself; explicit approval and a separately scoped implementation decision
remain required.

`VersionedRenderPlan`, `ManagedAsset`, `AssetValidationEvidence`, `VersionBoundValidationEvidence`, `AssetVersionBinding`, `AssetLeaseRequest`, `AssetLeaseRecord`, and `AssetVersionRecord` remain caller-constructible values. The pure evidence comparison, lifecycle-precondition check, lease-to-snapshot binding, and explicit-time expiry helper do not prove compiler provenance, evidence authenticity, authentication, storage availability, media-byte verification, atomic state change, or lease acquisition. A `ready` state or an `active` lease label alone does not authorize use. The existing local website-extraction CLI remains separate from the asset pipeline and retains its documented DNS rebinding/TOCTOU limitation and public-deployment warning. The `/scan` API remains unavailable and must not be added based on this policy work.
