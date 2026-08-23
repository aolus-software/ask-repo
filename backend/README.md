# AskRepo Backend

FastAPI service for AskRepo — the codebase-aware assistant described in
[`docs/PRD.md`](../docs/PRD.md).

This is currently a skeleton: it identifies itself and reports health. The RAG /
LangGraph work (project ingestion, Dev Knowledge, QA List, mock data generation)
lands on top of it starting with milestone M0.

## Requirements

- Python 3.13 (`uv` will fetch it for you)
- [uv](https://docs.astral.sh/uv/) — `curl -LsSf https://astral.sh/uv/install.sh | sh`

## Running locally

```bash
cd backend
cp .env.example .env          # optional — every value has a default
uv sync                       # creates .venv and installs dependencies
uv run uvicorn app.main:app --reload
```

The API is then on <http://localhost:8000>, with interactive docs at
<http://localhost:8000/docs>.

## Running in Docker

```bash
cd infra && docker compose up --build
```

That brings up the API alongside Postgres, Qdrant, Redis, and the frontend.
Source is bind-mounted, so `--reload` picks up your edits.

## Routes

| Method | Path            | Returns                                                       |
| ------ | --------------- | ------------------------------------------------------------- |
| `GET`  | `/`             | `{app, version, date}` — service identity and server time     |
| `GET`  | `/health`       | `{status, app, version, env, timestamp}` — overview           |
| `GET`  | `/health/live`  | `{status}` — liveness; `ok` whenever the process is up         |
| `GET`  | `/health/ready` | `{status, checks}` — readiness; `checks` is empty until M0     |

```bash
curl -s localhost:8000/ | jq
curl -s localhost:8000/health | jq
```

`/health/ready` exists so datastore probes (Postgres, Qdrant) can be added to
`checks` later without changing the response shape — a dependency going down
flips `status` to `degraded` while `/health/live` stays `ok`.

## Layout

```
backend/
├── pyproject.toml        # dependencies, ruff + pytest config
├── .env.example
├── app/
│   ├── main.py           # create_app(): CORS, router mounting
│   ├── config.py         # Settings (pydantic-settings) + get_settings()
│   ├── schemas/
│   │   └── base.py       # ApiModel — the snake_case → camelCase boundary
│   └── api/routes/
│       ├── index.py      # GET /
│       └── health.py     # GET /health, /health/live, /health/ready
└── tests/
    ├── conftest.py       # TestClient fixture
    ├── test_api_model.py # the camelCase wire contract
    └── test_meta_routes.py
```

Settings come from the environment, falling back to `.env`, falling back to the
defaults in `config.py`. `get_settings()` is `lru_cache`d and injected via
`Depends`, so tests can override it.

## Configuration

See [`.env.example`](.env.example). Two notes:

- `CORS_ORIGINS` must be a **JSON array** (`["http://localhost:3000"]`), not a
  comma-separated string — pydantic-settings parses complex types as JSON.
- `DATABASE_URL`, `QDRANT_URL`, and `REDIS_URL` are wired but unread; no code
  touches them yet. They land at M0 (Postgres for users/projects, Redis for
  auth rate limiting) and M1 (Qdrant for vectors, Redis for the ingestion queue).

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

```bash
uv run ruff check .        # lint
uv run ruff format .       # format
uv run pytest              # tests
```

`ruff` is configured (in `pyproject.toml`) with `ANN` for type-hint coverage, `T20` to ban
`print()`, and `LOG`/`G` for logging correctness — the rules in
[`.claude/rules/clean-code.md`](../.claude/rules/clean-code.md) are enforced at the lint step,
not by review.
