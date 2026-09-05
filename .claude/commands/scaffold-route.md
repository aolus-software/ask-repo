---
name: scaffold-route
description: "Scaffold a new FastAPI resource end-to-end (schema, model, migration, repository, service, router) following this repo's router/persistence/response-api conventions, or add one route to an existing resource."
risk: caution
source: local
date_added: "2026-09-05"
---

# Scaffold Route

`$ARGUMENTS` names the resource and scope — e.g. `scaffold-route widgets` for a full CRUD
resource, or `scaffold-route add a reindex action to projects` to add one custom route to an
existing router. If the resource name or which of the five canonical routes are needed isn't
clear from the arguments, ask before generating anything.

## Before writing anything

1. Read `.claude/rules/router.md`, `.claude/rules/response-api.md`, and
   `.claude/rules/persistence.md` in full. This command exists to apply those rules, not to
   reinvent a shape — most of what follows is a checklist derived from them, not new guidance.
2. Read one existing resource end-to-end as the template: `app/api/routes/projects.py`,
   `app/services/project_service.py`, its repository, model, and schema (or the checklist
   module family if the new resource needs more than plain CRUD — generation, a pending
   change set, a chat). Match the existing naming and layout, not just the rules in isolation.
3. Decide, and say explicitly before generating code — these are product decisions, not
   something to infer from the resource's name:
   - Does reading this resource need to go through the access resolver
     (`docs/PRD.md` §4.1/§5.1), or is it instance-shared like projects?
   - Does any route need `created_by`/`is_admin` gating, and is it a `403` or a `404` shape
     per `response-api.md`'s security-decision table?
   - Which of the five canonical routes (list/get/create/update/delete) does this resource
     actually need? Do not generate a route it has no use for.

## What to generate, per layer

- **Schema** (`app/schemas/<resource>.py`) — every model inherits `ApiModel`. A list route
  gets a request query model built on `ListQuery` (subclassed, never placed beside a scalar
  query param — `rag.md`'s query-model note applies to any router, not just conversations),
  and a response with pagination meta, never a bare array.
- **Model** (`app/models/<resource>.py`) — `TimestampMixin` and, unless this table is a
  documented exception like `refresh_tokens`, `SoftDeleteMixin`. A UUID primary key generated
  in application code, never a database sequence. `timestamptz`, UTC.
- **Migration** — a real Alembic revision with a working `downgrade()`. Never `create_all`.
  Write it by hand if autogenerate can't express the intent.
- **Repository** (`app/repositories/<resource>_repository.py`) — the only layer importing
  `select`/`insert`/`update`/`delete` for this resource. Reads start from `active_select()`
  unless they genuinely need deleted rows, in which case name the method accordingly
  (`get_including_deleted`). Any bulk update sets `updated_at` explicitly — the ORM's
  `onupdate` only fires on a per-row flush. A sortable list exposes a
  `SORTABLE_FIELDS: frozenset[str]` allowlist and raises on anything outside it.
- **Service** (`app/services/<resource>_service.py`) — owns business rules, transactions, and
  the `created_by`/`is_admin` check for destructive operations. Never builds a SQL statement
  itself; calls the repository.
- **Router** (`app/api/routes/<resource>.py`) — exactly one `router = APIRouter(prefix=...,
  tags=...)`, registered in `app/main.py`. Every handler: validated input → resolve
  dependencies → exactly one service call → typed return. No `if`, no data reshaping, no
  `try`/`except` in the handler body, no more than one service call. Declare `response_model`,
  `status_code`, and a `responses={...}` block traced from what the handler and its
  dependencies can actually raise — using `ERROR_RESPONSES` fragments, never copied from a
  sibling route.

## After generating

1. Walk `response-api.md`'s "Declaring error responses" checklist for every route generated:
   what can the service raise, is it behind an auth or rate-limit dependency, is it a
   destructive op (→ always `403`), does it take a body or typed query params (→ always
   `422`), can it `404` on a parent resource too.
2. Add the new route(s) to `backend/README.md`'s route table — it must stay exhaustive
   (`.claude/rules/documentation.md`).
3. Surface, rather than silently decide, anything from step 3 above that turned out to be
   ambiguous while writing the code — per `.claude/rules/contradiction-halt.md`.
4. Do not run `make check`, tests, or formatters without confirming first if scaffolding is
   happening inside a git worktree with install/dependency constraints — ask before running
   anything beyond what the user's session already allows.

## Rules

- Never invent a resource shape beyond the five canonical CRUD routes plus explicitly
  requested custom actions — `router.md`'s canonical table is the default, not a suggestion.
- Never scaffold a read path that filters on its own instead of going through the access
  resolver. If it's unclear whether this resource is phase-1-shared or already
  per-project-scoped, ask — do not guess.
- Never scaffold a success-envelope, an i18n wrapper, or a different error shape than
  `AppError`/`ErrorCode` — this API has none of those, and introducing one in a single new
  router produces two response shapes across the codebase.
