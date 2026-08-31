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

M2 through M4 are shipped too: Dev Knowledge (streaming RAG Q&A over an indexed project),
M3's LangGraph intent routing and corrective retrieval loop, and the QA List — see the
`### Conversations` and `### QA List` route sections below. Only the Mock Data Generator
(M5) and the local-vs-hosted comparison (M6) remain.

## Requirements

- Python 3.13 (`uv` will fetch it for you)
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Running locally

The datastores must be up first — `make infra` from the repo root, or
`docker compose -f infra/docker-compose.yml up -d --wait postgres qdrant redis kafka`.
Postgres and Redis are enough to run the test suite; Qdrant is needed to index, Kafka to
enqueue, and Ollama to embed (unless `EMBEDDING_PROVIDER` points at a hosted API).

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

The API only *enqueues* indexing jobs. Nothing indexes until a worker is running, so a
new project sits at `pending` until you start one — in a second terminal:

```bash
cd backend
uv run python -m app.worker
```

It is the same codebase with a different entrypoint, so it reads the same `Settings` and
the same `.env`. One process runs the ingest consumer, one consumer per retry rung, and a
sweep every 60 seconds that re-enqueues jobs whose produce failed or whose worker died,
and prunes expired refresh tokens. Run more than one and they share the ingest topic's
partitions — two is the configured cap (`KAFKA_INGEST_PARTITIONS`).

## Running in Docker

```bash
cd infra && docker compose --profile ollama up --build
```

That brings up the API alongside Postgres, Qdrant, Redis, Kafka, and the frontend.
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

### QA List

The shared regression set. Access matches projects and inverts conversations: every
authenticated user reads every pair, and `created_by` (or an admin) gates editing, deleting,
and re-running. Setting `status` is the one write deliberately open to everyone — any user may
mark a pair `pass` or `fail` (`docs/PRD.md:338`).

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/qa-pairs` | any user | List saved pairs, paginated; filters for project, module, tag, source, status, creator, and search |
| `GET` | `/qa-pairs/tags` | any user | Distinct tags across the caller's scope, for the filter combobox |
| `GET` | `/qa-pairs/export` | any user | The same filters as the list route, as a downloadable `.xlsx` |
| `GET` | `/qa-pairs/{id}` | any user | One pair, with its citations and any pending re-run |
| `POST` | `/qa-pairs` | any user | Publish a finished assistant answer from a conversation the caller owns |
| `PATCH` | `/qa-pairs/{id}` | creator or admin | Edit module, question, expected result, or tags |
| `PUT` | `/qa-pairs/{id}/status` | any user | Record pass / fail / unreviewed |
| `POST` | `/qa-pairs/{id}/rerun` | creator or admin | Re-run the saved question; **streams the new answer** into a pending slot |
| `POST` | `/qa-pairs/{id}/rerun/accept` | creator or admin | Save the pending re-run over the stored answer; resets `status` to unreviewed |
| `DELETE` | `/qa-pairs/{id}/rerun` | creator or admin | Discard the pending re-run, leaving the stored answer untouched |
| `DELETE` | `/qa-pairs/{id}` | creator or admin | Soft-delete a pair |

`POST /qa-pairs` never takes answer text in the body — only a `messageId`. The server copies
the question and answer out of the message rows itself, and refuses with `409
ANSWER_INCOMPLETE` unless that message is a finished (`finishReason: "stop"`) assistant answer
in a conversation the caller owns; a stranger's conversation is `404`, never `403`, because
conversations are private.

`POST /qa-pairs/{id}/rerun` follows the same pre-flight/stream split as
`POST /conversations/{id}/messages`: everything that can return a status code other than `200`
— ownership, project readiness, the embedding-model guard — runs before the stream starts, and
the result lands in the pair's pending slot rather than overwriting the stored answer. A human
then calls `rerun/accept` to publish it or `DELETE .../rerun` to throw it away; accepting always
resets `status` to `unreviewed`; because a stale `pass` badge over a replaced answer is worse
than no badge at all.

`GET /qa-pairs/export` and `GET /qa-pairs/tags` are declared **before** `GET /qa-pairs/{id}` in
the router: FastAPI matches path segments in declaration order, so a literal path declared
after a parameterised one would be swallowed as a malformed id and 422 every request. The
export is capped at `QA_EXPORT_MAX_ROWS` (default 5000) rows and returns `409
EXPORT_TOO_LARGE` over that, since `openpyxl` builds the whole workbook in memory.

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
│   │       └── conversations.py # /conversations CRUD + the SSE answer endpoint
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
