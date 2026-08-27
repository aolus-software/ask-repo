# AskRepo Backend

FastAPI service for AskRepo — the codebase-aware assistant described in
[`docs/PRD.md`](../docs/PRD.md).

M0 is shipped: the service identifies itself, reports health, and serves the full
auth/accounts surface — admin-provisioned users, login, forced first-login password
change, session rotation, and login rate limiting.

M1 is in progress. The project routes and the entire ingestion pipeline are here —
clone, walk, chunk, embed, and write to Qdrant — along with the Kafka producer. What is
missing is the consumer: **nothing runs the pipeline in the background yet**, so a new
project stays `pending`. The Dev Knowledge / QA List / mock-data work starts at M2.

## Requirements

- Python 3.13 (`uv` will fetch it for you)
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Running locally

The datastores must be up first — `make infra` from the repo root, or
`docker compose -f infra/docker-compose.yml up -d --wait postgres qdrant redis kafka`.
Postgres and Redis are enough to run the test suite; Qdrant is needed to index, and
Kafka to enqueue.

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

## Running in Docker

```bash
cd infra && docker compose up --build
```

That brings up the API alongside Postgres, Qdrant, Redis, Kafka, and the frontend.
Source is bind-mounted, so `--reload` picks up your edits.

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
is committed, so the project stays visible and the call can be retried.

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
│   │       └── projects.py # /projects CRUD + reindex; build_store_factory
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
│   │   ├── protocol.py   # IngestionQueue + the in-memory double
│   │   └── producer.py   # KafkaIngestionQueue + ensure_topics
│   ├── models/            # SQLAlchemy models: User, RefreshToken, Project
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

Settings come from the environment, falling back to `.env`, falling back to the
defaults in `config.py`. `get_settings()` is `lru_cache`d and injected via
`Depends`, so tests can override it.

## Configuration

See [`.env.example`](.env.example). A few notes:

- `CORS_ORIGINS` must be a **JSON array** (`["http://localhost:3000"]`), not a
  comma-separated string — pydantic-settings parses complex types as JSON.
- `DATABASE_URL` is read via the repository layer (`app/repositories/`) for users and
  refresh tokens, and `REDIS_URL` by the login rate limiter (`app/core/rate_limit.py`).
  `QDRANT_URL` is read by `app/ingestion/vector_store.py` and by `build_store_factory`
  in `app/api/routes/projects.py`, which reaches the collection a project recorded so
  a delete can hard-delete its points.
- Auth, password-policy, and bootstrap-admin settings are documented inline in
  `.env.example` — that file is the canonical list. `BOOTSTRAP_ADMIN_PASSWORD` has no
  default on purpose: seeding refuses to run without it rather than inventing one.

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
