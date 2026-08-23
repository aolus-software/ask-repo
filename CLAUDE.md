# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AskRepo — a self-hosted, single-tenant codebase assistant. It clones a repository, indexes it
into a vector store, and answers natural-language questions about it with citations. One
organization runs one instance on its own internal network.

**`docs/PRD.md` is the source of truth** for scope, schemas, the access model, milestones, and
the security model. It outranks every other doc and outranks the code. When code and the PRD
disagree, that is a contradiction to report — not a doc to quietly rewrite.

**Status: pre-M0.** The backend serves an index route and health checks. There is no auth, no
ingestion, no RAG, no database layer. Do not assume a module exists because the PRD describes
it — the PRD describes the destination.

## Commands

The `Makefile` at the root wraps everything; `make help` lists all targets.

```bash
make setup            # install backend + frontend dependencies
make infra            # start postgres + qdrant + redis only, wait until healthy
make dev              # both dev servers together (needs `make infra` first)
make check            # lint + format-check + typecheck + test, as CI would
make test-one T=tests/test_api_model.py
make up               # whole stack in Docker, apps included
```

Single-service datastore control: `make docker-start-pg`, `docker-start-redis`,
`docker-start-qdrant`, and the matching `docker-stop-*`. Shells: `make psql`, `make redis-cli`.

The underlying commands, if you need them directly:

```bash
# Backend — from backend/
uv sync                                   # create .venv, install deps
uv run uvicorn app.main:app --reload      # dev server on :8000, docs at /docs
uv run pytest                             # all tests
uv run pytest tests/test_api_model.py     # one file
uv run pytest -k camel_case               # one test by name substring
uv run ruff check . && uv run ruff format .

# Frontend — from frontend/
bun install
bun dev                                   # dev server on :3000
bun run build                             # catches type errors the dev server tolerates
bun lint

# Whole stack — from infra/
docker compose up --build                 # backend, frontend, postgres, qdrant, redis
docker compose config --quiet             # validate before committing compose changes
docker compose logs -f backend
```

`uv` is required for the backend and is not installed by default:
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Architecture

Two apps, three datastores, one Compose file. `backend/` is FastAPI + Python 3.13 (uv);
`frontend/` is Next.js 16 + React 19 + Tailwind 4 (bun); `infra/` holds both Dockerfiles and
`docker-compose.yml`.

The parts below are the ones you cannot infer from any single file.

### Datastores are wired but unread

`Settings` declares `database_url`, `qdrant_url`, and `redis_url`, and Compose points them at
live services, but **no code reads them yet**. Postgres and Redis activate at M0 (users,
sessions, login rate limiting); Qdrant and the Redis job queue at M1. A missing database layer
is the current state, not a bug to fix on sight.

### Configuration flows one way

`app/config.py` defines `Settings` (pydantic-settings). Precedence is environment → `.env` →
the defaults in the class. `get_settings()` is `lru_cache`d and injected with `Depends`, so
tests override it rather than mutating the environment. Nothing else reads `os.environ`.

### The wire boundary: `snake_case` in, `camelCase` out

Python attributes and Postgres columns are `snake_case`. Every JSON body is `camelCase`. The
translation happens in exactly one class — `ApiModel` in `app/schemas/base.py`, which applies
Pydantic's `to_camel` alias generator. Every request and response schema inherits it.

A schema on plain `BaseModel` silently ships `snake_case` keys. That is a defect, not a style
choice, and `tests/test_api_model.py` exists to catch it — no route shipped so far has a
multi-word field, so nothing else would.

### Access: shared now, per-project later

This is the single most consequential design constraint in the repo.

Phase 1 shares every project with every user on the instance. Phase 2 adds per-project RBAC.
To make that a change rather than a rewrite, **all read scoping goes through one access
resolver** — a function answering "which project IDs may this user query?" In phase 1 it
returns everything; phase 2 replaces its body and no route changes.

A route, service, or query that filters projects on its own is a defect **even when its output
is currently correct**. `docs/PRD.md` §7 makes it testable: read scoping happens in exactly one
function, confirmed by grep.

### `created_by` is not ownership

Projects and QA pairs carry `created_by`. It is attribution, and it gates destructive
operations (delete, reindex) alongside `is_admin`. **It never scopes reads.** Treating it as an
owner field reintroduces the per-user filtering the access resolver exists to centralize.

### `403` vs `404` is a security decision

- **`403`** when the caller may see the resource but not do this to it — deleting a project
  someone else created. Project existence is deliberately public.
- **`404`** when the caller should not learn it exists — another user's conversation.

Backwards, this either leaks existence or hides something the user can see in a list.

### Soft delete does not reach Qdrant

Every Postgres table carries `deleted_at`, and queries filter `deleted_at IS NULL`. Vector
points have no such column, and a query-time filter would be one forgotten call away from
serving deleted content. So: **Postgres rows soft-delete; the matching Qdrant points
hard-delete, in the same operation.**

### Ingestion is fire-and-forget, and disk is scratch

`POST /projects` returns immediately and the clone+index runs in the background. The cloned
working copy is **deleted after indexing**, so `/data/repos` is scratch space, not a persistent
volume — and reindex re-clones rather than `git pull`. Jobs move from
`BackgroundTasks` to Redis + ARQ at M1, because a restart mid-index otherwise leaves a project
stuck at `indexing` forever.

`repo_url` is user-supplied and fetched from **inside** a private network, where `10.0.x.x` and
internal service names resolve. Validation (https-only, host allowlist, private-address
rejection at connect time) is a security control, not input hygiene. See `docs/PRD.md` §9.

### Auth is admin-provisioned

No public registration, no email verification, no self-service reset, and therefore no mail
provider anywhere in the stack. An admin creates accounts; `must_change_password` forces a
change on first login. Access tokens are stateless JWTs (15 min); refresh tokens are opaque,
stored hashed so they can be revoked, and rotate on use.

## Rules

Nine rule files in `.claude/rules/`. Read the ones your change touches.

| Rule | Read it when |
| --- | --- |
| `contradiction-halt.md` | **Always.** A request may contradict a rule, the PRD, or correctness — stop and report rather than silently working around it |
| `documentation.md` | **Always.** If your change makes a doc wrong, fixing that doc is part of the same change |
| `clean-code.md` | Writing Python — type hints, docstrings, logging, suppressions |
| `response-api.md` | Any route, schema, or status code |
| `router.md` | Any `APIRouter` — layout, dependencies, the CRUD shape, access scoping |
| `design-system.md` | Any `.tsx` or `.css` — tokens, shadcn, dark mode, spacing |
| `forms.md` | Any form — dialog vs page, validation ownership, field composition |
| `navigation.md` | Sidebar, breadcrumbs, or adding a route |
| `audit-findings.md` | Writing an audit report |

One command in `.claude/commands/`: `audit-flow.md` — read-only sweep, writes
`docs/audit-findings.md`, fixes nothing.

Project skills live in `.claude/skills/`, symlinked to `.agents/skills/` and pinned by
`skills-lock.json`. Where a rule and a skill overlap, the rule wins: `clean-code.md` covers
Python specifics, the installed `clean-code` skill covers general principles.

## Enforcement is at the lint step, not in review

`backend/pyproject.toml` selects `ANN` (type-hint coverage), `T20` (bans `print()`),
`LOG`/`G` (logging correctness), `RUF`, plus `E`/`F`/`I`/`UP`/`B`. `# noqa` and
`# type: ignore` need a reason on the same line. A rule that lint can enforce should be
enforced there — if you add a convention, wire it into the config in the same change.

## Frontend

App Router, React 19, Tailwind CSS 4 (CSS-first `@theme`, no `tailwind.config.js` for tokens).
One route so far — the landing page. No API client and no component library installed yet.

**`docs/design.md` is the design reference**, and `frontend/app/globals.css` implements it.
Palette values come from the Fexend design system; the structure is one semantic token per role,
redefined under `.dark`. Two consequences worth internalizing:

- **Never write a `dark:` colour utility in a component.** The token already knows what dark
  means. `bg-card`, not `bg-white dark:bg-slate-900`. If no token fits, add one to `globals.css`
  — the only file allowed to contain a raw hex colour.
- **Never use a palette utility.** `bg-zinc-50` and `text-slate-600` name a colour, not a role,
  so they do not follow the theme. Use `bg-card`, `text-muted-foreground`, `border-border`.

Components come from **shadcn on the Base UI base**, installed by CLI into `components/ui/`.
Composition uses **`render={<Component />}`, never `asChild`** — `asChild` does not exist here
and fails silently. `docs/design.md` lists the intended component set per milestone; install a
row when the screen needing it lands.

`NEXT_PUBLIC_API_URL` is inlined into the client bundle at build time, so it must be an address
the **browser** can reach — under Compose that is the published `http://localhost:8000`, never
the `http://backend:8000` service name.

## Phase 1 sharing is intended

Every authenticated user can list and query every project. That is designed behaviour, not a
leak — `docs/PRD.md` §4.1 and `SECURITY.md` both say so, and `SECURITY.md` puts malicious
authenticated users outside the threat model. Do not "fix" it, and do not report it as a
vulnerability. Per-project access control is phase 2.
