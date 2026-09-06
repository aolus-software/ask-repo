# Installation

Getting AskRepo running on your machine, step by step. For production, read
[`deployment.md`](deployment.md) instead — **nothing on this page is safe to expose**, and the
last section explains why.

Three ways to run it. Pick one:

| Path | You get | Choose it when |
| --- | --- | --- |
| [Everything in Docker](#path-1-everything-in-docker) | The whole stack, one command | You want to try AskRepo, not develop it |
| [Datastores in Docker, apps on your machine](#path-2-datastores-in-docker-apps-on-your-machine) | Hot reload on both apps | You are writing code — this is the normal loop |
| [Without `make`](#path-3-without-make) | The same, spelled out | `make` is unavailable, or you want to see what it runs |

---

## Prerequisites

| Path 1 | Paths 2 and 3 |
| --- | --- |
| Docker with Compose v2 | Docker with Compose v2, plus uv and Bun |

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # backend — fetches Python 3.13 for you
curl -fsSL https://bun.sh/install | bash          # frontend
```

Versions are pinned where it matters: Python **≥ 3.13**, Bun **1.3.14**, Next 16, React 19.
`uv` installs the right Python itself, so you do not need one on the system. No Node version
is required — Bun runs the frontend.

**Ollama runs on the host, not in Docker.** Install it from [ollama.com](https://ollama.com)
and leave `ollama serve` running (the menu-bar app does this for you). It is deliberately out
of the Compose stack: a container gets no GPU on macOS and only the Docker VM's memory
allowance, so a model inside one runs on CPU inside a slice of RAM, while the host process
gets Metal and the whole machine. A Linux box with the NVIDIA runtime can put it back —
[configuration.md](configuration.md#running-ollama-in-docker-anyway).

**Disk and memory.** The Ollama models are the bulk of it: `nomic-embed-text` is ~270 MB and
`qwen2.5-coder:14b` is ~9 GB resident while answering. On a 16 GB machine, use
`qwen2.5-coder:7b` (~4.7 GB) instead — see
[configuration.md](configuration.md#ollama-runs-on-the-host-not-in-docker).

---

## Path 1: everything in Docker

```bash
git clone <this-repo> && cd ask-repo
launchctl setenv OLLAMA_HOST '0.0.0.0:11434'   # macOS: then restart Ollama.app
BOOTSTRAP_ADMIN_PASSWORD='<a real passphrase>' make up
```

That is the whole install. `make up` builds both images and starts eight containers: Postgres,
Qdrant, Redis, Kafka, the API, two ingestion workers, and the frontend. It runs in the
**foreground** — `Ctrl-C` stops it, and `make down` cleans up if you detach.

**Ollama is the ninth piece and it is not a container.** The API and workers reach it at
`host.docker.internal:11434`, which is the address Docker gives a container for the machine
outside. That only works if Ollama is listening on all interfaces rather than loopback, which
is what the `launchctl setenv` line above does — skip it and every embed fails with a
connection refused.

**`BOOTSTRAP_ADMIN_PASSWORD` must be set on that first run.** It is the one variable with no
default anywhere, deliberately: a password committed to this repository would be a password
every reader of it already knows. The backend container refuses to start without it, so a
missing value fails loudly instead of quietly creating a guessable admin.

Set it once in `infra/.env` if you would rather not repeat it:

```bash
cp infra/.env.example infra/.env    # then fill in BOOTSTRAP_ADMIN_PASSWORD
```

### What happens on first boot

Worth knowing, because the first run is slower than every run after it:

1. Postgres, Qdrant, Redis and Kafka start, and the API waits for all four to report
   **healthy** — not merely started.
2. The API container runs `alembic upgrade head`, then `python -m app.cli seed-admins`, then
   starts. **Migrations and admin seeding are part of the container's start command**, so
   there is no separate migrate step on this path.
3. The API creates the Kafka topics on startup (`ensure_topics`), including the 2-partition
   ingest topic. Kafka's own auto-create is off.
4. The two workers probe the embedding model for its vector width — a **live call to Ollama**.
   This is where a worker dies if Ollama is not reachable.
5. The API and each worker also probe the configured **chat** model for structured-output
   support — one live call, against whatever `CHAT_PROVIDER`/`CHAT_BASE_URL`/`CHAT_MODEL`
   names. An instance whose chat model cannot do tool-calling or JSON mode, or whose endpoint
   is unreachable, fails to boot here rather than on the first generation.

**No model is pre-pulled.** The first question you ask blocks on a multi-gigabyte download.
Pull them ahead of time, on the host:

```bash
ollama pull nomic-embed-text
ollama pull qwen2.5-coder:14b
```

Or `make pull-models`, which reads `backend/.env` and pulls whatever this checkout is
configured for rather than the defaults.

Then continue at [First login](#first-login).

---

## Path 2: datastores in Docker, apps on your machine

The normal development loop — containers hold the data, both apps run natively with hot
reload.

```bash
ollama serve       # on the host, if it is not already running
make setup         # uv sync + bun install
make pull-models   # nomic-embed-text + qwen2.5-coder:14b into the host Ollama
make infra         # postgres, qdrant, redis, kafka — waits until each is healthy
make migrate       # apply database migrations
BOOTSTRAP_ADMIN_PASSWORD='<a real passphrase>' make seed
make dev           # both dev servers + the worker; Ctrl-C stops all
```

On this path the apps run natively, so they reach Ollama at plain `localhost:11434` — no
`OLLAMA_HOST` change and no `host.docker.internal`. `make infra`, `make dev` and `make worker`
each check that something answers there and print a warning if not; it is a warning rather
than a failure, because an instance pointed at a hosted embedding or chat provider has no
Ollama by design.

Two differences from Path 1 that catch people out:

- **`make migrate` and `make seed` are yours to run.** Only the *container* start command runs
  them. Running the apps on the host skips that entirely, so a fresh database has no tables
  and no accounts until you run these two.
- **`make dev` starts the worker for you**, alongside the API and the frontend, because
  without it a project sits at `pending` forever and a generated checklist never arrives.
  To run one on its own — a second worker, or a restart without bouncing the servers:

  ```bash
  make worker
  ```

  That is the same codebase with a different entrypoint, reading the same `Settings` and the
  same `.env`. One process runs the ingest consumer, one consumer per retry rung, and a sweep
  every 60 seconds that re-enqueues jobs whose worker died and prunes expired refresh tokens.
  Run at most two — beyond the ingest topic's 2 partitions, extra workers own nothing and sit
  idle.

Configuration is optional on this path; every value has a default. To customize:

```bash
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env.local
```

What each setting does is in [`configuration.md`](configuration.md).

---

## Path 3: without `make`

`make` is a convenience wrapper — nothing depends on it.

**Datastores**

```bash
docker compose -f infra/docker-compose.yml up -d --wait postgres qdrant redis kafka
docker compose -f infra/docker-compose.yml ps            # check health
```

Ollama is not in that list and is not started by Compose. Run it yourself
(`ollama serve`) and pull `nomic-embed-text` and `qwen2.5-coder:14b`.

**Backend** (from `backend/`)

```bash
uv sync                                          # creates .venv, installs deps
uv run alembic upgrade head
BOOTSTRAP_ADMIN_PASSWORD='<a real passphrase>' \
  uv run python -m app.cli seed-admins
uv run uvicorn app.main:app --reload --port 8000
uv run python -m app.worker                      # separate terminal
```

**Frontend** (from `frontend/`)

```bash
bun install
bun dev
```

**Whole stack**

```bash
docker compose -f infra/docker-compose.yml up --build
```

**Bind Ollama to all interfaces first**, and it is the single most common way a manual start
fails. `EMBEDDING_BASE_URL` defaults to `http://host.docker.internal:11434`; if Ollama is
listening on loopback only, both workers restart-loop on a connection refused while probing
embedding dimensions. On macOS that is
`launchctl setenv OLLAMA_HOST "0.0.0.0:11434"` followed by a restart of Ollama.app; elsewhere
it is `OLLAMA_HOST=0.0.0.0:11434 ollama serve`.

To run Ollama in a container instead, add `--profile ollama` **and** set both
`EMBEDDING_BASE_URL` and `CHAT_BASE_URL` to `http://ollama:11434` in `infra/.env` — the
profile alone starts a service nothing is pointed at.

---

## First login

Check the API is alive, then sign in:

```bash
curl -s localhost:8000/ | jq
curl -s localhost:8000/health | jq
```

Open <http://localhost:3000> and log in as `superuser@example.com` or `admin@example.com`
with the `BOOTSTRAP_ADMIN_PASSWORD` you set. Both accounts are created with
`must_change_password`, so the first login forces a change before anything else works.

The same thing over the API, if you prefer:

```bash
curl -s -X POST localhost:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email":"admin@example.com","password":"<a real passphrase>"}' | jq
```

The response carries an `accessToken` and a user object with `mustChangePassword: true`. Until
`POST /auth/change-password` clears that flag, every route outside `/auth` returns
`403 PASSWORD_CHANGE_REQUIRED` — the gate is middleware, not a per-route check.

### Index your first repository

Add a project from the UI, or:

```bash
curl -s -X POST localhost:8000/projects \
  -H "Authorization: Bearer <accessToken>" \
  -H 'Content-Type: application/json' \
  -d '{"name":"example","repoUrl":"https://github.com/<owner>/<repo>.git"}' | jq
```

It returns immediately with status `pending` — cloning and indexing happen in the background,
on a worker. Poll `GET /projects/{id}` until it reads `ready`, then ask it a question. If it
never leaves `pending`, **no worker is running** (see Path 2 above).

Only `github.com` and `gitlab.com` are accepted by default. `REPO_HOST_ALLOWLIST` is a
security control, not a convenience setting — the URL is fetched from inside your network, so
widen it deliberately.

---

## Service URLs

| Service | URL |
| --- | --- |
| Frontend | <http://localhost:3000> |
| API | <http://localhost:8000> ([docs](http://localhost:8000/docs)) |
| Qdrant dashboard | <http://localhost:6333/dashboard> |
| Postgres | `localhost:5432` |
| Redis | `localhost:6379` |
| Kafka | `localhost:9092` |
| Ollama | `localhost:11434` — a host process, not a container |

The **ingestion worker publishes no port** — it is reached through Kafka, not HTTP. `make up`
runs two replicas, one per ingest partition.

---

## Everyday commands

`make help` lists all of them. The ones you will actually use:

| Command | Does |
| --- | --- |
| `make dev` | Both dev servers **and the worker** |
| `make dev-backend` / `make dev-frontend` | One of them |
| `make worker` | The ingestion + checklist worker on its own |
| `make check` | lint + format-check + typecheck + test — what CI would run |
| `make test` | Backend suite |
| `make test-one T=tests/test_api_model.py` | One file, or `T=-k\ camel_case` |
| `make test-integration` | The suite that needs a real Kafka broker |
| `make migrate` / `make seed` | Migrations, bootstrap admins |
| `make psql` / `make redis-cli` | Shell into a running datastore |
| `make up` / `make down` | Whole stack in Docker |
| `make infra` / `make infra-stop` / `make infra-down` | Datastores only; none of them delete data |
| `make clean` | Caches and build output |

**`make infra` must be running before `make test`.** The backend suite runs against real
Postgres and real Redis — never SQLite, never a mock.

### Stopping and resetting

| Command | Keeps your data? |
| --- | --- |
| `make down` | **Yes** — stops containers, volumes survive |
| `make infra-stop` | **Yes** — stops datastores, containers stay |
| `make infra-down` | **Yes** — stops and removes the containers, volumes survive |
| `make infra-reset` | **No.** Runs `docker compose down -v`, after asking you to confirm |

`make infra-reset` deletes **every** volume in the project — Postgres, Qdrant, Redis and
Kafka. Coming back from it costs `make migrate && make seed` plus a re-index of every project.
Your Ollama models survive: they live in the host's `~/.ollama`, not in a Compose volume. It
prompts for the word `delete` before doing anything, and a non-interactive invocation aborts
instead of proceeding.

Nothing named `down` deletes data: `make down`, `make infra-down` and `make down-prod` all keep
their volumes, and the destructive path has its own name so it cannot be a typo.

---

## When it does not work

**A project stays at `pending` forever.**
Nothing is consuming the queue. On Path 2, check that `make dev` printed the worker line and
did not die on startup; `make worker` runs one on its own. On Path 1, check
`docker compose logs worker`;
the usual cause is the next entry.

**The worker restart-loops at startup.**
It probes the embedding model for its vector width before doing anything else, and that is a
live network call. Either Ollama is not running on the host, or `EMBEDDING_BASE_URL` points
somewhere unreachable. Inside a container, `localhost` is *that container* — the model server
is at `http://host.docker.internal:11434`, and reaching it needs Ollama bound to `0.0.0.0`
rather than loopback. On Path 2 the apps run natively, so plain `http://localhost:11434` is
correct and no binding change is needed.

**Every question returns `409 EMBEDDING_MODEL_CHANGED`.**
The project was indexed with a different embedding model from the one now configured. The
Qdrant collection is named for provider + model + width, so the API would otherwise be
searching a collection the worker never wrote to. Either put `EMBEDDING_MODEL` back, or
reindex the project.

**`make test` fails to connect.**
`make infra` first. The suite needs real Postgres and Redis.

**The first question takes minutes.**
No model was pre-pulled; it is downloading. `make pull-models` does it up front, and
`ollama ps` on the host shows what is loaded.

**Port already in use.**
Every published port is overridable in `infra/.env` — `FRONTEND_PORT`, `BACKEND_PORT`,
`POSTGRES_PORT`, `REDIS_PORT`, `QDRANT_HTTP_PORT`, `QDRANT_GRPC_PORT`, `KAFKA_PORT`. See
[`infra/.env.example`](../infra/.env.example). `OLLAMA_PORT` is listed there too but is only
read when the containerised `ollama` profile is on; a host Ollama on a non-default port is
told to `EMBEDDING_BASE_URL` and `CHAT_BASE_URL` directly.

**`seed-admins` refuses to run.**
`BOOTSTRAP_ADMIN_PASSWORD` is unset, or fails the password policy (12 characters minimum, not
in the common-password blocklist). It refuses rather than inventing one. If the accounts
already exist it exits successfully without looking at the password at all — the command is
idempotent by design, because it runs on every container start.

**Answers are slow, or the machine swaps.**
Check that you are on the host Ollama and not a container you re-enabled: in Docker on macOS
it never gets the Apple GPU, so everything is CPU-only. Failing that, `CHAT_MODEL` is too big
for the machine — `qwen2.5-coder:7b` is ~4.7 GB against the 14b's ~9.5 GB resident, and it can
be swapped freely because nothing is indexed with it.
[configuration.md](configuration.md#ollama-runs-on-the-host-not-in-docker).

---

## This is a development stack

Everything on this page runs the development configuration, and it is not one bad setting away
from being production — it is a different build:

- The API runs `uvicorn --reload` and the frontend runs `next dev`. **No image in this repo
  runs `next build`.**
- Your working copy is bind-mounted over `/app` in the backend, worker, and frontend
  containers, so the running code is the checkout on disk, not the image.
- `APP_ENV` defaults to `development`, which means the startup checks that reject placeholder
  secrets never fire. The stack boots happily with `SECRET_KEY=dev-insecure-change-me`.
- Every datastore port is published to the host, and Redis, Kafka and Ollama have **no
  authentication at all**.
- There is no TLS, and the refresh cookie is `Secure` — so the app is functionally broken on
  any non-`localhost` hostname served over plain HTTP.

None of that is one setting away from being fixed — production is a different build, and it
ships separately: `infra/backend.prod.Dockerfile`, `infra/frontend.prod.Dockerfile`,
`infra/docker-compose.prod.yml`, and a `-prod` Make target for every step.
[`deployment.md`](deployment.md) is the procedure.

---

## See also

- [`README.md`](README.md) — **the documentation index**
- [`architecture.md`](architecture.md) — how the system fits together
- [`configuration.md`](configuration.md) — every setting and what it does
- [`deployment.md`](deployment.md) — running it for real
- [`../backend/README.md`](../backend/README.md) — routes, layout, the worker
- [`../frontend/README.md`](../frontend/README.md) — scripts and app layout
- [`../CONTRIBUTING.md`](../CONTRIBUTING.md) — workflow, checks, conventions
