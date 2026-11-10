# Project Creative Workspace v1

## Status and boundary

This document describes the authenticated project-scoped creative-planning workspace added in Milestone 11. It records implementation behavior; it does not approve implementation beyond the already authorized project scope, change any OD status, or authorize applying a migration to a development/hosted database or production deployment.

The workspace stores user-authored campaign brief fields, creative direction, and an ordered storyboard under one owned project. It does not establish the truth of campaign claims, validate media, create assets, generate video, or make the project production-ready. The sample project `sample-northstar` remains separate and illustrative. Existing demo render and preproduction evaluation routes remain unchanged. `/scan` remains unavailable.

## Persistence

Revision `20261111_0002` adds `project_creative_workspaces` with:

- `project_id`: primary key and foreign key to `projects.id`; no cascade deletion is configured.
- `revision`: positive integer, beginning at 1 for the first saved document.
- `brief`, `creative_direction`, and `storyboard`: JSON documents validated by the backend's strict Pydantic request models.
- `created_at` and `updated_at`: database timestamps; ORM writes update `updated_at`, while direct SQL writers must set it explicitly.

The revision file is additive and is not automatically executed. Migrations remain an explicit controlled setup/release operation. The migration must be tested in an isolated disposable PostgreSQL test schema; no verification of migration `20261111_0002` is implied until those tests actually run. Do not use the application development database for integration tests.

Campaign planning fields include campaign and brand names, optional website URL, product/service description, target audience, objective, platform, selling points, and call to action. Creative direction stores style, tone, messages, audience emphasis, brand personality, aspect ratio, and preferred duration. These are draft workspace fields and engineering-bounded inputs, not an approved production data contract.

Storyboard scenes preserve ordered IDs, title, description, visual direction, on-screen text, narration notes, duration, and editorial status. Scene status is `draft` or `ready_for_review`; neither means rendered or production-ready. The request is bounded to 32 scenes, text lengths are bounded by the API schema, duration is 1–60 whole seconds, IDs are unique and constrained, and website URLs must be absolute HTTP(S) URLs without embedded credentials. Empty fields are supported as incomplete drafts.

## API

Both endpoints require the existing verified Clerk principal and resolve its internal user mapping server-side. Project ownership is checked in the API/service boundary. The client supplies neither an owner ID nor Clerk identity fields. Unknown and non-owned project IDs return the existing project-not-found `404` response.

### Read

`GET /projects/{project_id}/creative-workspace`

Returns the saved document for the authenticated project owner. If none has been saved, returns an empty, unsaved representation (`revision: 0`, blank brief/direction, empty storyboard, null workspace timestamps) without creating a database row.

### Save

`PUT /projects/{project_id}/creative-workspace`

Request shape:

```json
{
  "revision": 0,
  "brief": { "campaign_name": "Spring launch" },
  "creative_direction": { "visual_style": "Editorial" },
  "storyboard": [
    { "id": "scene-opening", "title": "Opening", "duration_seconds": 5 }
  ]
}
```

All omitted supported fields receive empty/null defaults. Extra fields are rejected. Revision 0 inserts revision 1; subsequent writes must send the currently loaded revision and increment it. A stale revision returns `409` without overwriting saved content. Concurrent initial saves use a savepoint around the unique project-key insert; only one succeeds, and a conflict does not poison the enclosing request transaction.

The client loads on project entry and saves only after the user chooses **Save workspace**. Changes are not sent while typing. The editor is keyed by signed-in user and project; its project-aware loading effect ignores responses after that component has been replaced. Switching projects cannot reuse the other project's editor state.

## Readiness and unavailable capabilities

The overview derives campaign brief completion, creative-direction presence, and storyboard preparation from the saved document. It does not report a percentage. Asset handling is explicitly unavailable: there is no upload, validation/admission, or asset storage integration in this workspace. Project-scoped rendering is also unavailable; the existing temporary silent illustrative renderer remains tied to its separate demo workflow. Recent activity history is not implemented and is shown as unavailable rather than fabricated.

## Verification status

On 2026-11-11, the full backend suite reported 588 passed, 3 skipped, and 1 existing Starlette deprecation warning. The skipped tests are PostgreSQL integration tests because `SPOTLOOM_TEST_DATABASE_URL` was unavailable in that runner; PostgreSQL behavior for revision `20261111_0002` is therefore unverified. The complete frontend Node suite reported 69 passed. TypeScript typecheck, ESLint, and the Next.js production build passed. These results are also recorded in `docs/PROGRESS.md`.

PostgreSQL integration tests are opt-in and must use only `SPOTLOOM_TEST_DATABASE_URL` after verifying that it targets the disposable loopback `spotloom_test` database; they create and remove unique temporary schemas. Running the test harness is separate from applying the migration to the local development database. Migration `20261111_0002` was not applied to the local development database as part of this milestone.
