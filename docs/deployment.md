# Deployment

Running AskRepo for a team, on a machine other people reach.

The production stack ships: `infra/backend.prod.Dockerfile`,
`infra/frontend.prod.Dockerfile`, `infra/docker-compose.prod.yml`, and a `-prod` Make target
for every step below. **One thing does not ship — TLS.** There is no Caddyfile in this repo,
and without a reverse proxy in front, login does not work at all on a real hostname
([§4](#4-terminate-tls-with-caddy) explains why and gives you the config).

[`../SECURITY.md`](../SECURITY.md) is the authority on what remains your responsibility after
this page is done. Where they overlap, this links rather than repeats.

**The whole procedure, on a fresh box:**

```bash
cp infra/.env.example infra/.env    # then fill it in — see §2
make setup-prod                     # verify the box is ready; changes nothing
make build-prod
make migrate-prod
make seed-prod
make up-prod
```

---

## What AskRepo assumes about where it runs

From [`PRD.md`](PRD.md) §1 and §5. These are design assumptions, not preferences:

- **One organization, one instance.** There is no cross-organization tenancy. A second
  organization runs a second instance.
- **Internal network only.** VPN or Tailscale. The instance has no public registration, no
  email verification, and no self-service password reset, and its threat model puts malicious
  authenticated users *out of scope*. It is not built to survive the open internet.
- **A single box is the expected shape.** Postgres, Qdrant, Redis, Kafka and possibly Ollama
  on one VPS or on-prem machine. Kafka is single-node KRaft with replication factor 1 — a
  development-scale broker, documented as one. There is no high-availability story.
- **TLS is required, not optional.** The refresh token is a `Secure` cookie, so browsers will
  not send it over plain HTTP outside `localhost`.

Sizing: the answering model dominates. `qwen2.5-coder:14b` needs ~9 GB resident on top of
Postgres, Qdrant, Redis, Kafka and the two apps. Budget 16 GB minimum for a local model, or
point `CHAT_PROVIDER` at a hosted API and size for the datastores alone.

---

## 1. Build production images

```bash
make build-prod        # both images
make rebuild-prod      # without cache
```

Two Dockerfiles, separate from the development ones rather than parameterised, because almost
nothing about them is the same.

**`infra/backend.prod.Dockerfile`** — serves the API and, with a different command, the worker.
Differences from the development image:

- **No `--reload`,** and the source is baked in rather than bind-mounted.
- **No `alembic upgrade head` in `CMD`.** The development image chains migration, seeding and
  serving into one start command. That is fine for a single container and wrong for a
  deployment: two replicas restarting together race on the same migration, and schema changes
  become coupled to serving. Migrations are [step 5](#5-first-boot).
- **Runs as a non-root user** (`askrepo`, uid 10001). This image also runs the worker, which
  is the process that clones user-supplied URLs from inside your network.
- **Multi-stage,** so `uv` itself does not ship, and `--no-dev` drops mypy, pytest and ruff.
  The result is roughly half the size of the development image.
- `git` is still installed — the cloner shells out to it — and `/data/repos` is created and
  owned by the runtime user.

**`infra/frontend.prod.Dockerfile`** — runs `next build` once, at build time, and serves the
output with `next start`. The development image compiles on demand and never builds.

It has three stages, and the reason is worth knowing before you edit it: **Bun installs, Node
builds and serves.** `bun run build` segfaults running Next's compiler on linux/arm64 (Bun
1.3.14, both musl and glibc), so a Bun-built image builds fine on an x86 CI box and crashes on
an ARM one. Bun still owns dependency resolution, because `bun.lock` is the lockfile in this
repo and npm would resolve it afresh. `node_modules` in the runtime stage is a separate
production-only install, and `.next/cache` is dropped.

No `API_URL` is needed at build time. Everything that talks to the API also reads cookies,
which makes those routes dynamic; only `/login`, `/change-password` and `/_not-found` are
prerendered and none of them fetches anything.

---

## 2. Configure

Copy `infra/.env.example` to `infra/.env` and fill in the production block. Six values matter,
and `infra/docker-compose.prod.yml` refuses to start without four of them — `${VAR:?message}`
fails the command with a specific message rather than starting a stack with a publicly-known
key.

| Variable | Notes |
| --- | --- |
| `SECRET_KEY` | Signs access-token JWTs. `openssl rand -hex 32`. Rotating it invalidates every access token immediately |
| `PAT_ENCRYPTION_KEY` | Fernet key for stored repository tokens. `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` |
| `POSTGRES_PASSWORD` | Not the `askrepo` default |
| `PUBLIC_ORIGIN` | Your real https origin. Becomes `CORS_ORIGINS` |
| `BOOTSTRAP_ADMIN_PASSWORD` | Required before first boot. No fallback exists anywhere |
| `TRUSTED_PROXY_HOPS` | Defaults to `1` in the production file — correct for one Caddy. Count your proxies |

**`PAT_ENCRYPTION_KEY` must be identical in the API and the worker.** The API encrypts a PAT
when a project is created and the worker decrypts it to clone. The two share one `x-app-env`
anchor precisely so they cannot drift. A mismatch is a clone that fails with a decryption
error, not a startup error. Losing the key means every stored PAT must be re-entered by hand —
it is not recoverable from the database, and that is the point.

Then check the box before you build anything:

```bash
make setup-prod
```

It reads `infra/.env`, changes nothing, and reports each item individually — including the two
that are easy to leave wrong: a `PUBLIC_ORIGIN` that is not https, and `TRUSTED_PROXY_HOPS`
still at `0`. It exits non-zero if anything is missing.

`APP_ENV` is **pinned** to `production` in the compose file rather than defaulted, because that
value is what turns the placeholder secrets, `REFRESH_COOKIE_SECURE=false` and
`TRUSTED_PROXY_HOPS=0` into hard startup failures instead of a stack that boots and looks fine.

Everything else is in [`configuration.md`](configuration.md).

---

## 3. What the production compose file does differently

`infra/docker-compose.prod.yml` is a **standalone file, not an overlay.** Layering it with
`-f docker-compose.yml -f docker-compose.prod.yml` is the obvious approach and it silently does
not work: Compose merges `volumes` by target path rather than replacing the list, so the
development bind-mounts of your working copy over `/app` survive into the merged config and the
deployed code becomes whatever is checked out on the box. Every `-prod` Make target passes the
production file alone.

What it changes, and what each one prevents:

| Change | What it prevents |
| --- | --- |
| No bind mounts anywhere | The deployed code being the checkout on the box, with no immutability or rollback |
| `APP_ENV: production`, pinned | Booting with `SECRET_KEY=dev-insecure-change-me` |
| `DEBUG: "false"` | FastAPI debug mode in front of users |
| No `ports:` on postgres, qdrant, redis, kafka, ollama | Five unauthenticated services on the host. Anyone who reaches Kafka can enqueue a clone of a URL of their choosing |
| Kafka advertises **one** internal listener | The dev stack's second `HOST://localhost` listener, which exists so `make dev` can reach the broker and would otherwise publish a reachable, unauthenticated one |
| `backend` and `frontend` published to `127.0.0.1` only | Caddy — and therefore TLS — being bypassable |
| `CORS_ORIGINS` from `PUBLIC_ORIGIN` | The dev file's hardcoded `http://localhost:3000` |
| `ollama/ollama` pinned to a tag | The untagged dev image floating to `:latest` and changing the model runtime under you |
| `frontend` waits for `backend: service_healthy` | A UI that is up before the API can answer |
| `worker` waits for `backend: service_healthy` | Workers starting against a schema `make migrate-prod` has not been run against |
| Log rotation on every service | Unbounded container logs filling the disk, which takes Postgres down with it |
| Project name `askrepo-prod` | A production stack on a shared machine attaching to development volumes |

**The worker deliberately has no healthcheck.** It exposes no endpoint and has no liveness
signal to probe; a check that merely confirmed the process exists would add nothing over
`restart: unless-stopped`. Its real failure mode — dying at startup while probing embedding
dimensions against an unreachable model server — shows up as a restart loop in `make ps-prod`,
which is what to watch for.

**The `ollama` profile** is enabled by every `-prod` Make target, same as the dev ones. To run
against a hosted model provider instead, drop `--profile ollama` from `COMPOSE_PROD` in the
`Makefile` and point `EMBEDDING_BASE_URL` and `CHAT_BASE_URL` elsewhere.

---

## 4. Terminate TLS with Caddy

**This is the piece that does not ship.** The frontend is the only thing a browser should
reach — Next proxies the API server-side, so the API needs no public route at all, which is why
both are published to `127.0.0.1` and only the frontend needs a vhost.

```caddyfile
askrepo.internal.example.com {
    reverse_proxy 127.0.0.1:3000
}
```

That is genuinely all of it for the common case. Caddy gets certificates automatically from
Let's Encrypt for a public hostname; an internal hostname has no public DNS, so use an internal
CA or a Tailscale certificate — `PRD.md` §5 anticipates this ("certs may be internal CA"):

```caddyfile
askrepo.your-tailnet.ts.net {
    tls /var/lib/tailscale/certs/askrepo.crt /var/lib/tailscale/certs/askrepo.key
    reverse_proxy 127.0.0.1:3000
}
```

**Count your proxies.** One Caddy means `TRUSTED_PROXY_HOPS=1`, which is the production
default. It tells the API how many entries to discard from the right of `X-Forwarded-For`
before trusting what remains. Left at `0` behind a proxy, every request's socket address is
Caddy's, so the per-IP login limit — meant to be 5 attempts per minute per caller — becomes 5
per minute for the entire organization, and because the limit is counted before the credential
check, ordinary successful logins consume it too. A production boot with `0` is refused at
startup for exactly this reason.

If you do expose the API directly, it needs its own vhost, its origin in `CORS_ORIGINS`, and
the hop count adjusted.

---

## 5. First boot

Migrations and seeding are deploy steps, not container start commands:

```bash
make migrate-prod
make seed-prod
make up-prod
```

`make seed-prod` is idempotent: if every bootstrap admin already exists it exits successfully
without even reading the password, which is why re-running it on every deploy is safe. It
creates `superuser@example.com` and `admin@example.com` with `is_admin` and
`must_change_password` set.

**Pre-pull the models**, or the first question blocks on a multi-gigabyte download:

```bash
make pull-models-prod
```

Then, immediately and before anyone else is let in: **log in as both seeded accounts and
complete the forced password change.** They share the one bootstrap password until you do.

---

## 6. Verify the deployment

```bash
make ps-prod
make logs-prod
```

Six things worth checking explicitly, because each fails quietly:

1. **The workers survived startup.** They probe the embedding model for its vector width
   before anything else, and that is a live call. A restart loop here means Ollama is
   unreachable.
2. **`APP_ENV=production` actually took.** If a placeholder secret were still set the API
   would have refused to boot, so a running API is itself the proof.
3. **Login works over HTTPS.** If the refresh cookie is not being set, TLS is not terminating
   where you think it is.
4. **No datastore port answers from another machine.** `nc -vz <host> 5432 6379 9092 6333 11434`
   should fail on every one. The production file publishes none of them.
5. **Index a repository end to end.** It should move `pending` → `indexing` → `ready`. Stuck at
   `pending` means nothing is consuming the queue.
6. **Ask a question and confirm it cites real files.** That exercises Qdrant, the embedder and
   the chat model in one request.

---

## 7. Back up Postgres and the PAT key separately

Required by `PRD.md` §9.

```bash
make backup-prod    # writes backups/askrepo-<timestamp>.sql.gz
```

Postgres holds users, refresh tokens, projects, conversations, and the encrypted PATs. Run it
from cron and ship the output somewhere off the box.

**`PAT_ENCRYPTION_KEY` goes somewhere else.** A backup containing both the ciphertext and its
key is plaintext storage with extra steps. `make backup-prod` prints this reminder every time,
because the dump deliberately does not contain it.

**Qdrant needs no backup.** Every vector is reproducible by reindexing, and the projects table
records which collection each one wrote to. Restoring Postgres without Qdrant leaves projects
pointing at collections that no longer exist — reindex them and they recover.

**`/data/repos` needs no backup.** It is scratch: the working copy is deleted after indexing,
and a reindex re-clones rather than pulling.

---

## Operating it

### Upgrades

```bash
git pull
make build-prod
make backup-prod      # before the migration, not after
make migrate-prod
make up-prod
```

There is no automated rollback, and a migration that has run cannot be assumed reversible.

Tag your images if you deploy by pulling rather than building on the box: `VERSION` sets the
tag on both (`askrepo-backend:${VERSION:-latest}`).

### Everyday production targets

| Command | Does |
| --- | --- |
| `make setup-prod` | Preflight the box; changes nothing |
| `make build-prod` / `make rebuild-prod` | Build both images, with or without cache |
| `make up-prod` / `make down-prod` / `make restart-prod` | Start (detached, waits for healthy), stop, recreate |
| `make ps-prod` / `make logs-prod` | Status, logs |
| `make migrate-prod` / `make seed-prod` | Schema, bootstrap admins |
| `make psql-prod` | Postgres shell without publishing 5432 |
| `make pull-models-prod` | Pre-pull the Ollama models |
| `make backup-prod` | Timestamped Postgres dump |
| `make compose-config-prod` | Validate the production compose file |

There is deliberately **no `down -v` equivalent.** Deleting production volumes should not be
one typo away from a target you run every day — do it by hand if you mean it.

### Scaling ingestion

The concurrency cap is **partition count**, not a setting beside one. Two ingest partitions
means at most two repositories index at once, and a third worker replica owns no partition and
sits idle. To raise it, raise `KAFKA_INGEST_PARTITIONS` **and** `WORKER_REPLICAS` together.

Adding partitions to an existing topic is a Kafka operation, not something `ensure_topics` does
for you — it creates the topic with the configured partition count on first run and does not
repartition afterwards.

### Answer concurrency

`CHAT_MAX_CONCURRENCY` (default 2) caps answers generated at once, instance-wide. Against
Ollama, raising it does not shorten the queue: Ollama serialises inference internally, so more
concurrent answers means every answer is slower on a box already running four datastores.
Against a hosted API, it can go higher.

### What to watch

There is no metrics endpoint. What exists:

- `GET /health/live` — process liveness. Both production images carry a `HEALTHCHECK`, so
  `make ps-prod` reports health without compose having to define one.
- `GET /health/ready` — returns a `checks` map that is **empty**; no datastore probes are wired
  in yet. It does not currently tell you Postgres is up.
- Worker logs — the reconcile sweep runs every 60 seconds, re-enqueuing jobs stranded more than
  120 seconds and pruning expired refresh tokens.
- Projects stuck in `indexing` past a plausible duration, and anything landing in
  `askrepo.ingest.dlq` after `KAFKA_MAX_ATTEMPTS` (default 3).

### Known limits to plan around

- **Kafka is single-node, RF=1, no HA.** Losing the broker loses queued jobs. Projects are
  recovered by the reconcile sweep; in-flight indexing runs are not.
- **A Redis outage degrades login rate limiting.** The limiter fails open by design — an outage
  should not lock the whole team out — so brute-force protection falls back to bcrypt's cost
  while Redis is down.
- **Head-of-line blocking within a partition is accepted and unmitigated.** One enormous
  repository holds its partition for the length of its index.
- **Projects are shared instance-wide.** Every authenticated user can list and query every
  project, by design (`PRD.md` §4.1). Per-project access control is phase 2, so scope the PATs
  you add accordingly — read-only, single repository.

---

## See also

- [`../SECURITY.md`](../SECURITY.md) — threat model and the full operator checklist
- [`configuration.md`](configuration.md) — every setting; [before production](configuration.md#before-production)
- [`installation.md`](installation.md) — local setup, and why it is not this
- [`PRD.md`](PRD.md) — §5 the stack, §9 the security model
