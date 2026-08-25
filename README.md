# AskRepo

Ask questions about a codebase and get grounded, cited answers.

AskRepo clones a repository, indexes it into a vector store, and answers natural-language
questions about it — citing the actual files and functions the answer came from. It is
**self-hosted and single-tenant**: an organization runs its own instance on its own
infrastructure, provisions accounts for its developers, and keeps it on the internal
network.

Built as a learning project for RAG, LangChain/LangGraph, prompt engineering, and context
management — against real repositories rather than tutorial data.

> **Status: M0 shipped.** Auth & accounts are implemented — admin-provisioned users, login,
> forced first-login password change, and login rate limiting. M1 (project ingestion) has
> not started. See [Roadmap](#roadmap) for what lands when, and
> [`docs/PRD.md`](docs/PRD.md) for the full specification.

## Features (planned)

| | Feature | What it does |
| --- | --- | --- |
| **0** | Auth & Accounts | Admin-provisioned email/password accounts, JWT access + revocable refresh tokens |
| **1** | Project ingestion | Submit a repo URL; AskRepo clones, indexes, and tracks it. Projects are shared instance-wide |
| **2** | Dev Knowledge | Ask questions against an indexed project; answers cite real file paths and functions. Conversations stay private to each user |
| **3** | QA List | Shared, browsable Q&A pairs — the team's knowledge base and regression set |
| **4** | Mock Data Generator | Auto-generate synthetic Q&A pairs from code, plus a lightweight eval score |

## Stack

**Backend** FastAPI · Python 3.13 · uv · SQLAlchemy + Alembic · LangGraph · LangChain
**Frontend** Next.js 16 · React 19 · TypeScript · Tailwind CSS 4 · Bun
**Data** Postgres 17 · Qdrant · Redis
**Models** Ollama (qwen2.5-coder, qwen3) with a hosted-API adapter for comparison
**Infra** Docker Compose · Caddy · VPN/Tailscale only, not internet-facing

## Repository layout

```
ask-repo/
├── backend/            FastAPI service — see backend/README.md
├── frontend/           Next.js UI — see frontend/README.md
├── infra/              Dockerfiles + docker-compose.yml
├── docs/
│   ├── PRD.md          Product requirements — the source of truth
│   └── design.md       Design tokens, layout geometry, component inventory
├── .claude/            Rules, commands and skills for AI agents
└── Makefile            Task runner — `make help`
```

## Quick start

**Requirements:** Docker with Compose v2, plus [uv](https://docs.astral.sh/uv/) and
[Bun](https://bun.sh) if you want to run the apps outside containers.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # backend
curl -fsSL https://bun.sh/install | bash          # frontend
```

### Everything in Docker

One command, nothing else installed:

```bash
git clone <this-repo> && cd ask-repo
BOOTSTRAP_ADMIN_PASSWORD=<a real passphrase> make up
```

`BOOTSTRAP_ADMIN_PASSWORD` must be set before the first `make seed` or `make up` — the seed
command refuses to run without it rather than inventing a password, and the backend
container will not come up without it either. There is deliberately no built-in default: a
password committed to this repository would be a password every reader of it already knows.
Log in as `superuser@example.com` (or `admin@example.com`) with that password; both accounts
are created with `must_change_password` set, so the first login forces a change.

### Datastores in Docker, apps on your machine

The usual development loop — hot reload on both apps, datastores containerized:

```bash
make setup                                        # uv sync + bun install
make infra                                        # postgres + qdrant + redis, waits until healthy
make migrate                                       # apply database migrations
BOOTSTRAP_ADMIN_PASSWORD=<a real passphrase> make seed  # create the bootstrap admins
make dev                                           # both dev servers, Ctrl-C stops both
```

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:3000> |
| API | <http://localhost:8000> ([docs](http://localhost:8000/docs)) |
| Qdrant dashboard | <http://localhost:6333/dashboard> |
| Postgres | `localhost:5432` |
| Redis | `localhost:6379` |

Every environment value has a fallback, so this comes up with no `.env` file. To customize,
create `infra/.env` — the variable names are in
[`infra/docker-compose.yml`](infra/docker-compose.yml).

Verify the API is alive:

```bash
curl -s localhost:8000/ | jq
curl -s localhost:8000/health | jq
```

## Make targets

`make help` lists everything. The ones you'll reach for:

| Target | Does |
| --- | --- |
| `make setup` | Install backend + frontend dependencies |
| `make infra` | Start postgres + qdrant + redis, wait until healthy |
| `make migrate` | Apply database migrations |
| `make seed` | Create the bootstrap admin accounts (idempotent) |
| `make dev` | Both dev servers together |
| `make dev-backend` / `make dev-frontend` | One dev server |
| `make check` | lint + format-check + typecheck + test — what CI runs |
| `make lint` / `make format` | Both apps |
| `make test` | Backend test suite |
| `make test-one T=tests/test_api_model.py` | One test file, or `T=-k\ camel_case` |
| `make build` | Production frontend build |
| `make up` / `make down` | Whole stack in Docker |
| `make infra-down` | Stop datastores **and delete their volumes** |
| `make psql` / `make redis-cli` | Shell into a running datastore |
| `make clean` | Remove caches and build output |

Individual datastores: `make docker-start-pg`, `docker-start-redis`, `docker-start-qdrant`, and
the matching `docker-stop-*`.

## Starting without `make`

`make` is a convenience wrapper — nothing depends on it. The equivalent raw commands:

**Datastores only**

```bash
docker compose -f infra/docker-compose.yml up -d --wait postgres qdrant redis
docker compose -f infra/docker-compose.yml ps          # check health
docker compose -f infra/docker-compose.yml stop postgres qdrant redis
```

**Backend** (from `backend/`)

```bash
cp .env.example .env                              # optional; every value has a default
uv sync                                           # creates .venv
uv run alembic upgrade head                       # apply migrations
BOOTSTRAP_ADMIN_PASSWORD=<a real passphrase> \
  uv run python -m app.cli seed-admins            # create the bootstrap admins
uv run uvicorn app.main:app --reload --port 8000
uv run pytest                                     # tests
uv run pytest tests/test_api_model.py             # one file
uv run pytest -k camel_case                       # one test by name
uv run ruff check . && uv run ruff format .
uv run mypy .                                     # typecheck
```

**Frontend** (from `frontend/`)

```bash
cp .env.example .env.local                        # optional
bun install
bun dev
bun run build                                     # catches type errors dev tolerates
bun lint
bunx tsc --noEmit                                 # typecheck
bunx prettier --write .                           # format
```

**Whole stack in Docker**

```bash
docker compose -f infra/docker-compose.yml up --build
docker compose -f infra/docker-compose.yml logs -f backend
docker compose -f infra/docker-compose.yml down
```

Run the Compose commands from anywhere with `-f infra/docker-compose.yml`, or drop the flag and
run them from inside `infra/`.

## Roadmap

Milestones from [`docs/PRD.md`](docs/PRD.md) §6, built in order:

- [x] **M0** — Auth & accounts: admin-provisioned users, login, forced first-login password change, rate limiting
- [ ] **M1** — Project ingestion: clone + index, status tracking, re-index, Redis + ARQ job queue
- [ ] **M2** — Dev Knowledge: RAG Q&A against a ready project, private conversations
- [ ] **M3** — LangGraph: intent routing + self-critique loop
- [ ] **M4** — QA List: shared storage, save / view / filter / re-run
- [ ] **M5** — Mock Data Generator: synthetic Q&A + eval scoring
- [ ] **M6** — Local vs hosted model comparison

**Phase 2** (after M6): per-project RBAC — users assigned to projects, roles per project.
Phase 1 is deliberately built so this is a change to one access-resolver function rather
than a rewrite (PRD §2.1, §4.1).

## Security

AskRepo stores repository access credentials and clones user-supplied URLs from inside a
private network. Both are handled deliberately — see [`SECURITY.md`](SECURITY.md) and
[`docs/PRD.md`](docs/PRD.md) §9. Do not expose an instance to the public internet: it has
no self-service account flows and its threat model assumes trusted, authenticated users.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports and feature requests go through the
[issue templates](.github/ISSUE_TEMPLATE).

## Documentation

- [`docs/PRD.md`](docs/PRD.md) — product requirements, schemas, milestones, security model
- [`docs/design.md`](docs/design.md) — design tokens, typography, layout geometry, component inventory
- [`backend/README.md`](backend/README.md) — API setup, routes, configuration
- [`frontend/README.md`](frontend/README.md) — UI setup and scripts
- [`CLAUDE.md`](CLAUDE.md) — architecture notes and the conventions that bite, for AI agents and humans alike
- [`.claude/rules/`](.claude/rules) — nine enforceable conventions (Python, API contract, design system, forms, navigation)
