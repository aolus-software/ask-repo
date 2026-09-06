# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

AskRepo — a self-hosted, single-tenant codebase assistant. It clones a repository, indexes it
into a vector store, and answers natural-language questions about it with citations. One
organization runs one instance on its own internal network.

**`docs/PRD.md` is the source of truth** for scope, schemas, the access model, milestones, and
the security model. It outranks every other doc and outranks the code. When code and the PRD
disagree, that is a contradiction to report — not a doc to quietly rewrite.

**Status: M0, M1, M2, M3, M4 (backend), M4.5, and M5 shipped.** The backend serves an index route, health
checks, the full auth/accounts surface (admin-provisioned users, login, forced first-login
password change, session rotation, login rate limiting), the project CRUD routes, the
conversation routes that answer questions about an indexed project, the eighteen QA
Checklist routes that name modules over a repository, generate reviewed test plans for them,
refine them by chat, record results, and export the grid to `.xlsx`, and the ten Mock Data
Generator routes that generate, refine by chat, and export a grounded sample dataset per
module. **All four datastores are read** — Postgres, Redis, Qdrant, and Kafka. The worker
reads a chat model as well as an embedder: checklist and mock-data generation each run a
model in that process, ingestion does not.

M1 is complete end to end. `app/ingestion/` holds the cloner, walker, chunker, embedder adapter,
Qdrant vector store, and `IngestionPipeline`; `app/queue/` holds the message format, topics, both
protocols, `KafkaIngestionQueue`, `IngestionConsumer`, and the delayed-retry `RetryConsumer`; and
`app/worker.py` is the separate process that runs them, plus the reconcile sweep that recovers
jobs the broker never received. `POST /projects` publishes a job and a worker picks it up.

M2 is complete too. `app/rag/` holds the retriever, the chat-model adapter, the prompts, the
`Answerer` adapter, and the grounding guardrails; `app/services/conversation.py` and
`app/api/routes/conversations.py` put it behind five routes. `POST /conversations/{id}/messages`
streams the answer over Server-Sent Events.

M3 is shipped too. `app/rag/graph/` holds the state graph — `nodes.py` for each node,
`build.py` for the compiled graph, `state.py` for the shared `TurnState` — and `answerer.py` is
now the adapter that runs it and turns its stream writes into SSE events. The sequencing is
intent routing (codebase question / conversational / out of scope) followed, on the codebase
path, by a corrective retrieval loop: a grader checks the retrieved excerpts and asks for a
better search query when they fall short, bounded by `RAG_MAX_RETRIEVAL_ATTEMPTS`. The loop
grades retrieval, not the finished answer — see `docs/PRD.md` §5's Orchestration row and §6's
M3 line for why.

M4 is shipped too, and it replaced the QA List that shipped at this milestone earlier —
`docs/superpowers/specs/2026-09-01-m4-qa-checklist-design.md` §0 records why. `app/checklist/`
holds the generator, the model's output contracts, and the file rebuild; `app/queue/checklist.py`
holds the job handler the worker runs; `app/services/checklist_module.py`,
`checklist_item.py`, `checklist_change_set.py` and `checklist_export.py` hold the business rules;
and `checklist_modules.py`, `checklist_items.py` and `checklist_change_sets.py` put them behind
eighteen routes.

M4.5 is shipped too, backend-only — no new routes and no frontend surface. `app/rag/chat.py`'s
`build_chat_model` gained a native Anthropic branch alongside `ollama` and `openai`; a new
`app/rag/errors.py` taxonomy (`TerminalChatError` / `RetryableChatError`, classified by exception
name) is wired into checklist generation's retry path so a rejected key or an unknown model
stops retrying instead of burning the retry ladder; a boot-time capability probe
(`app/rag/capability.py`) runs in both `app/main.py`'s lifespan and `app/worker.py`'s startup and
fails the process if the configured chat model cannot do structured output, rather than failing
on the first generation; and `CHECKLIST_MAX_FILES_PER_JOB` caps how many files one checklist
generation run maps, reporting the excess in `skipped_paths` — a coverage note alongside the
pre-existing `partial_paths`, not the same field.

Two facts about it outrank the rest. **The generator scrolls the index; it does not search it**
— top-k retrieval cannot report what it left out, and a test plan that silently omits a file is
worse than one that says which files it covered. And **nothing writes `checklist_items` except
the apply path**: generation and the refinement chat both write a *pending change set*, and
`POST /checklist-change-sets/{id}/apply` is the only code that turns a proposal into a row.

M5 is shipped too: for a QA Checklist module, `app/mockdata/` generates a grounded sample
dataset (its own `mock_data_datasets`/`mock_data_records`/`mock_data_change_sets`/
`mock_data_messages` tables, independent of the checklist's own status and lease), refined
by chat through a second `propose_target` on the same answer graph (`app/rag/graph/`)
alongside the checklist's own, applied through the same generate/change-set/apply discipline
as the checklist, and exported as JSON or `.xlsx`.

The M0–M2, M4 and M5 frontend is shipped: auth screens, the app shell, projects, the streamed
answer surface, admin user management, the QA Checklist (`/checklist`, `/checklist/[moduleId]`),
and that module screen's Mock Data tab, with Next acting as a backend-for-frontend (see the
Frontend section below). Later milestones are not built — do not assume a module exists because
the PRD describes it; the PRD describes the destination.

## Commands

The `Makefile` at the root wraps everything; `make help` lists all targets.

```bash
make setup            # install backend + frontend dependencies
make infra            # start postgres + qdrant + redis + kafka, wait until healthy
make pull-models      # pull the embedding + chat models into the HOST ollama
make dev              # both dev servers + the worker (needs `make infra` and `ollama serve`)
make check            # lint + format-check + typecheck + test, as CI would
make test-one T=tests/test_api_model.py
make up               # whole stack in Docker, apps included (development)
make setup-prod       # preflight a deploy box; then build-prod / migrate-prod / up-prod
```

Single-service datastore control: `make docker-start-pg`, `docker-start-redis`,
`docker-start-qdrant`, and the matching `docker-stop-*`. Shells: `make psql`, `make redis-cli`.

**Ollama is not a Compose service in the development stack.** It runs on the host, because a
container gets no GPU on macOS and only the Docker VM's memory allowance — the same 22-minute
CPU reduce call `docs/PRD.md` §6 cites for M4.5. `make dev` and `make worker` warn (never
fail) when nothing answers on `:11434`, since a hosted-provider instance correctly has none.
The container is still in `docker-compose.yml` behind its profile: `make infra
OLLAMA_IN_DOCKER=1` re-enables it, and that also requires `EMBEDDING_BASE_URL` and
`CHAT_BASE_URL` set to `http://ollama:11434` in `infra/.env`, because they now default to the
host. The **production** stack is unchanged and still runs Ollama in a container.

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
docker compose up --build                 # backend, worker, frontend, postgres, qdrant, redis, kafka
#   ^ ollama is NOT here: it runs on the host and the app containers reach it at
#     host.docker.internal:11434, so bind it with
#     `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"` or the worker crash-loops
#     probing embedding dimensions. `make infra OLLAMA_IN_DOCKER=1` puts the
#     container back, and then both base URLs must be set to http://ollama:11434.
docker compose config --quiet             # validate before committing compose changes
docker compose logs -f backend
```

`uv` is required for the backend and is not installed by default:
`curl -LsSf https://astral.sh/uv/install.sh | sh`.

## Architecture

Two apps, a worker, four datastores, one Compose file. `backend/` is FastAPI + Python 3.13 (uv);
`frontend/` is Next.js 16 + React 19 + Tailwind 4 (bun); `infra/` holds four Dockerfiles —
`{backend,frontend}.Dockerfile` for development and `{backend,frontend}.prod.Dockerfile` for
production — plus `docker-compose.yml` and the standalone `docker-compose.prod.yml`.

**The production compose file is standalone, never an overlay.** Compose merges `volumes` by
target path rather than replacing the list, so `-f docker-compose.yml -f docker-compose.prod.yml`
would keep the development bind-mounts of the working copy over `/app`. Every `-prod` Make
target passes the production file alone. The procedure is `docs/deployment.md`.

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

There is a second opt-in marker, `model`, for `tests/test_rag_model_integration.py`: it needs a
served chat model rather than a broker, and it is what keeps the prompts honest. Everything else
drives `ScriptedChatModel`, so no ordinary test can catch a prompt that routes or cites wrongly
— run `uv run pytest -m model` after editing anything in `app/rag/prompts.py`.

### Configuration flows one way

`app/config.py` defines `Settings` (pydantic-settings). Precedence is environment → `.env` →
the defaults in the class. `get_settings()` is `lru_cache`d and injected with `Depends`, so
tests override it rather than mutating the environment. Nothing else reads `os.environ`.

**`docs/configuration.md` documents every setting**; the `.env.example` files carry names and
defaults only, grouped, with no inline prose. A new `Settings` field lands in all three
(`config.py`, `backend/.env.example`, `docs/configuration.md`) in the same change.

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

**The checklist sweep is the exception, and it has to be.** A project leaves `pending` the moment
anyone claims it, so it stops matching the sweep on its own. A module is already `generating`
before its claim and stays `generating` throughout, so status says nothing about whether a worker
holds it — and the sweep re-publishes with a deliberately fresh `job_id` so the claim *cannot*
refuse it. A duplicate there costs a whole generation, not a refused claim. `claim_stranded`
therefore stamps `updated_at` on the rows it returns, which is what stops the 60-second tick
re-publishing the same module forever. For the same reason a run that fails but is coming back
calls `ChecklistModuleRepository.defer`: rolling back alone leaves a five-minute lease owned by a
run that is over, and the retry is then refused by its own dead predecessor.

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

### The checklist is a diff, not a list

A generated checklist never lands as rows. Both producers — the background generator and the
refinement chat — write a **pending change set**: a JSON list of `add` / `update` / `remove`
operations, each with the rationale that argued for it. A human ticks the ones they accept and
`POST /checklist-change-sets/{id}/apply` writes exactly those. Discarding writes nothing at all.

Two consequences that are not visible from any single file. **A regeneration cannot destroy a
recorded result**: it proposes operations against the rows that exist, and a `pass` a tester
recorded last week survives unless somebody ticks a `remove` and applies it. And **`status` and
`current_result` are outside what an operation may write** — the apply path runs an explicit
column allowlist rather than `setattr`, because `changes` originates in a model's output and an
unchecked key would let it claim an observation nobody made.

One pending change set per module, deliberately: concurrent refinement is out of scope for v1,
and the UI disables Generate and the composer while one is waiting rather than letting the
second request fail with a `409` after the user typed a paragraph.

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

Thirteen rule files in `.claude/rules/`. Read the ones your change touches.

| Rule | Read it when |
| --- | --- |
| `contradiction-halt.md` | **Always.** A request may contradict a rule, the PRD, or correctness — stop and report rather than silently working around it |
| `documentation.md` | **Always.** If your change makes a doc wrong, fixing that doc is part of the same change |
| `clean-code.md` | Writing Python — type hints, docstrings, logging, suppressions |
| `response-api.md` | Any route, schema, or status code |
| `router.md` | Any `APIRouter` — layout, dependencies, the CRUD shape, access scoping |
| `persistence.md` | Any model, repository, migration, or session code |
| `ingestion.md` | Anything under `app/ingestion/` or `app/queue/` — leases, pausing, error classes, collections |
| `rag.md` | Anything under `app/rag/`, the conversation service/routes, or the checklist's refinement chat — generation filters, grounding, the SSE contract, the shielded write |
| `design-system.md` | Any `.tsx` or `.css` — tokens, shadcn, dark mode, spacing |
| `forms.md` | Any form — dialog vs page, validation ownership, field composition |
| `navigation.md` | Sidebar, breadcrumbs, or adding a route |
| `frontend-bff.md` | Any `middleware.ts`, the `app/api/[...path]` proxy, `/api/auth/*`, or session/refresh code — cookies, the refresh split, SSE piping |
| `audit-findings.md` | Writing an audit report |

Five commands in `.claude/commands/`: `audit-flow.md` (read-only sweep, writes
`docs/audit-findings.md`, fixes nothing), `commit.md` (stage and commit, never push), `open-pr.md`
(push and open a PR from the real `.github/PULL_REQUEST_TEMPLATE.md`), `scaffold-route.md`
(generate a new resource's schema/model/repository/service/router per `router.md`/
`persistence.md`/`response-api.md`), and `rag-check.md` (run the model-backed prompt suite,
`uv run pytest -m model`).

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
The M0–M2, M4 and M5 screens are shipped: `/login`, `/change-password`, `/` (dashboard),
`/projects`, `/projects/[id]`, `/ask`, `/ask/[conversationId]`, `/settings/users`,
`/checklist`, and `/checklist/[moduleId]` — the last of which now carries a Mock Data tab
beside the checklist grid, no new route of its own.

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
