# Configuration

Every setting AskRepo reads, what it does, and which ones you must change before anyone
else uses the instance.

The `.env.example` files are the **canonical list of variable names** — grouped, defaulted,
and deliberately free of prose. This document is where the prose lives: why a value is what
it is, and what breaks when it is wrong.

| File | Copy to | Read by |
| --- | --- | --- |
| [`backend/.env.example`](../backend/.env.example) | `backend/.env` | the API and the ingestion worker |
| [`frontend/.env.example`](../frontend/.env.example) | `frontend/.env.local` | Next, on the server only |
| [`infra/.env.example`](../infra/.env.example) | `infra/.env` | Docker Compose, for the whole stack ([reference](#docker-compose-infraenv)) |

---

## How settings are loaded

**Backend.** `app/config.py` defines `Settings` (pydantic-settings). Precedence is
**environment → `.env` → the defaults in the class**, so a `.env` file is optional: every
value has a default and the API boots with no file at all. `get_settings()` is `lru_cache`d
and injected with `Depends`; nothing else in the codebase reads `os.environ`.

Two consequences worth knowing:

- **Complex types are parsed as JSON.** `CORS_ORIGINS`, `REPO_HOST_ALLOWLIST`, and
  `BOOTSTRAP_ADMIN_EMAILS` must be JSON arrays — `["http://localhost:3000"]`, not a
  comma-separated string. A comma-separated value fails at startup, not at first use.
- **Bounds are validated at startup.** Several numeric settings carry a `ge=` guard because
  a zero would not fail, it would silently do nothing useful — see
  [Values that fail silently](#values-that-fail-silently).

**Frontend.** Next reads `API_URL` from the process environment (`.env.local` in
development). It is **not** `NEXT_PUBLIC_`-prefixed and must not become one — see
[Frontend](#frontend).

**Compose.** `infra/docker-compose.yml` gives every value a `${VAR:-default}` fallback, so
`make up` works with no `infra/.env`. The backend and worker share one `x-app-env` anchor
because they run the same image and must agree on every datastore and secret.

---

## Before production

`APP_ENV=production` turns four of these from advice into a startup check — the app raises
rather than serving traffic with a known key:

| Setting | Requirement | Why |
| --- | --- | --- |
| `SECRET_KEY` | not `dev-insecure-change-me` | Signs access tokens. A published key is a forgeable session for any account. Generate: `openssl rand -hex 32` |
| `PAT_ENCRYPTION_KEY` | not `dev-insecure-change-me` | Encrypts stored repository tokens at rest. PATs encrypted with a known key are not encrypted. Generate: `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |
| `REFRESH_COOKIE_SECURE` | `true` | A refresh cookie sent over plain HTTP is a session anyone on the path can take |
| `TRUSTED_PROXY_HOPS` | the number of proxies in front of the API | Left at `0` behind Caddy, every request appears to come from Caddy and the per-IP login limit becomes one instance-wide limit |

Two more that nothing enforces but you still want:

- **`PAT_ENCRYPTION_KEY` must be backed up separately from the database.** A backup holding
  both the ciphertext and the key is plaintext storage with extra steps. Losing the key means
  every stored PAT must be re-entered.
- **`BOOTSTRAP_ADMIN_PASSWORD` has no default on purpose.** Seeding refuses to run without
  it rather than inventing one, and Compose passes it through with no fallback for the same
  reason: a committed placeholder would be a valid, publicly-known password.

---

## Backend

### Application

| Variable | Default | What it does |
| --- | --- | --- |
| `APP_NAME` | `AskRepo API` | Title shown in the OpenAPI docs |
| `APP_VERSION` | `0.1.0` | Reported by `/` and `/health` |
| `APP_ENV` | `development` | `development` or `production`. `production` enables the startup checks above |
| `DEBUG` | `true` | Verbose errors and reload-friendly behaviour |

### Server

| Variable | Default | What it does |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Bind address |
| `PORT` | `8000` | Bind port |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | **JSON array.** Browser origins allowed to call the API |

`CORSMiddleware` is registered *outside* `AuthContextMiddleware` on purpose, so the
forced-password-change gate's `403` still carries CORS headers and the browser can read it.

### Datastores

All four are live. Inside Compose the hosts are service names (`postgres`, `qdrant`,
`redis`, `kafka`); running the API on your machine against `make infra`, they are
`localhost`.

| Variable | Default | What it does |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+asyncpg://askrepo:askrepo@localhost:5432/askrepo` | Users, refresh tokens, projects, conversations. The `+asyncpg` driver is required |
| `QDRANT_URL` | `http://localhost:6333` | Vector store for indexed code chunks. Written by the worker, searched and hard-deleted by the API |
| `REDIS_URL` | `redis://localhost:6379/0` | Login rate limiting, and nothing else |

**Redis does not back the job queue.** That is Kafka — see [Kafka](#kafka-the-ingestion-job-queue).
Redis is read by `app/core/rate_limit.py` alone.

### Secrets

| Variable | Default | What it does |
| --- | --- | --- |
| `SECRET_KEY` | `dev-insecure-change-me` | HMAC key for access-token JWTs |
| `PAT_ENCRYPTION_KEY` | `dev-insecure-change-me` | Fernet key encrypting stored personal access tokens |

Both must be **identical in the API and the worker**: the API encrypts a PAT when a project
is created and the worker decrypts it to clone. A mismatch surfaces as a clone that fails
with a decryption error, not as a warning at startup. Compose shares them through one anchor
so they cannot drift.

### Auth

| Variable | Default | What it does |
| --- | --- | --- |
| `ACCESS_TOKEN_TTL_MINUTES` | `15` | Lifetime of the stateless JWT |
| `REFRESH_TOKEN_TTL_DAYS` | `30` | Lifetime of the opaque refresh token, stored hashed so it can be revoked |
| `REFRESH_COOKIE_NAME` | `askrepo_refresh` | Cookie the backend sets. Operator-configurable, which is why the frontend stores it verbatim as a `name=value` pair |
| `REFRESH_COOKIE_PATH` | `/auth` | The backend only ever needs the cookie on its auth routes |
| `REFRESH_COOKIE_SECURE` | `true` | On even in development: browsers treat `http://localhost` as a secure context, so the cookie is still set and dev matches production |
| `REFRESH_COOKIE_SAMESITE` | `lax` | `lax` covers same-site deployments, `localhost:3000 → localhost:8000` included. A genuinely cross-site deployment needs `none`, which requires `Secure=true` |
| `REFRESH_ROTATION_GRACE_SECONDS` | `10` | Window in which a just-rotated token is not treated as a replay, so two browser tabs refreshing at once do not log the user out |

Refresh tokens rotate on use. Without the grace window, the second tab presents the token the
first one just consumed, that looks exactly like a stolen-token replay, and the correct
response to a replay is to revoke the family — logging out a user who did nothing wrong.

### Passwords

| Variable | Default | What it does |
| --- | --- | --- |
| `PASSWORD_MIN_LENGTH` | `12` | Minimum length |
| `PASSWORD_MAX_BYTES` | `72` | **Do not raise.** bcrypt ignores input past 72 bytes, so a higher cap lets two different long passwords authenticate against the same hash |
| `BCRYPT_COST` | `12` | Work factor. Higher is slower to verify, for you and for an attacker |
| `COMMON_PASSWORD_LIST_PATH` | vendored | Blocklist checked at password set. Defaults to `app/core/data/common-passwords.txt` inside the package; rarely overridden |

### Bootstrap admins

| Variable | Default | What it does |
| --- | --- | --- |
| `BOOTSTRAP_ADMIN_EMAILS` | `["superuser@example.com","admin@example.com"]` | **JSON array.** Accounts created by `make seed` / the container entrypoint |
| `BOOTSTRAP_ADMIN_PASSWORD` | *none* | Initial password for all of them. Seeding refuses to run without it |

Both accounts are created with `must_change_password` set, so the shared initial password
stops working the moment each admin logs in. Seeding is idempotent: an already-seeded
instance boots regardless of whether the variable is still present.

There is no public registration, no email verification, and no self-service reset — which is
why there is no mail provider anywhere in the stack. Admins create every other account.

### Login rate limiting

| Variable | Default | What it does |
| --- | --- | --- |
| `LOGIN_RATE_PER_MINUTE_IP` | `5` | Login attempts per minute from one address |
| `LOGIN_RATE_PER_HOUR_EMAIL` | `10` | Login attempts per hour against one account |
| `TRUSTED_PROXY_HOPS` | `0` | Number of trusted reverse proxies in front of the API |

`TRUSTED_PROXY_HOPS=0` means ignore `X-Forwarded-For` entirely and trust the socket address —
correct when nothing sits in front of the API, and wrong the moment something does. Behind one
Caddy, set `1`.

### Kafka — the ingestion job queue

| Variable | Default | What it does |
| --- | --- | --- |
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Read by **both** processes: `ensure_topics` and the producer from the API lifespan, the consumers from `app/worker.py` |
| `KAFKA_INGEST_TOPIC` | `askrepo.ingest.requested` | Topic new index jobs are published to |
| `KAFKA_CONSUMER_GROUP` | `askrepo-ingest` | Consumer group the workers join |
| `KAFKA_INGEST_PARTITIONS` | `2` | **This is the ingestion concurrency cap** — how many repositories can index at once |
| `KAFKA_MAX_ATTEMPTS` | `3` | Attempts before a job lands in `askrepo.ingest.dlq` |

There is no separate "max concurrent ingestions" setting: concurrency *is* partition count,
so the cap is the topology rather than a number someone can raise by accident. Worker replicas
beyond the partition count sit idle.

**There is deliberately no setting for `max.poll.interval.ms`.** An index can run for twenty
minutes, and aiokafka measures liveness as fetcher idle time — so the consumer pauses its
partitions and keeps polling throughout the job instead. Raising the timeout is not an
acceptable substitute for that.

### Embedding model

| Variable | Default | What it does |
| --- | --- | --- |
| `EMBEDDING_PROVIDER` | `ollama` | `ollama`, `openai`, or `voyage` |
| `EMBEDDING_MODEL` | `nomic-embed-text` | Model that turns code chunks and questions into vectors |
| `EMBEDDING_BASE_URL` | `http://localhost:11434` | Endpoint. Ollama runs on the host, so this is right for `make dev`. Inside Compose it is `http://host.docker.internal:11434` — `localhost` in a container is that container |
| `EMBEDDING_API_KEY` | *empty* | Required for `openai` and `voyage`; ignored by `ollama` |
| `EMBEDDING_BATCH_SIZE` | `64` | Chunks embedded per request. Must be ≥ 1 |

**The API and the worker must agree on all of these.** The worker embeds documents at index
time; the API embeds the question at query time. The Qdrant collection is named
`code_chunks__provider__model__dimensions`, so if the two disagree the API searches a
collection the worker never wrote to.

**The vector width is probed at worker startup, never configured.** That is why a provider or
model change lands in a *different* collection instead of silently mixing incompatible
vectors: existing projects keep serving their old collection and report as needing a reindex.
Never hardcode or guess a collection name.

Swapping one 768-dimensional model for another is the case this protects against hardest —
Qdrant would accept those queries happily and return nearest neighbours in a vector space the
collection was never built in. Answers stay fluent and cited; only the quality drops. The
guard is `409 EMBEDDING_MODEL_CHANGED`, raised by comparing `project.embedding_model` against
the current embedder.

### Ingestion

| Variable | Default | What it does |
| --- | --- | --- |
| `REPO_HOST_ALLOWLIST` | `["github.com","gitlab.com"]` | **JSON array.** Any host not listed is rejected before DNS resolution |
| `CLONE_TIMEOUT_SECONDS` | `120` | Wall-clock budget for a clone. Must be ≥ 1 |
| `REPO_MAX_SIZE_MB` | `500` | Repositories larger than this are refused. Must be ≥ 1 |
| `REPO_SCRATCH_DIR` | `/data/repos` | Where clones land |
| `CHUNK_SIZE` | `1200` | Characters per indexed chunk |
| `CHUNK_OVERLAP` | `150` | Characters shared between adjacent chunks, so a definition split across a boundary is still retrievable |
| `MAX_INDEXED_FILE_BYTES` | `1048576` | Files larger than 1 MiB are skipped. Must be ≥ 1 |

`REPO_HOST_ALLOWLIST` is a **security control, not input hygiene**. Repository URLs are
user-supplied and fetched from *inside* a private network, where `10.0.x.x` and internal
service names resolve — the full control is https-only, host allowlist, and private-address
rejection at connect time.

`REPO_SCRATCH_DIR` is scratch space, **not a volume to preserve**: the working copy is deleted
after indexing, and a reindex re-clones rather than pulling.

### Chat model

Separate from the embedding model on purpose — an instance commonly embeds locally and
answers with a hosted model, or the reverse.

| Variable | Default | What it does |
| --- | --- | --- |
| `CHAT_PROVIDER` | `ollama` | `ollama`, `openai`, or `anthropic` |
| `CHAT_MODEL` | `qwen2.5-coder:14b` | The answering model |
| `CHAT_BASE_URL` | `http://localhost:11434` | Endpoint. Inside Compose, `http://host.docker.internal:11434`. For `anthropic`, `https://api.anthropic.com` — there is no default that guesses it, the same as `openai` |
| `CHAT_API_KEY` | *empty* | Required for `openai` and `anthropic`; ignored by `ollama` |
| `CHAT_TEMPERATURE` | `0.1` | Low but not zero: answers about code should be reproducible, not creative. `0.0`–`2.0` |
| `CHAT_TIMEOUT_SECONDS` | `180` | Whole-answer budget. Expiry ends the turn with `finishReason=timeout` |
| `CHAT_MAX_CONCURRENCY` | `2` | Answers generated at once, instance-wide |

These are read by the **API only** — the worker indexes, it never answers a question.

Raising `CHAT_MAX_CONCURRENCY` against Ollama does not shorten the queue. Ollama serialises
inference internally, so more concurrent answers means every answer is slower, on a box
already running Postgres, Qdrant, Redis and Kafka.

Boot now performs one live structured-output call against the configured chat model, in both
the API and each worker. An instance whose model cannot do tool-calling or JSON mode, or whose
endpoint is unreachable, fails to start here rather than on the first generation.

### Retrieval

| Variable | Default | What it does |
| --- | --- | --- |
| `RAG_TOP_K` | `12` | Qdrant hits fetched *before* adjacent chunks are merged; merging typically collapses 12 hits into 5–8 contiguous spans |
| `RAG_CONTEXT_MAX_CHARS` | `24000` | Character budget for retrieved code in the prompt. Lowest-scoring spans are dropped first, so the cap can never discard the best hit. Must be ≥ 1000 |
| `RAG_HISTORY_TURNS` | `6` | Prior turns replayed into the prompt. `0` disables multi-turn memory |
| `RAG_MIN_SCORE` | `0.25` | Cosine similarity a chunk must reach to be shown to the model at all. `0.0` disables the floor |
| `RAG_MAX_RETRIEVAL_ATTEMPTS` | `2` | How many times retrieval may run for one question — the first attempt plus any the evidence grader asks for. Raise it if answers often miss code you know is indexed; each extra attempt costs one model call before the answer starts. Must be at least 1. |
| `RAG_GRADE_EVIDENCE` | `true` | Whether a model call judges the retrieved excerpts before answering, and re-searches on a better query when they fall short. Turning it off removes one model call per question and makes the answer path identical to M2's. |
| `RAG_CLASSIFY_INTENT` | `true` | Whether a model call routes the question — code question, conversational follow-up, or out of scope — before retrieving. Turning it off sends every question down the retrieval path, including "thanks". |
| `RAG_PROPOSE_CHANGES` | `true` | Whether the QA Checklist's refinement chat runs the extra model call that turns a reply into a proposed change set. Turning it off leaves the chat answering questions about the checklist and proposing nothing — the Ask screen is unaffected either way, because its call site cannot reach this node. |

`RAG_MIN_SCORE` is the setting most worth tuning. Below the floor the embedder is saying
"unrelated", and answering from unrelated code is how a fluent, confident, entirely wrong
answer gets produced. **If nothing clears the floor the model is not called at all** — a fixed
refusal is streamed instead, with `groundingWarnings: ["no_context"]` on the `done` event.
Raise it if answers cite plausible-looking but irrelevant files; lower it if the assistant
refuses questions it should be able to answer.

The floor is applied *before* adjacent chunks are merged, so a strong chunk cannot drag a
below-floor neighbour in behind it.

---

### QA Checklist

`QA_EXPORT_MAX_ROWS` was renamed to `CHECKLIST_EXPORT_MAX_ROWS` when the QA List was replaced
(`docs/PRD.md` §4.3). The old name is not read as a fallback: an instance still setting it will
run on the default and the export cap will silently be whatever the default is, so rename it in
your `.env` rather than assuming it carried over.

| Variable | Default | What it does |
| --- | --- | --- |
| `CHECKLIST_EXPORT_MAX_ROWS` | `5000` | Rows the `.xlsx` export will build before refusing with `409 EXPORT_TOO_LARGE`. `openpyxl` builds the whole workbook in memory even in write-only mode, so this cap is the only thing bounding that allocation. Narrow the filters and try again rather than raising it casually. |
| `KAFKA_CHECKLIST_TOPIC` | `askrepo.checklist.generate` | The topic checklist generation jobs are published to. Its own topic, not the ingest one, and that is the point: a generation retrying for eleven minutes must not sit in the queue a project reindex is waiting in. Its retry rungs are derived from this name, so renaming it strands anything already queued under the old one. |
| `KAFKA_CHECKLIST_PARTITIONS` | `1` | Partitions on that topic, which is the ceiling on how many generations run at once — one consumer may own a partition, so `1` means one generation at a time across the instance. Raise it only alongside worker replicas; more partitions than workers buys nothing. Lowering it later is not possible without deleting the topic. |
| `CHECKLIST_MAP_CONCURRENCY` | `4` | How many files the generator observes concurrently in its map step. Each is one model call, so this multiplies load on a server that may already serialise inference: too high and every generation gets slower rather than the batch finishing sooner. Too low and a large module takes minutes longer than it needs to. |
| `CHECKLIST_SCROLL_PAGE_SIZE` | `256` | Points fetched per Qdrant scroll page while enumerating a module's files. It bounds memory per page, not the total: the generator reads every matching chunk regardless, so this trades round trips against the size of one response. |
| `CHECKLIST_MAX_FILES_PER_JOB` | `200` | Files mapped per generation run before the rest are reported skipped rather than processed. One model call per file, so this bounds the worst-case cost of a single run rather than cumulative spend — a module larger than this needs more than one generation pass to cover in full. |

### QA Mock Data Generator

| Variable | Default | What it does |
| --- | --- | --- |
| `MOCK_DATA_EXPORT_MAX_ROWS` | `5000` | Records the `.xlsx`/`.json` export will build before refusing with `409 EXPORT_TOO_LARGE`. Same reasoning as `CHECKLIST_EXPORT_MAX_ROWS`: `openpyxl` builds the whole workbook in memory. |
| `KAFKA_MOCK_DATA_TOPIC` | `askrepo.mock-data.generate` | The topic mock-data generation jobs are published to. Its own topic and retry ladder, so a stuck generation does not sit in the queue a reindex or a checklist run is waiting in. |
| `KAFKA_MOCK_DATA_PARTITIONS` | `1` | Partitions on that topic — the ceiling on how many mock-data generations run at once across the instance. Raise only alongside worker replicas. |
| `MOCK_DATA_SCROLL_PAGE_SIZE` | `256` | Points fetched per Qdrant scroll page while enumerating a module's files for schema detection. |
| `MOCK_DATA_MAX_FILES_PER_JOB` | `200` | Files read per generation run before the rest are reported skipped. Unlike the checklist generator this is a single model call over the concatenated (capped) source, not a map-reduce — schema-shaped code is typically small relative to a whole module. |

---

## Values that fail silently

Most misconfiguration is loud. These are the ones that would not be, which is why they carry
startup bounds instead:

| Setting | At `0` it would… |
| --- | --- |
| `EMBEDDING_BATCH_SIZE` | never drain the batching loop — flushing empty batches forever while the lease keeps renewing. No log, no timeout, no failure |
| `CLONE_TIMEOUT_SECONDS` | kill every clone |
| `REPO_MAX_SIZE_MB` | reject every repository |
| `MAX_INDEXED_FILE_BYTES` | index nothing at all |
| `RAG_TOP_K` / `RAG_CONTEXT_MAX_CHARS` | send an empty context, and the model answers from memory in the same confident tone |
| `CHAT_MAX_CONCURRENCY` | admit no answers |

`RAG_HISTORY_TURNS=0` and `RAG_MIN_SCORE=0.0` are legitimate — they disable multi-turn memory
and the relevance floor respectively, and both are accepted.

---

## Frontend

| Variable | Default | What it does |
| --- | --- | --- |
| `API_URL` | `http://localhost:8000` | Base URL of the AskRepo API |

One variable, and the important thing about it is where it is read: **on the server only** —
by the API forwarding route (`app/api/[...path]/route.ts`), by `middleware.ts`, and by
`serverFetch`.

Next acts as a backend-for-frontend. It holds the session in two httpOnly cookies and calls
the API on the browser's behalf, so no token is ever readable by a script on the page. The
browser never calls the API directly, which means `API_URL` **does not need to be reachable
from a browser**: under Compose it is the service name `http://backend:8000`, not the
published host port.

This inverts the old `NEXT_PUBLIC_API_URL` rule, which was correct while the browser did the
fetching. Re-adding a `NEXT_PUBLIC_` prefix would inline the value into the client bundle and
invite exactly the direct-from-browser call the proxy exists to prevent.

---

## Docker Compose (`infra/.env`)

`make up` needs no `infra/.env` — every value has a `${VAR:-default}` fallback. Copy
[`infra/.env.example`](../infra/.env.example) to `infra/.env` to override. **Its lines are
commented out on purpose:** an uncommented line pins that value, so a compose default that
later changes would stop reaching you. Uncomment only what you are actually overriding.

`BOOTSTRAP_ADMIN_PASSWORD` is the one line left live, because it is the one variable with no
fallback.

Values not listed here are fixed in `infra/docker-compose.yml` because they describe the
compose network itself (`QDRANT_URL`, `REDIS_URL`, `KAFKA_BOOTSTRAP_SERVERS`, and
`DATABASE_URL`'s host).

**Credentials and secrets**

| Variable | Default | Notes |
| --- | --- | --- |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `askrepo` | Also assembled into the backend's `DATABASE_URL` |
| `SECRET_KEY` | `dev-insecure-change-me` | Shared by backend and worker |
| `PAT_ENCRYPTION_KEY` | `dev-insecure-change-me` | Shared by backend and worker |
| `BOOTSTRAP_ADMIN_PASSWORD` | **none** | No fallback on purpose. Set it before the first `make up` / `make seed` |

**Published ports** — change these when something else on your machine already holds one:

| Variable | Default |
| --- | --- |
| `FRONTEND_PORT` | `3000` |
| `BACKEND_PORT` | `8000` |
| `POSTGRES_PORT` | `5432` |
| `REDIS_PORT` | `6379` |
| `QDRANT_HTTP_PORT` / `QDRANT_GRPC_PORT` | `6333` / `6334` |
| `KAFKA_PORT` | `9092` |
| `OLLAMA_PORT` | `11434` — only read when the containerised `ollama` profile is on |

`CORS_ORIGINS` is derived from `FRONTEND_PORT`, so changing the frontend port keeps the API
in agreement automatically.

**Models and app**

| Variable | Default |
| --- | --- |
| `APP_ENV` / `APP_NAME` / `DEBUG` | `development` / `AskRepo API` / `true` |
| `TRUSTED_PROXY_HOPS` | `0` — nothing sits in front of the API in the dev stack |
| `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` | `ollama` / `nomic-embed-text` / `http://host.docker.internal:11434` / empty |
| `CHAT_PROVIDER` / `CHAT_MODEL` / `CHAT_BASE_URL` / `CHAT_API_KEY` | `ollama` / `qwen2.5-coder:14b` / `http://host.docker.internal:11434` / empty |
| `API_URL` | `http://backend:8000` |
| `KAFKA_CLUSTER_ID` | a fixed KRaft cluster id |

### Ollama runs on the host, not in Docker

**This is the default, and it needs no `infra/.env` entry.** The containerised `ollama`
service still exists, but it sits behind a Compose profile that is off — `make infra` starts
four datastores and `make up` starts the apps against a model server you run yourself:

```bash
ollama serve        # or the menu-bar app
make pull-models    # pulls the configured EMBEDDING_MODEL and CHAT_MODEL
make infra
make dev
```

`make dev` and `make worker` check `http://localhost:11434` first and print a warning if
nothing answers. It is a warning and never a failure, because an instance on a hosted
embedding or chat provider legitimately has no Ollama at all.

Why: Ollama inside Docker on macOS never gets Metal, because the Apple GPU is not passed
through to Linux containers. Every embed and every generated token is CPU-only, and a model
larger than the Docker VM's memory allocation cannot load at all — it thrashes and starves
the rest of the stack. A host-native Ollama gets Metal and the machine's full RAM.

**Two different endpoints for the same server, and that is not a mistake.** Under `make dev`
the API and worker run on the host, so `backend/.env` uses `http://localhost:11434`. Under
`make up` they run in containers, where `localhost` is the container itself and
`host.docker.internal` is the machine outside — which is why the Compose defaults use the
latter. Docker Desktop resolves that name natively; on Linux the `extra_hosts:
host.docker.internal:host-gateway` entry on `backend` and `worker` supplies it.

Two host-side notes for `make up`: bind Ollama to all interfaces so a container can reach it,
and expect it to be reachable by anything else on your network while it is —

```bash
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"   # then restart Ollama.app
```

#### Running Ollama in Docker anyway

On a Linux box with the NVIDIA runtime, the container is the right answer. Two steps, and the
second is not optional:

```bash
make infra OLLAMA_IN_DOCKER=1     # any non-empty value re-enables the profile
```

```dotenv
# infra/.env — the URLs default to the host, so without these the containers
# talk straight past the service you just started.
EMBEDDING_BASE_URL=http://ollama:11434
CHAT_BASE_URL=http://ollama:11434
```

Then pull into the container rather than with `make pull-models`:
`docker compose -f infra/docker-compose.yml exec ollama ollama pull nomic-embed-text`.

The production stack (`docker-compose.prod.yml`, all the `-prod` targets) is unchanged: it
still runs Ollama in a container behind the profile, which `make pull-models-prod` feeds.

**`EMBEDDING_MODEL` is load-bearing once a project is indexed.** The collection is named for
provider + model + width, and the project row records what it was indexed with — change the
model and every question returns `409 EMBEDDING_MODEL_CHANGED` until you reindex. `CHAT_MODEL`
carries no such constraint: it can be swapped freely, and a smaller one (`qwen2.5-coder:7b`,
~4.7 GB, against the 14b's ~9.5 GB resident) is the difference between fitting in 16 GB and
swapping.

---

## Adding a setting

1. Add the field to `Settings` in `backend/app/config.py`, with a `ge=`/`le=` bound if a
   nonsensical value would fail silently rather than loudly.
2. Add it to `backend/.env.example`, in its group, with the same default and **no inline
   prose** — that file is a name-and-default list.
3. Document it here, in the matching section. A setting with no entry in either file is
   undiscoverable.
4. If Compose needs to pass it through, add it to `infra/docker-compose.yml` — to the
   `x-app-env` anchor if both the API and the worker need it — and to the
   [Compose reference](#docker-compose-infraenv) above.

`.claude/rules/documentation.md` makes steps 2–4 part of the same change, not a follow-up.

---

## See also

- [`installation.md`](installation.md) — step-by-step local setup
- [`deployment.md`](deployment.md) — production images, TLS, secrets, backups
- [`docs/PRD.md`](PRD.md) — §5 the stack, §9 the security model these settings implement
- [`SECURITY.md`](../SECURITY.md) — threat model and operator responsibilities
- [`backend/README.md`](../backend/README.md) — routes, layout, dev commands
- [`frontend/README.md`](../frontend/README.md) — scripts and app layout
