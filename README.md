# AskRepo

Ask questions about a codebase and get grounded, cited answers.

AskRepo clones a repository, indexes it into a vector store, and answers natural-language
questions about it — citing the actual files and functions the answer came from. It is
**self-hosted and single-tenant**: an organization runs its own instance on its own
infrastructure, provisions accounts for its developers, and keeps it on the internal
network.

Built as a learning project for RAG, LangChain/LangGraph, prompt engineering, and context
management — against real repositories rather than tutorial data.

> **Status: M0, M1, M2 and M3 shipped (backend).** Auth & accounts are implemented —
> admin-provisioned users, login, forced first-login password change, and login rate
> limiting — as are the project routes and the whole ingestion pipeline: clone, walk,
> chunk, embed, Qdrant, driven by a Kafka job queue and a separate worker process.
> `POST /projects` enqueues a repository and a worker indexes it in the background.
> M2 added Dev Knowledge: ask a question about a ready project and the answer streams
> back token by token over Server-Sent Events, cited to real files and line ranges,
> with conversations private to whoever had them. M3 turned the answer path into a
> LangGraph state graph: questions are routed (codebase question / conversational /
> out of scope) before anything is retrieved, and on the codebase path a grader
> checks the retrieved excerpts and re-searches with a better query when they fall
> short — the loop grades retrieval, not the finished answer, so streaming stays
> unaffected. **The M0–M2 frontend is shipped too**: sign in, change the forced initial password,
> add and re-index projects, ask questions with the answer streaming in, and manage
> accounts — all in a browser, with the session held in httpOnly cookies by Next rather
> than in the page. See [Roadmap](#roadmap) for what lands when, and
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
**Data** Postgres 17 · Qdrant · Redis · Kafka
**Models** Ollama (qwen2.5-coder, qwen3) with a hosted-API adapter for comparison
**Infra** Docker Compose · Caddy · VPN/Tailscale only, not internet-facing

## Repository layout

```
ask-repo/
├── backend/            FastAPI service — see backend/README.md
├── frontend/           Next.js UI — see frontend/README.md
├── infra/              Dockerfiles + compose files (dev and prod)
├── docs/
│   ├── PRD.md          Product requirements — the source of truth
│   ├── installation.md   Step-by-step local setup
│   ├── deployment.md     Running it for a team
│   ├── configuration.md  Every setting, what it does, what to change for production
│   └── design.md       Design tokens, layout geometry, component inventory
├── .claude/            Rules, commands and skills for AI agents
└── Makefile            Task runner — `make help`
```

## Quick start

The short version is below; [`docs/installation.md`](docs/installation.md) is the same thing
step by step, with a troubleshooting section.

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
make infra                                        # postgres + qdrant + redis + kafka, waits until healthy
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
| Kafka | `localhost:9092` |
| Ollama | `localhost:11434` (embeddings) |

The **ingestion worker** publishes no port — it is reached through Kafka, not HTTP.
`make up` runs two replicas of it, one per ingest partition. Running the apps locally
with `make dev` does *not* start a worker; see
[`backend/README.md`](backend/README.md#the-ingestion-worker) for how to run one.

Every environment value has a fallback, so this comes up with no `.env` file. To customize,
create `infra/.env` — every variable it accepts is listed in
[`docs/configuration.md`](docs/configuration.md#docker-compose-infraenv).

Verify the API is alive, then log in as a seeded admin (replace the password with the one you
set in `BOOTSTRAP_ADMIN_PASSWORD`):

```bash
curl -s localhost:8000/ | jq
curl -s localhost:8000/health | jq
curl -s -X POST localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<a real passphrase>"}' | jq
```

The login response carries an `accessToken` and a `user` object with `mustChangePassword: true`
— the account is unusable for anything outside `/auth` until `POST /auth/change-password`
clears that flag.

## Make targets

`make help` lists everything. The ones you'll reach for:

| Target | Does |
| --- | --- |
| `make setup` | Install backend + frontend dependencies |
| `make infra` | Start postgres + qdrant + redis + kafka + ollama, wait until healthy |
| `make migrate` | Apply database migrations |
| `make seed` | Create the bootstrap admin accounts (idempotent) |
| `make dev` | Both dev servers together |
| `make dev-backend` / `make dev-frontend` | One dev server |
| `make check` | lint + format-check + typecheck + test — what CI runs |
| `make lint` / `make format` | Both apps |
| `make test` | Backend test suite |
| `make test-one T=tests/test_api_model.py` | One test file, or `T=-k\ camel_case` |
| `make build` | Production frontend build |
| `make up` / `make down` | Whole stack in Docker (development) |
| `make setup-prod` | Check a box is ready to deploy; changes nothing |
| `make build-prod` / `make up-prod` | Production images and stack — see [`docs/deployment.md`](docs/deployment.md) |
| `make infra-down` | Stop datastores **and delete their volumes** |
| `make psql` / `make redis-cli` | Shell into a running datastore |
| `make clean` | Remove caches and build output |

Individual datastores: `make docker-start-pg`, `docker-start-redis`, `docker-start-qdrant`,
`docker-start-kafka`, and the matching `docker-stop-*`.

## Starting without `make`

`make` is a convenience wrapper — nothing depends on it. The equivalent raw commands:

**Datastores only**

```bash
docker compose -f infra/docker-compose.yml up -d --wait postgres qdrant redis kafka
docker compose -f infra/docker-compose.yml ps          # check health
docker compose -f infra/docker-compose.yml stop postgres qdrant redis kafka
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
docker compose -f infra/docker-compose.yml --profile ollama up --build
docker compose -f infra/docker-compose.yml logs -f backend
docker compose -f infra/docker-compose.yml down
```

Run the Compose commands from anywhere with `-f infra/docker-compose.yml`, or drop the flag and
run them from inside `infra/`.

## Configuration

Nothing needs configuring to run locally — every setting has a default and both `.env` files
are optional. The `.env.example` files list the variable names and defaults:

- [`backend/.env.example`](backend/.env.example) → `backend/.env`
- [`frontend/.env.example`](frontend/.env.example) → `frontend/.env.local`
- [`infra/.env.example`](infra/.env.example) → `infra/.env` for the Compose stack

**[`docs/configuration.md`](docs/configuration.md) explains what each one does**, which values
fail silently when set wrong, and the four the app refuses to boot without when
`APP_ENV=production`.

## Roadmap

Milestones from [`docs/PRD.md`](docs/PRD.md) §6, built in order:

- [x] **M0** — Auth & accounts: admin-provisioned users, login, forced first-login password change, rate limiting
- [x] **M1** — Project ingestion: clone + index, status tracking, re-index, Kafka job queue
- [x] **M2** — Dev Knowledge: streaming RAG Q&A against a ready project, private conversations
- [x] **M0–M2 frontend** — auth screens, app shell, projects, streamed answers, admin user management
- [x] **M3** — LangGraph: intent routing + a self-critique loop that grades retrieval before generating
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
[`docs/deployment.md`](docs/deployment.md) covers what a real deployment needs.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md). Bug reports and feature requests go through the
[issue templates](.github/ISSUE_TEMPLATE).

## Documentation

- [`docs/PRD.md`](docs/PRD.md) — product requirements, schemas, milestones, security model
- [`docs/installation.md`](docs/installation.md) — step-by-step local setup, all three paths, and troubleshooting
- [`docs/deployment.md`](docs/deployment.md) — running it for a team: production images, TLS, secrets, backups
- [`docs/configuration.md`](docs/configuration.md) — every setting, what it does, and what to change before production
- [`docs/design.md`](docs/design.md) — design tokens, typography, layout geometry, component inventory
- [`backend/README.md`](backend/README.md) — API setup, routes, configuration
- [`frontend/README.md`](frontend/README.md) — UI setup and scripts
- [`CLAUDE.md`](CLAUDE.md) — architecture notes and the conventions that bite, for AI agents and humans alike
- [`.claude/rules/`](.claude/rules) — twelve enforceable conventions (Python, persistence, API contract, ingestion, RAG, design system, forms, navigation)
