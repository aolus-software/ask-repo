<p align="center">
  <img src="assets/logo.png" alt="AskRepo" width="120" height="120" />
</p>

<h1 align="center">AskRepo</h1>

<p align="center">Ask questions about a codebase and get grounded, cited answers.</p>

AskRepo clones a repository, indexes it into a vector store, and answers natural-language
questions about it — citing the actual files and functions the answer came from. It is
**self-hosted and single-tenant**: an organization runs its own instance on its own
infrastructure, provisions accounts for its developers, and keeps it on the internal
network.

Built as a learning project for RAG, LangChain/LangGraph, prompt engineering, and context
management — against real repositories rather than tutorial data.

AskRepo is admin-provisioned: an administrator creates accounts, and a new user is forced to
change their initial password on first login. Submit a repository URL and it is cloned, walked,
chunked, embedded into Qdrant and tracked as a project — driven by a Kafka job queue and a
separate worker process, so the request returns immediately. Ask a question about an indexed
project and the answer streams back token by token over Server-Sent Events, cited to real files
and line ranges, with conversations private to whoever had them. Questions are routed (codebase
question / conversational / out of scope) before anything is retrieved, and on the codebase path
a grader checks the retrieved excerpts and re-searches with a better query when they fall short
— it grades retrieval rather than the finished answer, so streaming is unaffected.

Point it at a module and it generates test cases with expected results grounded in the code.
Nothing enters the checklist unreviewed: a shared conversation proposes further changes, a human
accepts the ones they want, and testers record pass/fail/blocked results, all exported to
`.xlsx`. For the same module it will propose a grounded sample dataset from that feature's actual
schema, refined the same way — chat, a pending change set, then apply — and exported as JSON or
`.xlsx`.

All of it works in a browser, with the session held in httpOnly cookies by Next rather than in
the page.

> **For what is built and what is not, read [`docs/PRD.md`](docs/PRD.md) §6.** It is the only
> place this repository records milestone progress; no other document tracks it, so nothing else
> can go stale about it.

## Features

Numbered as in [`docs/PRD.md`](docs/PRD.md) §4, which is also where their status lives.

| | Feature | What it does |
| --- | --- | --- |
| **0** | Auth & Accounts | Admin-provisioned email/password accounts, JWT access + revocable refresh tokens |
| **1** | Project ingestion | Submit a repo URL; AskRepo clones, indexes, and tracks it. Projects are shared instance-wide |
| **2** | Dev Knowledge | Ask questions against an indexed project; answers cite real file paths and functions. Conversations stay private to each user |
| **3** | QA Checklist | Generate test cases for a code module, review and refine them via chat, record pass/fail/blocked results, and export as a spreadsheet |
| **4** | Mock Data Generator | Generate sample data records for a QA Checklist module, grounded in that feature's actual schema, reviewed via chat and exported as JSON/xlsx |

## How it works

Four steps, and the third is the one people usually want explained.

**1 — Index.** `POST /projects` writes a row, publishes a Kafka job and returns. A separate
worker clones the repo, walks it, splits each file into overlapping chunks on language
boundaries, embeds them, and writes them to Qdrant. The working copy is then deleted, which is
why the chunk's text rides along in the vector payload:

```python
{"project_id": "…", "generation": 3, "file_path": "app/auth/login.py",
 "start_line": 1, "end_line": 40, "symbol": "login", "content": "def login(user): …"}
```

**2 — Retrieve.** A question is embedded with the same model, then searched — filtered to that
project *and* the generation it is currently serving, cut at a relevance floor, and merged back
into contiguous spans:

```python
vector = await self.embedder.embed_query(query)
hits   = await self.store.search(project_id=..., generation=..., vector=vector, limit=top_k)
kept   = [chunk_from_hit(h) for h in hits if h.score >= self.min_score]
return apply_budget(merge_adjacent(kept), max_chars=self.max_chars)
```

If nothing clears the floor, **the model is never called** — a refusal is streamed instead.

**3 — Answer.** Not one model call, a small state machine. LangGraph routes the question,
retrieves, grades whether the excerpts actually answer it, searches again with a better query if
not, then generates:

```mermaid
flowchart LR
    C[classify] -->|codebase| R[retrieve] --> G[grade]
    G -->|insufficient| R
    G -->|sufficient| GEN[generate] --> E([stream])
    C -->|conversational| H[answer from history] --> E
    C -->|out of scope| F[refuse] --> E
```

It grades **retrieval, not the finished answer** — a critic that can reject a finished answer can
only run on one that finished, which would mean buffering the whole draft or retracting a
streamed one. Tokens go to the browser over SSE as they arrive, citations first.

**4 — Ground.** The finished answer is checked against what was actually retrieved: a file it
named that no excerpt contained, or an answer that cited nothing, is reported to the user. That
does not make the model honest — it makes dishonesty visible.

The same graph, with one extra node, powers the QA Checklist and Mock Data refinement chats.

**→ [`docs/`](docs/README.md) explains all of it properly**, starting with
[`docs/architecture.md`](docs/architecture.md).

## Stack

**Backend** FastAPI · Python 3.13 · uv · SQLAlchemy + Alembic · LangGraph · LangChain
**Frontend** Next.js 16 · React 19 · TypeScript · Tailwind CSS 4 · Bun
**Data** Postgres 17 · Qdrant · Redis · Kafka
**Models** Ollama (qwen2.5-coder, qwen3), run on the host rather than in Compose, or any
OpenAI-compatible endpoint, or Anthropic — the answering model is a setting, not a rebuild
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
├── assets/             Brand source files — logo.png and the favicon set
├── .claude/            Rules, commands and skills for AI agents
└── Makefile            Task runner — `make help`
```

## Quick start

The short version is below; [`docs/installation.md`](docs/installation.md) is the same thing
step by step, with a troubleshooting section.

**Requirements:** Docker with Compose v2, [Ollama](https://ollama.com) installed **on the
host**, plus [uv](https://docs.astral.sh/uv/) and [Bun](https://bun.sh) if you want to run the
apps outside containers.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # backend
curl -fsSL https://bun.sh/install | bash          # frontend
```

Ollama is deliberately **not** in the Compose stack. A container gets no GPU on macOS and only
the Docker VM's memory allowance, so a model inside one runs on CPU in a slice of RAM; run by
the host it gets Metal and the whole machine. Start it once and pull the models:

```bash
ollama serve        # or the menu-bar app
make pull-models    # nomic-embed-text + qwen2.5-coder:14b, ~10 GB
```

A Linux box with the NVIDIA runtime can put it back in Docker —
[`docs/configuration.md`](docs/configuration.md#running-ollama-in-docker-anyway).

### Everything in Docker

The apps and datastores; Ollama still on the host, reached at `host.docker.internal:11434`:

```bash
git clone <this-repo> && cd ask-repo
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"      # macOS: let containers reach it
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
make dev                                           # both dev servers + the worker, Ctrl-C stops all
```

`make infra` and `make dev` both check that the host Ollama is answering on `:11434` and print
a warning if it is not — the worker otherwise dies probing embedding dimensions, in a log
stream interleaved with two others. It is a warning, never a failure, because an instance on a
hosted embedding or chat provider correctly has no Ollama.

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:3000> |
| API | <http://localhost:8000> ([docs](http://localhost:8000/docs)) |
| Qdrant dashboard | <http://localhost:6333/dashboard> |
| Postgres | `localhost:5432` |
| Redis | `localhost:6379` |
| Kafka | `localhost:9092` |
| Ollama | `localhost:11434` (embeddings + answers) — **runs on the host, not in Compose** |

The **worker** publishes no port — it is reached through Kafka, not HTTP. It consumes both
ingestion and checklist-generation jobs, so nothing indexes and no checklist is generated
without one. `make up` runs two replicas, one per ingest partition; `make dev` runs a single
one alongside the dev servers, and `make worker` runs one on its own. See
[`backend/README.md`](backend/README.md#the-ingestion-worker).

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
| `make infra` | Start postgres + qdrant + redis + kafka, wait until healthy |
| `make pull-models` | Pull the configured embedding + chat models into the host Ollama |
| `make migrate` | Apply database migrations |
| `make seed` | Create the bootstrap admin accounts (idempotent) |
| `make dev` | Both dev servers and the worker together |
| `make dev-backend` / `make dev-frontend` | One dev server |
| `make worker` | The ingestion + checklist worker on its own |
| `make check` | lint + format-check + typecheck + test — what CI runs |
| `make lint` / `make format` | Both apps |
| `make test` | Backend test suite |
| `make test-one T=tests/test_api_model.py` | One test file, or `T=-k\ camel_case` |
| `make build` | Production frontend build |
| `make up` / `make down` | Whole stack in Docker (development) |
| `make setup-prod` | Check a box is ready to deploy; changes nothing |
| `make build-prod` / `make up-prod` | Production images and stack — see [`docs/deployment.md`](docs/deployment.md) |
| `make infra-down` | Stop and remove the datastore containers; data survives |
| `make infra-reset` | **Deletes every volume in the project.** Asks for confirmation first |
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
uv run uvicorn app.main:app --reload --port 8000 --log-config logging.json
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

**Whole stack in Docker** — apps and datastores in containers, Ollama still on the host at
`host.docker.internal:11434`. Bind it with `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"`
first, or a container cannot reach it.

```bash
docker compose -f infra/docker-compose.yml up --build
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

Not tracked here. [`docs/PRD.md`](docs/PRD.md) §6 lists the milestones and which are built;
§2.1 covers what is deliberately deferred and what each deferred item would cost.

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

- [**`docs/README.md`**](docs/README.md) — **the documentation index; start here**
- [`CHANGELOG.md`](CHANGELOG.md) — what changed in each release
- [`docs/PRD.md`](docs/PRD.md) — product requirements, schemas, security model, and **the only record of milestone progress**
- [`docs/architecture.md`](docs/architecture.md) — the processes, the datastores, and three request lifecycles
- [`docs/codebase.md`](docs/codebase.md) — the layering, the source tree, and where to add code
- [`docs/rag.md`](docs/rag.md) — clone → chunk → embed → retrieve → cite, end to end
- [`docs/llm.md`](docs/llm.md) — providers, structured output, retries, and cost bounds
- [`docs/langgraph.md`](docs/langgraph.md) — the answer graph and the streaming contract
- [`docs/data.md`](docs/data.md) — the 13 tables, leases, soft delete, and what each store holds
- [`docs/installation.md`](docs/installation.md) — step-by-step local setup, all three paths, and troubleshooting
- [`docs/deployment.md`](docs/deployment.md) — running it for a team: production images, TLS, secrets, backups
- [`docs/configuration.md`](docs/configuration.md) — every setting, what it does, and what to change before production
- [`docs/design.md`](docs/design.md) — design tokens, typography, layout geometry, component inventory
- [`backend/README.md`](backend/README.md) — API setup, routes, configuration
- [`frontend/README.md`](frontend/README.md) — UI setup and scripts
- [`CLAUDE.md`](CLAUDE.md) — architecture notes and the conventions that bite, for AI agents and humans alike
- [`.claude/rules/`](.claude/rules) — twelve enforceable conventions (Python, persistence, API contract, ingestion, RAG, design system, forms, navigation)
