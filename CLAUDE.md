# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AskRepo — a self-hosted, single-tenant codebase assistant. It clones a repository, indexes it
into a vector store, and answers natural-language questions about it with citations. One
organization runs one instance on its own internal network.

**`docs/PRD.md` is the source of truth** for scope, schemas, the access model, milestones, and
the security model. It outranks every other doc and outranks the code. When code and the PRD
disagree, that is a contradiction to report — not a doc to quietly rewrite.

**Status: M0, M1 and M2 (backend) shipped.** The backend serves an index route, health checks,
the full auth/accounts surface (admin-provisioned users, login, forced first-login password
change, session rotation, login rate limiting), the project CRUD routes, and the conversation
routes that answer questions about an indexed project. **All four datastores are read** —
Postgres, Redis, Qdrant, and Kafka.

M1 is complete end to end. `app/ingestion/` holds the cloner, walker, chunker, embedder adapter,
Qdrant vector store, and `IngestionPipeline`; `app/queue/` holds the message format, topics, both
protocols, `KafkaIngestionQueue`, `IngestionConsumer`, and the delayed-retry `RetryConsumer`; and
`app/worker.py` is the separate process that runs them, plus the reconcile sweep that recovers
jobs the broker never received. `POST /projects` publishes a job and a worker picks it up.

M2 is complete too. `app/rag/` holds the retriever, the chat-model adapter, the prompts, the
`Answerer` that sequences rewrite → retrieve → generate, and the grounding guardrails;
`app/services/conversation.py` and `app/api/routes/conversations.py` put it behind five routes.
`POST /conversations/{id}/messages` streams the answer over Server-Sent Events. **There is no
LangGraph yet** — the answerer is a plain sequence, and M3 replaces that one file with a graph.

The frontend has not moved: it is still the landing page from scaffolding, with no API client
and no auth screens. Do not assume a module exists because the PRD describes it — the PRD
describes the destination.

## Commands

The `Makefile` at the root wraps everything; `make help` lists all targets.

```bash
make setup            # install backend + frontend dependencies
make infra            # start postgres + qdrant + redis + kafka + ollama, wait until healthy
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
docker compose up --build                 # backend, worker, frontend, postgres, qdrant, redis, kafka, ollama
docker compose config --quiet             # validate before committing compose changes
docker compose logs -f backend
```

`uv` is required for the backend and is not installed by default:
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Architecture

Two apps, a worker, four datastores, one Compose file. `backend/` is FastAPI + Python 3.13 (uv);
`frontend/` is Next.js 16 + React 19 + Tailwind 4 (bun); `infra/` holds both Dockerfiles and
`docker-compose.yml`.

The parts below are the ones you cannot infer from any single file.

### All four datastores are read

`Settings` declares `database_url`, `qdrant_url`, `redis_url`, and `kafka_bootstrap_servers`,
and Compose points them at live services. Postgres is read through the repository layer
(`app/repositories/`) for users, refresh tokens, and projects; Redis is read by the login rate
limiter (`app/core/rate_limit.py`) and by nothing else — **it does not back the job queue**.
`qdrant_url` is read by `app/ingestion/vector_store.py` and by `build_store_factory` in
`app/api/routes/projects.py`.

Kafka is read from both processes: the API lifespan calls `ensure_topics` and starts
`KafkaIngestionQueue`, and the worker (`app/worker.py`) runs `IngestionConsumer` on the ingest
topic plus one `RetryConsumer` per retry rung. `InMemoryIngestionQueue` remains the test double
for both protocols, so route, service, consumer and retry tests all run with no broker — the
only suite needing a real one is `tests/test_ingestion_integration.py`, behind the `integration`
marker.

### Configuration flows one way

`app/config.py` defines `Settings` (pydantic-settings). Precedence is environment → `.env` →
the defaults in the class. `get_settings()` is `lru_cache`d and injected with `Depends`, so
tests override it rather than mutating the environment. Nothing else reads `os.environ`.

### The wire boundary: `snake_case` in, `camelCase` out

Python attributes and Postgres columns are `snake_case`. Every JSON body is `camelCase`. The
translation happens in exactly one class — `ApiModel` in `app/schemas/base.py`, which applies
Pydantic's `to_camel` alias generator. Every request and response schema inherits it.

A schema on plain `BaseModel` silently ships `snake_case` keys. That is a defect, not a style
choice, and `tests/test_api_model.py` exists to catch it. It matters most for the **SSE event
payloads** in `app/schemas/conversation.py`: those never pass through a `response_model`, so
FastAPI validates nothing about them, and the `SSE_EVENT_MODELS` tuple that test walks is the
only thing holding them to the rule. An event added to the stream but not to the tuple ships
unchecked.

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
volume — and reindex re-clones rather than `git pull`.

**M1's job queue is Kafka, not Redis + ARQ.** Earlier PRD drafts argued against Kafka by name,
and that technical argument was never disputed — it was **overridden for a non-technical
reason**: `docs/PRD.md` §1 names learning as the project's primary goal, and §2's goal list now
carries event streaming. This is settled, not a live contradiction: `docs/PRD.md` §5's job-queue note
now records the decision, the accepted costs, and their mitigations. Do not "fix" the code
toward ARQ, and do not reintroduce Redis as a queue — Redis backs login rate limiting only.

### The lease is the deduplication boundary

Kafka delivers at least once, so the same job can arrive twice — a rebalance, a redelivered
uncommitted offset, a reconcile sweep racing a retry. **What stops two workers indexing the same
project is a database lease on the project row** (`ProjectRepository.claim`), not the offset and
not the partition key. The service-level "is it already running?" check is a fast path for a nicer
API response; removing the lease because "the service already checks" is a defect, not a
simplification.

Two consequences: a worker that dies holding a lease is recovered when the lease expires (the
reconcile sweep in `app/worker.py` re-enqueues it), and a duplicate delivery is *supposed* to be
cheap — it costs one refused claim. That is why the consumer can safely absorb an error and leave
the offset uncommitted.

### A long job pauses its partitions and keeps polling

aiokafka measures liveness as *fetcher idle time*: go longer than `max.poll.interval.ms` without
calling `getmany` and the client leaves the group on its own. An index can run for twenty minutes.
So the consumer pauses every assigned partition and **keeps polling throughout the job** — each
poll returns nothing but holds the member's seat. Every partition, not just the one being worked,
because a keep-alive poll discards what it returns and an unpaused sibling would have its jobs
read and thrown away.

Raising `max.poll.interval.ms` instead is not an acceptable substitute, and there is deliberately
no setting for it. The same pattern serves the retry ladder: Kafka has no delay primitive, so
`RetryConsumer` holds the partition head until it is due rather than sleeping.

### The collection name carries the embedding model

Qdrant collections are named `code_chunks__provider__model__dimensions` (`collection_name` in
`app/ingestion/vector_store.py`), and the width is **probed at worker startup**, never declared.
A model change therefore lands in a different collection instead of silently mixing incompatible
vectors. Each project records the collection it wrote to, which is how `DELETE /projects/{id}`
knows where its points live. Never hardcode a collection name.

### Reindex is a generation swap

A reindex does not empty the project's points and refill them — that would take a `ready` project
offline for the length of a clone-and-embed. New vectors are written under an incremented
`active_generation`, the project switches to reading it only on success, and the old generation is
deleted afterwards. **A reindex that fails part-way leaves the previous index intact and still
serving.**

### Nothing derived from clone output is stored or logged unscrubbed

A PAT is embedded in the clone URL, so it can surface in git's stderr, an exception message, or a
traceback. Everything on that path goes through `scrub` before it is written to `Project.error`
or a log line. `docs/PRD.md` §9: a token must not survive into anything an operator can read.

`repo_url` is user-supplied and fetched from **inside** a private network, where `10.0.x.x` and
internal service names resolve. Validation (https-only, host allowlist, private-address
rejection at connect time) is a security control, not input hygiene. See `docs/PRD.md` §9.

### Auth is admin-provisioned

No public registration, no email verification, no self-service reset, and therefore no mail
provider anywhere in the stack. An admin creates accounts; `must_change_password` forces a
change on first login. Access tokens are stateless JWTs (15 min); refresh tokens are opaque,
stored hashed so they can be revoked, and rotate on use.

### Identity is resolved once, in middleware

`AuthContextMiddleware` decodes the bearer token, loads the user row, and stashes a frozen
`AuthenticatedUser` on `request.state`. `CurrentUser` / `AdminUser` read it. Two consequences:
the user row is read on **every** authenticated request (which is what makes deactivation
immediate, per `docs/PRD.md:101`), and the middleware is registered **before** `CORSMiddleware`
so CORS ends up outermost and the gate's `403` carries CORS headers.

### The forced-password-change gate is structural

While `must_change_password` is set, every route outside `/auth` returns
`403 PASSWORD_CHANGE_REQUIRED` — enforced by middleware, not by a dependency, so a route added
later is covered without opting in. Adding a route group under a **new** prefix means deciding
whether it belongs in `GATE_EXEMPT_PREFIXES`.

### One error shape

Every error the app raises is `{"detail": {"code": ..., "message": ...}}`, built by `AppError`.
`ErrorCode` values are a wire contract — add members, never rename them. `422` adds a `fields`
map keyed by the `camelCase` field name.

## Rules

Twelve rule files in `.claude/rules/`. Read the ones your change touches.

| Rule | Read it when |
| --- | --- |
| `contradiction-halt.md` | **Always.** A request may contradict a rule, the PRD, or correctness — stop and report rather than silently working around it |
| `documentation.md` | **Always.** If your change makes a doc wrong, fixing that doc is part of the same change |
| `clean-code.md` | Writing Python — type hints, docstrings, logging, suppressions |
| `response-api.md` | Any route, schema, or status code |
| `router.md` | Any `APIRouter` — layout, dependencies, the CRUD shape, access scoping |
| `persistence.md` | Any model, repository, migration, or session code |
| `ingestion.md` | Anything under `app/ingestion/` or `app/queue/` — leases, pausing, error classes, collections |
| `rag.md` | Anything under `app/rag/`, or the conversation service/routes — generation filters, grounding, the SSE contract, the shielded write |
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
The M0–M2 screens are shipped: `/login`, `/change-password`, `/` (dashboard), `/projects`,
`/projects/[id]`, `/ask`, `/ask/[conversationId]`, and `/settings/users`.

### Next is a backend-for-frontend, not a thin client

`docs/PRD.md` §5 calls the frontend "minimal", and it has outgrown that deliberately —
`docs/superpowers/specs/2026-08-29-frontend-m0-m2-design.md` §2.1 records why. **Next holds the
session and calls the API on the browser's behalf**, so no token is ever readable by a script on
the page.

- **Two cookies, both set by Next, both httpOnly and `Path=/`**: `askrepo_access` (the JWT) and
  `askrepo_session` (the backend's own refresh cookie, stored as a verbatim `name=value` pair
  because `REFRESH_COOKIE_NAME` is operator-configurable). The `Path=/` differs from the
  backend's `/auth` scope on purpose: middleware runs at `/projects` and is only sent cookies
  whose path matches.
- **`app/api/[...path]/route.ts` is the one route the browser talks to.** It attaches the bearer,
  strips `set-cookie` from every backend response, and relays the body untouched. Only the three
  `/api/auth/*` handlers write cookies.
- **Refresh happens in two places, and that split is structural.** A Server Component cannot set
  a cookie, so a token refreshed during render could never be persisted. Navigations refresh in
  `middleware.ts`; browser fetches and the answer stream refresh inside the proxy, on the `401`
  status line, before any body is read — which is what keeps it safe on the SSE route.
- **The answer stream is piped through the proxy unbuffered**, preserving `text/event-stream`,
  `Cache-Control: no-cache` and `X-Accel-Buffering: no`.
- **`API_URL` is server-only** and replaces `NEXT_PUBLIC_API_URL`. Under Compose it is the
  service name `http://backend:8000` — the inverse of the old rule, because the fetch now happens
  server-side.

Vitest runs in `make test` alongside pytest. The suite covers the pieces that fail silently: the
nav filter, the error envelope, the SSE parser, single-flight refresh, the proxy's
refresh-and-retry, the answer stream's ordering contract, and the form shells' error routing.

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

`API_URL` is read on the **server** only — by the proxy, the middleware, and `serverFetch`. It
does not need to be reachable from the browser, so under Compose it is the service name
`http://backend:8000`, not the published host port.

## Phase 1 sharing is intended

Every authenticated user can list and query every project. That is designed behaviour, not a
leak — `docs/PRD.md` §4.1 and `SECURITY.md` both say so, and `SECURITY.md` puts malicious
authenticated users outside the threat model. Do not "fix" it, and do not report it as a
vulnerability. Per-project access control is phase 2.
