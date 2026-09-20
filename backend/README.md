# AskRepo Backend

FastAPI service for AskRepo — the codebase-aware assistant described in
[`docs/PRD.md`](../docs/PRD.md).

**Milestone progress is recorded in [`docs/PRD.md`](../docs/PRD.md) §6 and nowhere else** —
this file describes the service as it stands, and the route table below is its exhaustive
contract.

The service identifies itself, reports health, and serves the full auth/accounts surface —
admin-provisioned users, login, forced first-login password change, session rotation, and login
rate limiting.

Access is **per project**. Every project has members, each holding one role, and each role
carries a set of named permissions; `viewer`, `editor` and `owner` ship as immutable system
roles and admins may define more. See `### Project members` and `### Roles and permissions`
below.

The project routes and the entire ingestion pipeline are here — clone, walk, chunk, embed, and
write to Qdrant — along with the Kafka producer, the consumer that turns a queued message into an
indexing run, the delayed-retry consumers, and `app/worker.py`: the separate process that runs
all of them and sweeps up jobs the broker never received. `POST /projects` enqueues and a worker
indexes.

On top of that sit Dev Knowledge (streaming RAG Q&A over an indexed project), the LangGraph
intent routing and corrective retrieval loop behind it, the QA Checklist, and the Mock Data
Generator — see the `### Conversations`, `### QA Checklist`, and `### Mock Data Generator` route
sections below.

## Requirements

- Python 3.13 (`uv` will fetch it for you)
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Running locally

The datastores must be up first — `make infra` from the repo root, or
`docker compose -f infra/docker-compose.yml up -d --wait postgres qdrant redis kafka`.
Postgres and Redis are enough to run the test suite; Qdrant is needed to index, Kafka to
enqueue, and Ollama to embed (unless `EMBEDDING_PROVIDER` points at a hosted API).

**Ollama is not one of the containers** — it runs on the host, so `ollama serve` has to be up
too, and `EMBEDDING_BASE_URL` / `CHAT_BASE_URL` point at plain `http://localhost:11434` when
the app runs natively. `make pull-models` fetches the configured models.

```bash
cd backend
cp .env.example .env                              # optional — every value has a default
uv sync                                            # creates .venv and installs dependencies
uv run alembic upgrade head                        # apply migrations
BOOTSTRAP_ADMIN_PASSWORD=<a real passphrase> \
  uv run python -m app.cli seed-admins             # create the bootstrap admins (idempotent)
uv run uvicorn app.main:app --reload --log-config logging.json
```

The API is then on <http://localhost:8000>, with interactive docs at
<http://localhost:8000/docs>. Log in as `superuser@example.com` or `admin@example.com`
with the password you set; both are seeded with `must_change_password` set.

### The ingestion worker

The API only *enqueues* indexing and checklist-generation jobs. Nothing indexes and no
checklist is generated until a worker is running, so a new project sits at `pending` and a
module sits at `generating` until one is. `make dev` starts one for you; to run a lone one:

```bash
make worker            # or, equivalently:
cd backend && uv run python -m app.worker
```

It is the same codebase with a different entrypoint, so it reads the same `Settings` and
the same `.env`. One process runs the ingest consumer, the checklist consumer, one consumer
per retry rung of each, and a sweep every 60 seconds that re-enqueues jobs whose produce
failed or whose worker died, and prunes expired refresh tokens. Run more than one and they share the ingest topic's
partitions — two is the configured cap (`KAFKA_INGEST_PARTITIONS`).

## Running in Docker

```bash
cd infra && docker compose up --build
```

That brings up the API alongside Postgres, Qdrant, Redis, Kafka, and the frontend. Ollama
stays on the host; the containers reach it at `host.docker.internal:11434`, which needs it
bound to `0.0.0.0` (`launchctl setenv OLLAMA_HOST "0.0.0.0:11434"` on macOS).
Source is bind-mounted, so `--reload` picks up your edits — which is also why this image is
**not** a production one. See [`../docs/deployment.md`](../docs/deployment.md).

## Routes

| Method | Path            | Returns                                                       |
| ------ | --------------- | ------------------------------------------------------------- |
| `GET`  | `/`             | `{app, version, date}` — service identity and server time     |
| `GET`  | `/health`       | `{status, app, version, env, timestamp}` — overview           |
| `GET`  | `/health/live`  | `{status}` — liveness; `ok` whenever the process is up         |
| `GET`  | `/health/ready` | `{status, checks}` — readiness; `checks` is empty for now      |

```bash
curl -s localhost:8000/ | jq
curl -s localhost:8000/health | jq
```

`/health/ready` exists so datastore probes (Postgres, Qdrant, Kafka) can be added to
`checks` later without changing the response shape — a dependency going down
flips `status` to `degraded` while `/health/live` stays `ok`. **No probes have been
wired in yet**, even though all four datastores are now read elsewhere in the app.

### Auth

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/auth/password-policy` | none | The length bounds a new password must satisfy |
| `POST` | `/auth/login` | none | Log in; sets the refresh cookie |
| `POST` | `/auth/refresh` | refresh cookie | Rotate the session |
| `POST` | `/auth/change-password` | access token | Change your own password |
| `POST` | `/auth/logout` | refresh cookie | Log out of this device |
| `POST` | `/auth/logout-all` | access token | Log out everywhere |
| `GET` | `/auth/me` | access token | The current account |

### Users

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/users` | any user | List accounts, paginated |
| `GET` | `/users/{id}` | any user | One account |
| `POST` | `/users` | admin | Provision an account |
| `PATCH` | `/users/{id}` | admin | Update name or admin flag |
| `DELETE` | `/users/{id}` | admin | Deactivate, revoking sessions. `409 LAST_OWNER` if it would leave any project with no live owner — the body names the blocking projects |
| `POST` | `/users/{id}/reset-password` | admin | Set a temporary password |

`DELETE /users/{id}` is the one route in the codebase whose error body is wider than
`{code, message}`. `LAST_OWNER` carries a `projects` array of `{id, name}`, because "no" alone
tells an admin nothing about what to fix — the widening is declared with its own
`LastOwnerErrorResponse` model rather than the generic `409` entry, so `/docs` and every
generated client describe the body the route actually returns. The guard prevents *new*
strandings; it cannot repair one the RBAC migration's backfill inherited (see
`?ownerless=true` below).

### Projects

**A project is reachable only by its members.** Access comes from the caller's
`project_memberships` row and the role it names — see [`../docs/data.md`](../docs/data.md). A
caller with no membership gets `404 PROJECT_NOT_FOUND` on every route here, including the
destructive ones: project existence is no longer public, so `403` would confirm a private
repository exists to anyone who can guess an id. A **member** whose role is too low gets
`403 INSUFFICIENT_ROLE`. Administrators pass every project permission.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/projects` | any user | List the projects you are a member of, paginated. Admins see all. `?ownerless=true` (**admin only**, else `403 ADMIN_REQUIRED`) narrows to projects with no live owner |
| `GET` | `/projects/{id}` | any member | One project, including your own `role` and effective `permissions` on it |
| `GET` | `/projects/{id}/indexed-paths` | any member | Browse (`?path=`) or search (`?search=`) the project's indexed file tree, for the checklist path picker |
| `POST` | `/projects` | any user | Register a repository and enqueue its first index. The creator is granted `owner` on it |
| `POST` | `/projects/{id}/reindex` | `project.reindex` | Re-index; raises `reindexInProgress` before publishing, and a run already in flight is a no-op |
| `DELETE` | `/projects/{id}` | `project.delete` | Soft-delete the row and hard-delete its vectors |

`ProjectResponse` carries two fields the frontend uses to hide controls it would be refused:
`role` (the caller's role name on this project, `null` for an admin with no membership) and
`permissions` (their effective permission values). **Hiding is cosmetic** —
`access.require_permission` in the service is the control.

`?ownerless=true` exists for one situation the RBAC migration created deliberately. The backfill
seeded one `owner` membership per project from `created_by` and **did not fabricate owners for
creators who were already deactivated**, so those projects start with no live owner. They stay
operable, because admins bypass every project permission, and this filter is how an admin finds
them to grant someone `owner`. It is applied *on top of* the access resolver's scope rather than
in place of it, so it can only ever narrow what the caller may already read.

`DELETE` and `indexed-paths` are the two routes here that can return
**`503 VECTOR_STORE_UNAVAILABLE`**, because they are the two that reach Qdrant. `DELETE` must,
to satisfy `docs/PRD.md` §5.1's same-operation hard delete; if Qdrant is down nothing is
committed, so the project stays visible and the call can be retried. It also soft-deletes every
conversation against the project, for every owner (`docs/PRD.md` §4.2).

`indexed-paths` enumerates the project's indexed `file_path` values — a scroll asking for that
one payload field, no vector search and no model call — cached per `(project, activeGeneration)`
so a reindex cannot serve a stale tree. It answers one directory at a time, or every match for
`?search=`, and refuses with `409 PROJECT_NOT_READY` when there is no index to enumerate. A
reindex in flight does **not** block it: the live generation is still serving and this read
records nothing.

### Project members

Who may reach one project, and as what. Every route gates through
`access.require_permission`, so a non-member gets `404 PROJECT_NOT_FOUND` and an
under-privileged member gets `403 INSUFFICIENT_ROLE`.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/projects/{id}/members` | `membership.read` | Everyone with a role on this project |
| `POST` | `/projects/{id}/members` | `membership.grant` | Grant a user a role here; `201`. `404 ROLE_NOT_FOUND` / `404 USER_NOT_FOUND`, `409 MEMBERSHIP_EXISTS` if they already hold one |
| `PATCH` | `/projects/{id}/members/{userId}` | `membership.grant` | Change an existing member's role. `404 MEMBERSHIP_NOT_FOUND`, `404 ROLE_NOT_FOUND`, `409 LAST_OWNER` if it would demote the last owner |
| `DELETE` | `/projects/{id}/members/{userId}` | `membership.revoke` | Revoke access; `204`. `404 MEMBERSHIP_NOT_FOUND`, `409 LAST_OWNER` if it would remove the last owner |

`viewer` holds `membership.read`, so every member can see who else is on a project. Only
`owner` holds `membership.grant` and `membership.revoke`.

Both `409 LAST_OWNER` refusals enforce the same invariant as `DELETE /users/{id}`: a live
project keeps at least one live owner, so nobody can lock a project's own members out of
managing it.

### Roles and permissions

Role definitions are **instance-wide**; a membership is what carries the project. That is what
lets one "QA Lead" role be granted on twelve projects without twelve role rows. Every route
here is admin-only, enforced by a router-level dependency rather than per route, so a route
added later is gated with no action taken.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/permissions` | admin | The permission catalogue, grouped and labelled for the role-matrix editor |
| `GET` | `/roles` | admin | Every role on the instance, system roles first, each with its permissions and `memberCount` |
| `POST` | `/roles` | admin | Create a custom role (name + description); `201`. `409 ROLE_NAME_EXISTS` |
| `PATCH` | `/roles/{id}` | admin | Rename a custom role and/or replace its permission set. `404 ROLE_NOT_FOUND`, `403 SYSTEM_ROLE_IMMUTABLE`, `409 ROLE_NAME_EXISTS`, `422` for a permission not in the catalogue |
| `DELETE` | `/roles/{id}` | admin | Soft-delete a custom role; `204`. `404 ROLE_NOT_FOUND`, `403 SYSTEM_ROLE_IMMUTABLE`, `409 ROLE_IN_USE` if anyone still holds it |

`viewer`, `editor` and `owner` are **system roles** (`isSystem: true`) and cannot be renamed,
deleted or re-permissioned — `403 SYSTEM_ROLE_IMMUTABLE`. That immutability is what makes the
role editor safe to expose at all: without it, unchecking `membership.grant` on `owner` would
leave nobody on the instance able to grant membership, including to undo it. If a system role is
damaged some other way — direct SQL, a partial restore — `python -m app.cli restore-system-roles`
puts it back.

Which permissions exist is anchored in `app/core/permissions.py`, not in a table.
`role_permissions.permission` is a validated string, and `PATCH /roles/{id}` refuses a value
that is not in the catalogue, because a stored permission nothing checks is silently dead
weight. There is deliberately **no `conversation.*` permission** — that absence is what makes
the administrator bypass in `require_permission` safe, since there is nothing here to bypass
into.

### Conversations

The mirror image of projects: a conversation is visible **only** to the user who had it. Every
miss is `404`, never `403` — a `403` would confirm it exists — and `is_admin` does not widen
this, because conversations are not shared (`docs/PRD.md` §4.2).

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/conversations` | owner only | List your own, paginated; optional `projectId` filter |
| `GET` | `/conversations/{id}` | owner only | One conversation with its messages, oldest first |
| `POST` | `/conversations` | any user | Open a conversation against a readable project |
| `DELETE` | `/conversations/{id}` | owner only | Soft-delete |
| `POST` | `/conversations/{id}/messages` | owner only | Ask a question; **streams the answer** |

`POST /conversations/{id}/messages` responds `text/event-stream`, so it has no
`response_model`. Everything that can set a status code happens before the body starts —
`404` for an unreachable conversation or project, `409 PROJECT_NOT_READY`, `409
EMBEDDING_MODEL_CHANGED`, `422` for an empty question. Once streaming begins the response is
`200` and failures arrive as an `error` event.

Five event types, all `camelCase` payloads:

| Event | Payload | Notes |
| --- | --- | --- |
| `status` | `{phase}` | `queued` \| `classifying` \| `retrieving` \| `grading` \| `generating`. May repeat |
| `citations` | `{citations: [...]}` | Exactly once, **before** the first `token` |
| `token` | `{text}` | One fragment of the answer |
| `done` | `{messageId, model, finishReason, citedIndexes, groundingWarnings}` | Terminator |
| `error` | `{messageId, code, message, finishReason}` | Terminator |

Exactly one terminator per stream, and both carry `finishReason`: `stop`, `error`, `timeout`,
or `disconnected`. A disconnect emits nothing — nobody is listening — but the tokens that
arrived are still persisted. `groundingWarnings` is empty for a normal answer and carries
`no_context`, `uncited_answer`, `unknown_paths`, or `weak_evidence` when the answer may not
be grounded.

A `: keep-alive` comment goes out every 15 seconds during any gap, and the response sets
`Cache-Control: no-cache` and `X-Accel-Buffering: no` so a proxy does not accumulate the
stream and deliver it in one piece.

### QA Checklist

Modules over an indexed repository — a user names a module ("Authentication"), points it at a path in the repository, and requests generation. A background job enumerates the module's files, proposes features and test cases with expected results grounded in the code, and produces a change set for review. Nothing generated enters the checklist unreviewed.

Access follows the module's **project**, never `created_by`: reads are scoped by
`access.resolve_project_scope`, so a module is visible exactly to the project's members, and
editing and deleting gate on a named permission (`module.edit`, `module.delete`, `item.edit`).
Recording a test result needs only `result.record`, which **every** system role holds including
`viewer` — a tester must be able to record what they observed without being able to rewrite
what was expected.

**Checklist Modules**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/checklist-modules` | any member | List modules for projects you are a member of, paginated |
| `POST` | `/checklist-modules` | `module.create` | Name a module and point it at a path in the indexed repository. `400 MODULE_PATH_NOT_INDEXED` if the path matches nothing |
| `GET` | `/checklist-modules/{id}` | any member | One module with its test cases, grouped by feature |
| `PATCH` | `/checklist-modules/{id}` | `module.edit` | Rename or re-point the module |
| `DELETE` | `/checklist-modules/{id}` | `module.delete` | Soft-delete the module, its items, its change sets, and its chat |
| `POST` | `/checklist-modules/{id}/generate` | `generate.run` | Publish a generation job; returns the module in `generating` status. `409 PROJECT_NOT_READY` while the project is being re-indexed |
| `GET` | `/checklist-modules/{id}/change-sets` | any member | List the module's proposed change sets, newest first |
| `GET` | `/checklist-modules/{id}/messages` | any member | Read the module's refinement chat |
| `POST` | `/checklist-modules/{id}/messages` | any member | Refine the checklist by chat; **streams the reply and proposes changes** |

**Checklist Items**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/checklist-items` | any member | List test cases across modules, paginated; filters for project, module, feature, status, source, kind |
| `POST` | `/checklist-items` | any member | Add a test case by hand |
| `PATCH` | `/checklist-items/{id}` | `item.edit` | Edit what a test expects (name, feature, expected result, notes) |
| `PUT` | `/checklist-items/{id}/result` | `result.record` | Record a test result (current result and status); every system role holds this, `viewer` included |
| `DELETE` | `/checklist-items/{id}` | `item.edit` | Soft-delete the test case |
| `GET` | `/checklist-items/export` | any member | Export the filtered checklist as `.xlsx`, regardless of pagination limit |
| `POST` | `/checklist-items/clear-results` | any member | Reset the recorded result on every row the filter selects, within one module |

**Checklist Change Sets**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/checklist-change-sets/{id}/apply` | `changeset.apply` | Apply the named operations, or all of them; nothing is written to the checklist until this is called |
| `POST` | `/checklist-change-sets/{id}/discard` | `changeset.apply` | Throw the proposal away; nothing is written to the checklist |

Nothing generated enters the checklist unreviewed: generation writes a *pending change set*, and `POST /checklist-change-sets/{id}/apply` is the only path that writes `checklist_items`.

`POST /checklist-modules/{id}/messages` follows the same pre-flight/stream split as
`POST /conversations/{id}/messages`: everything that needs a status code happens before the stream opens, and the streamed proposal is written server-side into a change set rather than posted back by the client.

`GET /checklist-items/export` and `POST /checklist-items/clear-results` are declared **before** the parameterised `/checklist-items/{item_id}` routes because FastAPI matches in declaration order: a literal segment declared after a parameterised one is swallowed as an id, so a `GET /checklist-items/{item_id}` added later would take the export's requests unless the export stays first. The export is capped at `checklist_export_max_rows` (default 5000) rows and returns `409 EXPORT_TOO_LARGE` over that limit, since `openpyxl` builds the whole workbook in memory.

Recording a result is open to every member while editing what a test expects is not: a tester must be able to record what they saw without being able to rewrite what was expected. That is why `result.record` sits in the `viewer` set and `item.edit` does not — otherwise the cheapest way to make a failing test pass is to edit the expectation.

### Mock Data Generator

**Mock Data Datasets**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/checklist-modules/{id}/mock-data` | any member | A module's mock dataset summary and its applied records; an empty summary before the first generation |
| `POST` | `/checklist-modules/{id}/mock-data-generations` | `generate.run` | Publish a generation job; returns the dataset in `generating` status. `409 PROJECT_NOT_READY` while the project is being re-indexed |
| `GET` | `/checklist-modules/{id}/mock-data-change-sets` | any member | List the dataset's proposed change sets, newest first |
| `GET` | `/checklist-modules/{id}/mock-data-messages` | any member | Read the dataset's refinement chat |
| `POST` | `/checklist-modules/{id}/mock-data-messages` | any member | Refine the dataset by chat; **streams the reply and proposes changes** |
| `GET` | `/checklist-modules/{id}/mock-data/export.json` | any member | Export the dataset's records as a JSON array of field maps |
| `GET` | `/checklist-modules/{id}/mock-data/export.xlsx` | any member | Export the dataset's records as a spreadsheet |

**Mock Data Records**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `DELETE` | `/mock-data-records/{id}` | `mockdata.edit` | Soft-delete one record |

**Mock Data Change Sets**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/mock-data-change-sets/{id}/apply` | `changeset.apply` | Apply the named operations, or all of them; nothing is written to the dataset until this is called |
| `POST` | `/mock-data-change-sets/{id}/discard` | `changeset.apply` | Throw the proposal away; nothing is written to the dataset |

A module's mock dataset generates, reviews, and fails independently of its checklist —
one module can carry a test plan, a mock dataset, both, or neither. Generation is grounded:
it fails rather than inventing fields when no schema-shaped code exists under the module's
`source_path`. Export is capped at `mock_data_export_max_rows` (default 5000) records and
returns `409 EXPORT_TOO_LARGE` over that limit, the same reasoning
`checklist_export_max_rows` already documents above.

### Audit trail

Append-only. Both routes are **reads**, and that is the point: there is no route that writes an
audit row, which is how append-only shows up on the wire and not only in the schema. Both are
admin-only and instance-wide — auth, account and export events span no project, so a per-project
scope would not describe this read.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/audit-events` | admin | A page of events, newest first. Filters: `eventType`, `actorUserId`, `projectId`, `outcome` (`success`/`failure`), `occurredFrom`, `occurredTo`, `search`, plus `page`/`limit`. A bare `occurredTo` date (no time component) is inclusive of that whole day. `search` matches `actorEmail`/`targetLabel` by substring and `ipAddress` by prefix. `sort` accepts the literal `created_at` only — the one ordering the `created_at` index supports — with `sortDirection` defaulting to `desc` |
| `GET` | `/audit-events/{id}` | admin | One event with its full `details` payload, `ipAddress`, and a `current` block saying whether the actor is still active and the target still exists. `404 AUDIT_EVENT_NOT_FOUND` |

Every write and every export in the app records one of **37 event types** catalogued in
`app/core/audit.py`; which operations must is a rule (`.claude/rules/audit-trail.md`), enforced in
both directions by `tests/test_audit_coverage.py`. The payload is an allowlist per event type,
never a diff of dirty attributes, and it never carries a secret or any content — no message text,
and `targetLabel` is `NULL` for a conversation. Retention is `AUDIT_RETENTION_DAYS` (default `0`,
keep forever), pruned by the worker's existing 60-second tick.

### Notifications

One caller's own rows, always — `is_admin` gates nothing here and there is no administrative
view. Ownership resolves through `resolve_notification_owner`, so a notification belonging to
someone else is `404 NOTIFICATION_NOT_FOUND`, never `403`. None of these writes records an audit
event: exemption 5 in `.claude/rules/audit-trail.md`.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/notifications` | any user | A page of the caller's own notifications, newest first. Filters: `unreadOnly`, `projectId`, `eventType`, plus `page`/`limit` |
| `GET` | `/notifications/unread-count` | any user | `{ count }`, what the bell polls |
| `POST` | `/notifications/mark-all-read` | any user | Marks every visible unread row read. Declared **before** `/{notification_id}/read` so the literal path wins the match |
| `POST` | `/notifications/{id}/read` | any user | Marks one read. `404 NOTIFICATION_NOT_FOUND` for a row that does not exist or belongs to someone else |
| `GET` | `/notification-preferences` | any user | Every event type in the catalogue, gaps filled in as on, plus `emailEnabled` (`false` until Phase 2.4) |
| `PUT` | `/notification-preferences` | any user | Replaces the whole set. `400 UNKNOWN_EVENT_TYPE` for an event type the catalogue does not name |

## Layout

```
backend/
├── pyproject.toml        # dependencies, ruff + pytest + mypy config
├── logging.json          # uvicorn --log-config; reaches the --reload parent process
├── alembic.ini
├── alembic/versions/     # migrations
├── .env.example
├── app/
│   ├── main.py           # create_app(): middleware, CORS, routers, Kafka lifespan
│   ├── config.py         # Settings (pydantic-settings) + get_settings()
│   ├── cli.py            # `python -m app.cli seed-admins | restore-system-roles`
│   ├── api/
│   │   ├── deps.py       # CurrentUser / AdminUser dependencies
│   │   └── routes/
│   │       ├── index.py    # GET /
│   │       ├── health.py   # GET /health, /health/live, /health/ready
│   │       ├── auth.py     # POST /auth/login, /refresh, /change-password, ...
│   │       ├── users.py    # /users CRUD + reset-password
│   │       ├── projects.py # /projects CRUD + reindex + indexed-paths
│   │       ├── members.py  # /projects/{id}/members — grant, change role, revoke
│   │       ├── roles.py    # /roles CRUD + GET /permissions (admin-only router)
│   │       ├── conversations.py # /conversations CRUD + the SSE answer endpoint
│   │       ├── checklist_modules.py # /checklist-modules CRUD + generate + chat
│   │       ├── checklist_items.py   # /checklist-items CRUD + export
│   │       ├── checklist_change_sets.py # apply + discard change sets
│   │       ├── mock_data_datasets.py    # module-scoped mock data reads, generate, chat, export
│   │       ├── mock_data_records.py     # DELETE /mock-data-records/{id}
│   │       ├── mock_data_change_sets.py # apply + discard mock-data change sets
│   │       ├── audit_events.py # GET /audit-events, GET /audit-events/{id} (admin, reads only)
│   │       ├── notifications.py # /notifications list + unread-count + mark-read(-all)
│   │       └── notification_preferences.py # GET/PUT /notification-preferences
│   ├── core/
│   │   ├── access.py     # resolve_project_scope + require_permission — the only two
│   │   ├── audit.py      # the 37-event catalogue, the per-event field allowlist, AuditRecorder
│   │   ├── crypto.py     # SecretBox (PAT encryption at rest) + scrub
│   │   ├── errors.py     # AppError, ErrorCode, exception handlers
│   │   ├── grant_cache.py # Redis read-through cache for a user's project grants
│   │   ├── logging.py    # the one log format, shared by all four processes
│   │   ├── middleware.py # AuthContextMiddleware — identity, grants, password-change gate
│   │   ├── passwords.py  # password policy (length, common-password blocklist)
│   │   ├── permissions.py # the permission catalogue + the viewer/editor/owner sets
│   │   ├── rate_limit.py # Redis-backed login rate limiting
│   │   ├── role_seed.py  # ensure_system_roles — used by the migration, tests and the CLI
│   │   ├── repo_url.py   # clone-URL validation: https, allowlist, private-address refusal
│   │   └── security.py   # hashing, JWT access tokens, opaque refresh tokens
│   ├── db/session.py     # async engine + sessionmaker
│   ├── ingestion/        # one indexing run, stage by stage
│   │   ├── pipeline.py   # clone → walk → chunk → embed → upsert → generation swap
│   │   ├── cloner.py     # DNS-pinned git clone with size and time caps
│   │   ├── walker.py     # which files are worth indexing
│   │   ├── chunker.py    # language-aware splitting, line ranges preserved
│   │   ├── embedder/     # Ollama / OpenAI / Voyage behind one protocol
│   │   ├── vector_store.py # Qdrant: model-named collections, generation-scoped points
│   │   └── errors.py     # Terminal vs Retryable — what decides whether a job retries
│   ├── queue/
│   │   ├── topics.py     # IngestionMessage, the topic names, the retry ladder
│   │   ├── protocol.py   # IngestionQueue + TopicProducer + the in-memory double
│   │   ├── producer.py   # KafkaIngestionQueue + ensure_topics
│   │   ├── consumer.py   # handle_message, the routing ladder, the polling loop
│   │   └── retry.py      # holds a delayed message until it is due, then re-queues it
│   ├── rag/               # one answer, stage by stage
│   │   ├── retriever.py  # embed query → filtered search → merge adjacent → typed spans
│   │   ├── chat.py       # Ollama / OpenAI chat models behind build_chat_model
│   │   ├── prompts.py    # the classify/rewrite prompt, the grade prompt, the answer prompt
│   │   ├── answerer.py   # runs the graph, turns its stream writes into SSE events
│   │   ├── grounding.py  # the refusal, and the checks that make a bad answer visible
│   │   └── graph/        # the LangGraph state graph
│   │       ├── state.py  # TurnState — the shared dict every node reads and writes
│   │       ├── nodes.py  # classify → retrieve → grade/loop → generate, each with a fallback
│   │       └── build.py  # wires the nodes into the compiled graph, incl. routing edges
│   ├── checklist/        # QA Checklist: modules, generation, chat, change sets
│   ├── mockdata/          # Mock Data Generator: generation, model output contracts, change-set ops
│   ├── worker.py          # the worker entrypoint: consumers + the reconcile sweep
│   ├── models/            # SQLAlchemy models: User, RefreshToken, Project, Conversation,
│   │                      #   Message, Role, RolePermission, ProjectMembership, ...
│   ├── repositories/      # the only layer that issues `select`
│   ├── schemas/
│   │   ├── base.py       # ApiModel — the snake_case → camelCase boundary
│   │   ├── auth.py
│   │   ├── errors.py
│   │   ├── pagination.py
│   │   ├── project.py
│   │   └── user.py
│   └── services/          # AuthService, UserService, ProjectService
└── tests/
    ├── conftest.py           # app/client/db_session fixtures, real Postgres + Redis
    ├── factories.py          # create_user / create_project
    ├── test_api_model.py     # the camelCase wire contract
    ├── test_route_coverage.py
    ├── test_access.py
    ├── ...                   # one file per module; `ls tests/` is the current list
    ├── test_m0_acceptance.py # PRD §7's M0 success criterion, end to end
    └── test_m1_acceptance.py # PRD §7's M1 access/gating/scoping criteria
```

## Configuration

Settings come from the environment, falling back to `.env`, falling back to the defaults in
`config.py`. Every value has a default, so `.env` is optional. `get_settings()` is
`lru_cache`d and injected via `Depends`, so tests override it rather than mutating the
environment.

- [`.env.example`](.env.example) — the variable names and their defaults, grouped. Copy it to
  `.env`.
- [`../docs/configuration.md`](../docs/configuration.md) — what each one does, which ones fail
  silently when set wrong, and the four the app refuses to boot without under
  `APP_ENV=production`.

The things worth knowing before you touch any of it:

- **Complex types are JSON.** `CORS_ORIGINS`, `REPO_HOST_ALLOWLIST` and
  `BOOTSTRAP_ADMIN_EMAILS` must be JSON arrays (`["http://localhost:3000"]`), not
  comma-separated strings — pydantic-settings parses complex types as JSON.
- **The API and the worker share one configuration.** Both run the same image and must agree
  on every datastore, on `PAT_ENCRYPTION_KEY` (the API encrypts a PAT, the worker decrypts it
  to clone), and on `EMBEDDING_*` (the worker embeds documents, the API embeds the question —
  and the collection name is derived from provider + model + width). A mismatch is a runtime
  failure, not a startup one.
- **`KAFKA_INGEST_PARTITIONS` is the ingestion concurrency cap**, not a tuning knob beside
  one. Worker replicas beyond the partition count sit idle.
- **`GRANT_CACHE_TTL_SECONDS` (default `300`) is a backstop, not the invalidation mechanism.**
  Every membership and role write evicts explicitly; the TTL only bounds how long an eviction
  Redis dropped can serve a stale permission set. A Redis outage is not a lockout — the cache
  falls back to querying Postgres.
- **`RAG_MIN_SCORE` is the relevance floor below which no answer is generated at all** — the
  turn ends with a fixed refusal rather than a model call.
- **`RAG_CLASSIFY_INTENT`, `RAG_GRADE_EVIDENCE` and `RAG_MAX_RETRIEVAL_ATTEMPTS` tune the graph
  for the graph's helper nodes.** The first two default on and each short-circuits to its failure-path value when
  off, so there is one code path rather than two; `RAG_MAX_RETRIEVAL_ATTEMPTS` (default `2`)
  bounds how many times the grader may ask for a re-search before the answer is generated anyway
  and flagged `weak_evidence`.
- **`AUDIT_RETENTION_DAYS` (default `0`) means keep every audit row forever.** A positive value
  is a window the worker's reconcile tick enforces, and it is the only lever over that table —
  the single delete path takes a cutoff and nothing else.

## Conventions

`snake_case` internally, **`camelCase` on the wire**. Every request and response schema
inherits `ApiModel` from `app/schemas/base.py`, which applies Pydantic's `to_camel` alias
generator; FastAPI serializes by alias, so a field named `last_indexed_commit` in Python
appears as `lastIndexedCommit` in JSON. Nothing converts casing by hand.

A schema on plain `BaseModel` silently ships `snake_case` keys and breaks the API contract.
`tests/test_api_model.py` guards the boundary — none of the routes here has a
multi-word field, so nothing else would catch a regression.

Full conventions in [`CLAUDE.md`](../CLAUDE.md) and
[`docs/PRD.md`](../docs/PRD.md) §5.1; the enforceable rules are in
[`.claude/rules/`](../.claude/rules).

## Development

`make infra` (from the repo root) must be running before `pytest` — the suite runs against
real Postgres and real Redis, never SQLite or a mock (see `tests/conftest.py`).

```bash
uv run alembic upgrade head              # apply migrations
uv run python -m app.cli seed-admins     # create the bootstrap admins (idempotent)
uv run python -m app.cli restore-system-roles   # repair viewer/editor/owner (idempotent)
uv run ruff check .                      # lint
uv run ruff format .                     # format
uv run mypy .                            # typecheck (strict, over app and tests)
uv run pytest                            # tests — needs `make infra` first
```

`restore-system-roles` reconciles `viewer`, `editor` and `owner` back to the permission sets in
`app/core/permissions.py` and bumps the grant-cache epoch so every cached snapshot is re-read.
It reuses the same `ensure_system_roles` the migration and the test harness call, so a restore
on a live box and a restore between tests cannot drift apart. Unlike `seed-admins`, it is not
part of the container entrypoint — it exists for an instance whose seed was damaged by direct
SQL or a partial restore.

`ruff` is configured (in `pyproject.toml`) with `ANN` for type-hint coverage, `T20` to ban
`print()`, and `LOG`/`G` for logging correctness — the rules in
[`.claude/rules/clean-code.md`](../.claude/rules/clean-code.md) are enforced at the lint step,
not by review.
