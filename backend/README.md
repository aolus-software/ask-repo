# AskRepo Backend

FastAPI service for AskRepo — the codebase-aware assistant described in
[`docs/PRD.md`](../docs/PRD.md).

M0 is shipped: the service identifies itself, reports health, and serves the full
auth/accounts surface — admin-provisioned users, login, forced first-login password
change, session rotation, and login rate limiting.

M1 is complete. The project routes and the entire ingestion pipeline are here — clone,
walk, chunk, embed, and write to Qdrant — along with the Kafka producer, the consumer
that turns a queued message into an indexing run, the delayed-retry consumers, and
`app/worker.py`: the separate process that runs all of them and sweeps up jobs the
broker never received. `POST /projects` enqueues and a worker indexes.

M2 through M5 are shipped too: Dev Knowledge (streaming RAG Q&A over an indexed project),
M3's LangGraph intent routing and corrective retrieval loop, the QA Checklist, and the Mock
Data Generator — see the `### Conversations`, `### QA Checklist`, and `### Mock Data
Generator` route sections below. Only the local-vs-hosted comparison (M6) remains.

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
uv run uvicorn app.main:app --reload
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
| `DELETE` | `/users/{id}` | admin | Deactivate, revoking sessions |
| `POST` | `/users/{id}/reset-password` | admin | Set a temporary password |

### Projects

Every authenticated user can list and read **every** project — phase-1 sharing is intended, not
a leak (`docs/PRD.md` §4.1). Only the project's `created_by` or an admin may reindex or delete.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/projects` | any user | List all projects, paginated |
| `GET` | `/projects/{id}` | any user | One project |
| `POST` | `/projects` | any user | Register a repository and enqueue its first index |
| `POST` | `/projects/{id}/reindex` | creator or admin | Re-index; a run already in flight is a no-op |
| `DELETE` | `/projects/{id}` | creator or admin | Soft-delete the row and hard-delete its vectors |

`DELETE` is the one route that can return **`503 VECTOR_STORE_UNAVAILABLE`**: it must reach
Qdrant to satisfy `docs/PRD.md` §5.1's same-operation hard delete, and if Qdrant is down nothing
is committed, so the project stays visible and the call can be retried. It also soft-deletes
every conversation against the project, for every owner (`docs/PRD.md` §4.2).

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
`no_context`, `uncited_answer`, `unknown_paths`, or (M3) `weak_evidence` when the answer may not
be grounded.

A `: keep-alive` comment goes out every 15 seconds during any gap, and the response sets
`Cache-Control: no-cache` and `X-Accel-Buffering: no` so a proxy does not accumulate the
stream and deliver it in one piece.

### QA Checklist

Modules over an indexed repository — a user names a module ("Authentication"), points it at a path in the repository, and requests generation. A background job enumerates the module's files, proposes features and test cases with expected results grounded in the code, and produces a change set for review. Nothing generated enters the checklist unreviewed. Access matches projects and inverts conversations: every authenticated user reads every module and every module's chat, and `created_by` (or an admin) gates editing and deleting. Recording a test result is deliberately open to every authenticated user — a tester must be able to record what they observed without being able to rewrite what was expected.

**Checklist Modules**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/checklist-modules` | any user | List modules for readable projects, paginated |
| `POST` | `/checklist-modules` | any user | Name a module and point it at a path in the indexed repository |
| `GET` | `/checklist-modules/{id}` | any user | One module with its test cases, grouped by feature |
| `PATCH` | `/checklist-modules/{id}` | creator or admin | Rename or re-point the module |
| `DELETE` | `/checklist-modules/{id}` | creator or admin | Soft-delete the module, its items, its change sets, and its chat |
| `POST` | `/checklist-modules/{id}/generate` | any user | Publish a generation job; returns the module in `generating` status |
| `GET` | `/checklist-modules/{id}/change-sets` | any user | List the module's proposed change sets, newest first |
| `GET` | `/checklist-modules/{id}/messages` | any user | Read the module's refinement chat |
| `POST` | `/checklist-modules/{id}/messages` | any user | Refine the checklist by chat; **streams the reply and proposes changes** |

**Checklist Items**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/checklist-items` | any user | List test cases across modules, paginated; filters for project, module, feature, status, source, kind |
| `POST` | `/checklist-items` | any user | Add a test case by hand |
| `PATCH` | `/checklist-items/{id}` | creator or admin | Edit what a test expects (name, feature, expected result, notes) |
| `PUT` | `/checklist-items/{id}/result` | **any user** | Record a test result (current result and status); open to every user |
| `DELETE` | `/checklist-items/{id}` | creator or admin | Soft-delete the test case |
| `GET` | `/checklist-items/export` | any user | Export the filtered checklist as `.xlsx`, regardless of pagination limit |
| `POST` | `/checklist-items/clear-results` | **any user** | Reset the recorded result on every row the filter selects, within one module |

**Checklist Change Sets**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/checklist-change-sets/{id}/apply` | any user | Apply the named operations, or all of them; nothing is written to the checklist until this is called |
| `POST` | `/checklist-change-sets/{id}/discard` | any user | Throw the proposal away; nothing is written to the checklist |

Nothing generated enters the checklist unreviewed: generation writes a *pending change set*, and `POST /checklist-change-sets/{id}/apply` is the only path that writes `checklist_items`.

`POST /checklist-modules/{id}/messages` follows the same pre-flight/stream split as
`POST /conversations/{id}/messages`: everything that needs a status code happens before the stream opens, and the streamed proposal is written server-side into a change set rather than posted back by the client.

`GET /checklist-items/export` and `POST /checklist-items/clear-results` are declared **before** the parameterised `/checklist-items/{item_id}` routes because FastAPI matches in declaration order: a literal segment declared after a parameterised one is swallowed as an id, so a `GET /checklist-items/{item_id}` added later would take the export's requests unless the export stays first. The export is capped at `checklist_export_max_rows` (default 5000) rows and returns `409 EXPORT_TOO_LARGE` over that limit, since `openpyxl` builds the whole workbook in memory.

Recording a result is open to every authenticated user while editing what a test expects is not: a tester must be able to record what they saw without being able to rewrite what was expected.

### Mock Data Generator

**Mock Data Datasets**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/checklist-modules/{id}/mock-data` | any user | A module's mock dataset summary and its applied records; an empty summary before the first generation |
| `POST` | `/checklist-modules/{id}/mock-data-generations` | any user | Publish a generation job; returns the dataset in `generating` status |
| `GET` | `/checklist-modules/{id}/mock-data-change-sets` | any user | List the dataset's proposed change sets, newest first |
| `GET` | `/checklist-modules/{id}/mock-data-messages` | any user | Read the dataset's refinement chat |
| `POST` | `/checklist-modules/{id}/mock-data-messages` | any user | Refine the dataset by chat; **streams the reply and proposes changes** |
| `GET` | `/checklist-modules/{id}/mock-data/export.json` | any user | Export the dataset's records as a JSON array of field maps |
| `GET` | `/checklist-modules/{id}/mock-data/export.xlsx` | any user | Export the dataset's records as a spreadsheet |

**Mock Data Records**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `DELETE` | `/mock-data-records/{id}` | creator or admin | Soft-delete one record |

**Mock Data Change Sets**

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `POST` | `/mock-data-change-sets/{id}/apply` | any user | Apply the named operations, or all of them; nothing is written to the dataset until this is called |
| `POST` | `/mock-data-change-sets/{id}/discard` | any user | Throw the proposal away; nothing is written to the dataset |

A module's mock dataset generates, reviews, and fails independently of its checklist —
one module can carry a test plan, a mock dataset, both, or neither. Generation is grounded:
it fails rather than inventing fields when no schema-shaped code exists under the module's
`source_path`. Export is capped at `mock_data_export_max_rows` (default 5000) records and
returns `409 EXPORT_TOO_LARGE` over that limit, the same reasoning
`checklist_export_max_rows` already documents above.

## Layout

```
backend/
├── pyproject.toml        # dependencies, ruff + pytest + mypy config
├── alembic.ini
├── alembic/versions/     # migrations
├── .env.example
├── app/
│   ├── main.py           # create_app(): middleware, CORS, routers, Kafka lifespan
│   ├── config.py         # Settings (pydantic-settings) + get_settings()
│   ├── cli.py            # `python -m app.cli seed-admins`
│   ├── api/
│   │   ├── deps.py       # CurrentUser / AdminUser dependencies
│   │   └── routes/
│   │       ├── index.py    # GET /
│   │       ├── health.py   # GET /health, /health/live, /health/ready
│   │       ├── auth.py     # POST /auth/login, /refresh, /change-password, ...
│   │       ├── users.py    # /users CRUD + reset-password
│   │       ├── projects.py # /projects CRUD + reindex
│   │       ├── conversations.py # /conversations CRUD + the SSE answer endpoint
│   │       ├── checklist_modules.py # /checklist-modules CRUD + generate + chat
│   │       ├── checklist_items.py   # /checklist-items CRUD + export
│   │       ├── checklist_change_sets.py # apply + discard change sets
│   │       ├── mock_data_datasets.py    # module-scoped mock data reads, generate, chat, export
│   │       ├── mock_data_records.py     # DELETE /mock-data-records/{id}
│   │       └── mock_data_change_sets.py # apply + discard mock-data change sets
│   ├── core/
│   │   ├── access.py     # the phase-2 access-resolver seam
│   │   ├── crypto.py     # SecretBox (PAT encryption at rest) + scrub
│   │   ├── errors.py     # AppError, ErrorCode, exception handlers
│   │   ├── middleware.py # AuthContextMiddleware — identity + the password-change gate
│   │   ├── passwords.py  # password policy (length, common-password blocklist)
│   │   ├── rate_limit.py # Redis-backed login rate limiting
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
│   │   └── graph/        # the LangGraph state graph (M3)
│   │       ├── state.py  # TurnState — the shared dict every node reads and writes
│   │       ├── nodes.py  # classify → retrieve → grade/loop → generate, each with a fallback
│   │       └── build.py  # wires the nodes into the compiled graph, incl. routing edges
│   ├── checklist/        # QA Checklist: modules, generation, chat, change sets
│   ├── mockdata/          # Mock Data Generator: generation, model output contracts, change-set ops
│   ├── worker.py          # the worker entrypoint: consumers + the reconcile sweep
│   ├── models/            # SQLAlchemy models: User, RefreshToken, Project, Conversation, Message
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

The four things worth knowing before you touch any of it:

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
- **`RAG_MIN_SCORE` is the relevance floor below which no answer is generated at all** — the
  turn ends with a fixed refusal rather than a model call.
- **`RAG_CLASSIFY_INTENT`, `RAG_GRADE_EVIDENCE` and `RAG_MAX_RETRIEVAL_ATTEMPTS` tune the graph
  added in M3.** The first two default on and each short-circuits to its failure-path value when
  off, so there is one code path rather than two; `RAG_MAX_RETRIEVAL_ATTEMPTS` (default `2`)
  bounds how many times the grader may ask for a re-search before the answer is generated anyway
  and flagged `weak_evidence`.

## Conventions

`snake_case` internally, **`camelCase` on the wire**. Every request and response schema
inherits `ApiModel` from `app/schemas/base.py`, which applies Pydantic's `to_camel` alias
generator; FastAPI serializes by alias, so a field named `last_indexed_commit` in Python
appears as `lastIndexedCommit` in JSON. Nothing converts casing by hand.

A schema on plain `BaseModel` silently ships `snake_case` keys and breaks the API contract.
`tests/test_api_model.py` guards the boundary — none of the routes shipped so far has a
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
uv run ruff check .                      # lint
uv run ruff format .                     # format
uv run mypy .                            # typecheck (strict, over app and tests)
uv run pytest                            # tests — needs `make infra` first
```

`ruff` is configured (in `pyproject.toml`) with `ANN` for type-hint coverage, `T20` to ban
`print()`, and `LOG`/`G` for logging correctness — the rules in
[`.claude/rules/clean-code.md`](../.claude/rules/clean-code.md) are enforced at the lint step,
not by review.
