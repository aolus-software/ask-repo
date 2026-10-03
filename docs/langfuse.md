# The AI call log on Langfuse

How to turn on the AI call log, find what it recorded, and run it in production. The call log
records what each model call **cost** — provider, model, feature, timing, token counts, success or
failure — in a self-hosted [Langfuse](https://langfuse.com). It never records what a call **said**.

It is **off by default** (`LANGFUSE_ENABLED=false`). An instance that leaves it off loads nothing
and sends nothing, and nothing on this page applies to it.

How the recorder works is in [`llm.md`](llm.md) "The call log". The invariants are in
`.claude/rules/call-log.md`. Every setting is in [`configuration.md`](configuration.md).

---

## What reaches Langfuse, and what never does

| Sent | Never sent |
| --- | --- |
| Provider and model name | The prompt, or any message in it |
| The feature that made the call (below) | The completion |
| Start time, end time, duration | Retrieved code, or a question |
| Input and output token counts | A user id, a name, or an email |
| Success or failure, and the error's **class** name | The error's message — provider error text can echo the request |
| Project id, prompt version, the job's delivery attempt | Anything from a conversation's title |

This is structural, not a mask. The records the recorder builds (`CallStart`, `CallRecord`) have
no field that could hold content, and a test pins both field sets.

---

## How the backend connects to Langfuse

**Langfuse does not reach AskRepo — AskRepo sends to Langfuse, and only once it is turned on.**
When `LANGFUSE_ENABLED=true`, the API process and the worker each do this once, at startup:

1. Read the `LANGFUSE_*` settings ([`configuration.md`](configuration.md) "AI call log").
2. Construct one Langfuse client from them (`build_call_log`, `app/observability/langfuse_sink.py`).
3. Attach the call recorder to the chat model they build (`build_chat_model(..., callbacks=...)`).

From then on every model call is sent with no further setup — the Ask answer path, grading,
checklist and mock-data generation, both refinement chats. The client sends in the background, in
batches. If Langfuse is down or the keys are wrong, the model call still succeeds and the failure
appears only as a `WARNING` in that process's log. The call log never fails a user's request.

**The connection needs three values.**

| Setting | What it is |
| --- | --- |
| `LANGFUSE_BASE_URL` | Where to send. An internal address — browsers never use it |
| `LANGFUSE_PUBLIC_KEY` | The Langfuse project's public API key |
| `LANGFUSE_SECRET_KEY` | The project's secret API key |

You never create these keys in the Langfuse UI. Langfuse creates its project **with** the keys you
give it in `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` / `_SECRET_KEY`, on first boot. So the job is to hand
the backend that same pair, and whether that happens on its own depends on how the backend runs:

| How the backend runs | Address | Keys | What you set |
| --- | --- | --- | --- |
| In Docker (`make up`) | Set by the compose file: `http://langfuse-web:3000` | Set by the compose file — the same pair Langfuse was created with | `LANGFUSE_ENABLED=true` in `infra/.env` |
| On the host (`make dev`) | The default, `http://localhost:3001` | **Not set.** The host backend reads `backend/.env`, which the compose file never touches | `LANGFUSE_ENABLED`, `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` in `backend/.env` |
| Production (`make up-prod`) | Set by the compose file: `http://langfuse-web:3000` | Set by the compose file, from the `LANGFUSE_INIT_PROJECT_*` pair in `infra/.env` | The secrets and `LANGFUSE_ENABLED=true` in `infra/.env` |

**A missing key stops the process at boot**, with `LANGFUSE_ENABLED requires LANGFUSE_PUBLIC_KEY
and LANGFUSE_SECRET_KEY`. Wrong keys or a wrong address do not — they show up as `WARNING` lines
and an empty Traces page.

---

## Before you start: memory

Langfuse is five more containers, and they need about **4 cores and 16 GiB on their own**.
ClickHouse is the heavy part, and it fails to start without memory. That is on top of what
Postgres, Qdrant, Redis, Kafka and your model server already use. Check the machine has room
first — on a laptop, close whatever else is heavy.

---

## Set it up for development

Choose the path that matches how you run AskRepo ([`installation.md`](installation.md)).

### Apps on the host (`make dev`)

**1. Start the Langfuse containers.**

```bash
make infra LANGFUSE=1
```

This does two things. It creates a `langfuse` database on your existing Postgres (`make
langfuse-db`, which is safe to re-run). Then it starts the four usual datastores plus the five
Langfuse services. On first boot Langfuse creates its organization, a project with the id
`askrepo`, that project's API keys, and an admin user. You do not need an `infra/.env` for any
of this: the development compose file has defaults for all of it.

**2. Turn the call log on in `backend/.env`.**

```
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-lf-dev-askrepo
LANGFUSE_SECRET_KEY=sk-lf-dev-askrepo
```

These are the keys the development stack created in step 1. `LANGFUSE_BASE_URL` already defaults
to `http://localhost:3001` and `LANGFUSE_PROJECT_ID` to `askrepo`, so leave both alone. The
backend refuses to start with `LANGFUSE_ENABLED=true` and either key missing.

**3. Restart `make dev`.** The API and the worker each read the setting when they start.

**4. Log in to Langfuse** at <http://localhost:3001> as `admin@askrepo.local` with the password
`dev-insecure-change-me`. That is the only account: sign-up is turned off
([Accounts](#accounts-sign-up-is-off)). Then [check it works](#check-it-works).

### Everything in Docker (`make up`)

**1. Turn it on in `infra/.env`:**

```
LANGFUSE_ENABLED=true
```

The backend and worker containers already get the development keys and the internal address
`http://langfuse-web:3000` from the compose file.

**2. Create the database, then start the stack:**

```bash
make infra LANGFUSE=1   # creates the langfuse database and starts the datastores
make up LANGFUSE=1      # the whole stack, Langfuse included
```

`make up` does not create the `langfuse` database itself, so run `make infra LANGFUSE=1` (or
`make langfuse-db LANGFUSE=1` against a running Postgres) before the first `make up LANGFUSE=1`.
You only need to do it once per Postgres volume.

**3. Log in** at <http://localhost:3001>, the same as above.

---

## Check it works

1. Ask a question on the Ask screen, or run a checklist generation.
2. In Langfuse, open the **askrepo** project and go to **Traces**. Data appears **15–30 seconds**
   after a call ends — the SDK sends in batches, and Langfuse processes them in the background.
3. Open a trace. Each model call is one *generation* inside it, named after its feature.

If nothing appears, see [Troubleshooting](#troubleshooting).

---

## Reading the traces

**A trace is one unit of work, not one model call.**

| Trace | Holds | Trace id seeded from |
| --- | --- | --- |
| One Ask or refinement-chat turn | `classify`, `grade`, `answer` (or `history_answer`), and a proposal on the refinement chats | The assistant message id |
| One checklist generation | One `map` per file, then `reduce` — a 200-file run is one trace with about 201 generations | The change set id |
| One mock-data generation | `generate_mock_data` | The change set id |

The re-run route and the capability probe have no message or change set to seed from, so their
calls are recorded without a trace grouping.

**Generation names** are the feature that made the call:

| Name | Where it comes from |
| --- | --- |
| `classify` | Deciding what kind of question it is |
| `grade` | Judging whether the retrieved code is enough |
| `answer` | Writing the answer from the retrieved code |
| `history_answer` | Answering from the conversation alone |
| `propose_checklist` | The checklist refinement chat proposing changes |
| `propose_mock_data` | The mock-data refinement chat proposing changes |
| `map` | Checklist generation, one call per file |
| `reduce` | Checklist generation, combining the per-file notes |
| `generate_mock_data` | Mock-data generation |
| `capability_probe` | The worker's startup check that the model can return structured output |
| `untagged` | A call that did not say which feature it was — a bug; a test should have caught it |

Each generation's **metadata** carries the provider, the feature, the project id, the prompt
version, and `attempt` — the job's Kafka delivery attempt, starting at `0`. `attempt` is absent on
calls the API makes. A retried job's calls show a higher `attempt`, so the cost of the retry
ladder is visible.

**Cost** comes from Langfuse's own model price table, for hosted models it knows. A local model
shows token counts and no cost.

**From the feedback screen.** On **Settings → Feedback**, a vote on a checklist or mock-data reply,
or on a change set, links to its trace. A vote on an **Ask answer never links**: admins see only
the day a vote was cast, and a trace carries second-precision times that would undo that
(`.claude/rules/feedback.md`). There is also no link when the call log is off, or when the change
set has been deleted.

---

## Accounts: sign-up is off

**Nobody can create a Langfuse account by visiting the login page.** Both compose files set
Langfuse's `AUTH_DISABLE_SIGNUP=true` on `langfuse-web`, so the only account that exists is the
one `LANGFUSE_INIT_USER_*` creates on first boot. That matters because Langfuse has its own login,
outside AskRepo's access control, and an account sees every project's call records — metadata
only, but instance-wide. The intended readers are AskRepo's administrators (`SECURITY.md`).

The setting is `LANGFUSE_AUTH_DISABLE_SIGNUP` in `infra/.env`, default `true`. Leave it there.

**Adding a colleague.** Langfuse applies `AUTH_DISABLE_SIGNUP` to invited people too: an invite
to someone with no account stays pending until they sign up, and they cannot sign up while it is
on. So adding someone means opening the door briefly:

1. In Langfuse, go to **Organization settings → Members**, add their email address and choose a
   role. They appear as a pending invite. (This instance sends no email, so tell them yourself.)
2. Set `LANGFUSE_AUTH_DISABLE_SIGNUP=false` in `infra/.env` and recreate `langfuse-web`:
   `make up-prod LANGFUSE=1` (or `make infra LANGFUSE=1` in development).
3. They sign up at `LANGFUSE_UI_URL` **with that exact email address**, and land in the
   organization with the role you chose.
4. Set `LANGFUSE_AUTH_DISABLE_SIGNUP=true` again and recreate `langfuse-web` the same way.

Anyone who finds the sign-up page during that window can register too, but without an invite they
belong to no organization and see no project data. Remove any account you did not expect under
**Organization settings → Members**. Keep the window short.

**Removing someone** is **Organization settings → Members → remove**. Their account still exists
but reaches nothing.

**A forgotten password.** With no mail server configured, Langfuse has no "forgot password"
flow. Its documented recovery is a manual edit of its `users` table — see Langfuse's
[authentication docs](https://langfuse.com/self-hosting/security/authentication-and-sso#password-reset).
Keep the initial admin's password somewhere your team can find it.

---

## Turn it off

1. Set `LANGFUSE_ENABLED=false` (in `backend/.env`, or `infra/.env` under Docker), and restart.
   The app then loads nothing and sends nothing.
2. Stop the containers, keeping their data:

```bash
make infra-stop LANGFUSE=1   # or infra-down LANGFUSE=1 to remove the containers too
```

**Pass `LANGFUSE=1` to every Make target that should see the Langfuse services** — `infra-status`,
`infra-logs`, `infra-stop`, `infra-down`, and the `-prod` equivalents. Without it those targets
act on the usual services only, and the Langfuse containers keep running unnoticed.

---

## Deploy it to production

This assumes AskRepo itself is already deployed by [`deployment.md`](deployment.md) — Postgres
running, Caddy in front of the app. Langfuse runs on the same box, from the same
`infra/docker-compose.prod.yml`, behind its `langfuse` profile.

### 1. Check the box has room

Langfuse needs about **4 cores and 16 GiB** on top of everything already running. Check with
`free -h` and `nproc` before you start. If the box is short, ClickHouse is the service that fails,
and it fails by restarting in a loop rather than with a clear error.

### 2. Set the secrets in `infra/.env`

Uncomment the `LANGFUSE_*` block from `infra/.env.example` and replace every value. None of the
secrets has a production default:

| Variable | What it is | Generate with |
| --- | --- | --- |
| `LANGFUSE_SALT`, `LANGFUSE_NEXTAUTH_SECRET` | Langfuse's own signing secrets | `openssl rand -base64 32` |
| `LANGFUSE_ENCRYPTION_KEY` | Encrypts secrets Langfuse stores. Exactly 64 hex characters | `openssl rand -hex 32` |
| `LANGFUSE_CLICKHOUSE_PASSWORD`, `LANGFUSE_MINIO_ROOT_PASSWORD`, `LANGFUSE_REDIS_AUTH` | Passwords for the three Langfuse datastores. Nothing outside the compose network uses them | `openssl rand -hex 24` |
| `LANGFUSE_INIT_PROJECT_PUBLIC_KEY`, `LANGFUSE_INIT_PROJECT_SECRET_KEY` | The project's API keys. Langfuse creates the project with them, and the API and worker send with them — one pair configures both ends | `pk-lf-` and `sk-lf-` followed by `openssl rand -hex 16` |
| `LANGFUSE_INIT_USER_EMAIL`, `LANGFUSE_INIT_USER_PASSWORD` | The first Langfuse login — the only account until you add one ([Accounts](#accounts-sign-up-is-off)) | Your own |

**Keep `LANGFUSE_ENCRYPTION_KEY` and `LANGFUSE_SALT` once set.** Changing either later makes what
Langfuse already stored unreadable. Back them up with the rest of `infra/.env`.

**`LANGFUSE_INIT_*` is read once.** Langfuse creates the organization, project, keys and user on
first boot, only if they do not exist yet. Changing `LANGFUSE_INIT_USER_PASSWORD` afterwards does
not change the password.

### 3. Set the two addresses

```
LANGFUSE_ENABLED=true
LANGFUSE_UI_URL=https://langfuse.internal.example.com
```

`LANGFUSE_UI_URL` is the address administrators' **browsers** use. Langfuse builds its login
redirects from it, and AskRepo builds the trace links on the feedback screen from it. Leave
`LANGFUSE_BASE_URL` unset: the API and worker reach Langfuse inside the compose network at
`http://langfuse-web:3000`, never through the proxy.

### 4. Start it

```bash
make up-prod LANGFUSE=1
```

In order, this:

1. runs `langfuse-require-prod`, which refuses to start if any secret above is unset or still a
   development value (`dev-insecure-change-me`, the `pk-lf-dev-askrepo`/`sk-lf-dev-askrepo` keys,
   an all-zero encryption key). It names the variable and never prints the value;
2. creates the `langfuse` database on your existing Postgres (`langfuse-db-prod`, safe to re-run);
3. starts the whole stack, Langfuse included, and recreates the backend and worker so they pick
   up `LANGFUSE_ENABLED=true`.

**Use the Make target, not `docker compose` by hand.** The production compose file cannot require
these secrets itself: Compose reads every service's variables even when its profile is off, so a
hard requirement there would stop every deployment that does not run Langfuse. A hand-run
`docker compose -f infra/docker-compose.prod.yml --profile langfuse up` skips the check and
starts with empty secrets.

The first boot takes a few minutes — Langfuse runs its Postgres and ClickHouse migrations. Watch
it with `make logs-prod LANGFUSE=1` until `langfuse-web` reports it is ready.

### 5. Put it behind Caddy

The Langfuse UI listens on `127.0.0.1:3001` only. Give it its own hostname, next to the app's
vhost from [`deployment.md`](deployment.md) §4:

```caddyfile
langfuse.internal.example.com {
    reverse_proxy 127.0.0.1:3001
}
```

The same certificate notes apply — an internal hostname needs an internal CA or a Tailscale
certificate. Use a hostname only your administrators can reach: Langfuse shows every project's
call records to anyone with an account.

### 6. Log in and check it

Open `LANGFUSE_UI_URL`, sign in with `LANGFUSE_INIT_USER_EMAIL` / `_PASSWORD`, and follow
[Check it works](#check-it-works). If traces do not arrive, look for `WARNING` lines with
`make logs-prod LANGFUSE=1`.

**Every later `-prod` target needs `LANGFUSE=1` too** — `restart-prod`, `down-prod`, `ps-prod`,
`logs-prod`. Without it they act on the usual services only.

### Upgrading Langfuse

Change the pinned tag on `langfuse-web` and `langfuse-worker` in `infra/docker-compose.prod.yml`
— always both, to the same version — read Langfuse's release notes for that range, then run
`make up-prod LANGFUSE=1`. Migrations run on start. Back up Postgres first (`make backup-prod`);
ClickHouse holds only call records, which you can afford to lose.

### Pinned images

The production file pins `langfuse` and `langfuse-worker` at `4.50.0`, and ClickHouse at
`25.12`. The MinIO image (`cgr.dev/chainguard/minio`) and `redis:7` follow upstream's own tags and
are not pinned to a patch release — re-check them when you upgrade.

### Outbound network access

Self-hosted Langfuse reaches out to the internet by default. Two paths are closed in the compose
files; the third is yours.

| Path | What goes out | Closed by |
| --- | --- | --- |
| Usage ping | Anonymous usage statistics to Langfuse | `TELEMETRY_ENABLED=false` on `langfuse-web` and `langfuse-worker` |
| Version check | The web image's Prisma CLI calls `checkpoint.prisma.io` | `CHECKPOINT_DISABLE=1` on `langfuse-web` |
| Image pulls | Nothing is sent, but the images come from `docker.langfuse.com` | Not a setting. On a network with no outbound access, mirror the five images into your own registry and change `image:` |

The Python SDK in the API and worker sends only to `LANGFUSE_BASE_URL`.

### Retention

**Without a retention setting, Langfuse keeps every call record forever.** Its automated retention
is an Enterprise feature, and AskRepo has no setting for it because the data is in Langfuse's store,
not AskRepo's. On the open-source build the lever is a ClickHouse TTL on the tables that grow:

| Table | Time column |
| --- | --- |
| `traces` | `timestamp` |
| `observations` | `start_time` |
| `scores` | `timestamp` |

For 90 days, against the `default` database the compose file creates, with the ClickHouse
credentials exported from `infra/.env`:

```bash
docker compose -f infra/docker-compose.prod.yml exec langfuse-clickhouse \
  clickhouse-client --user "$LANGFUSE_CLICKHOUSE_USER" --password "$LANGFUSE_CLICKHOUSE_PASSWORD" --multiquery \
  --query "ALTER TABLE traces MODIFY TTL toDateTime(timestamp) + INTERVAL 90 DAY;
           ALTER TABLE observations MODIFY TTL toDateTime(start_time) + INTERVAL 90 DAY;
           ALTER TABLE scores MODIFY TTL toDateTime(timestamp) + INTERVAL 90 DAY"
```

ClickHouse deletes expired rows when it merges parts, not at the moment they expire.

**Check the table list against your version first.** The table and column names above come from
Langfuse's ClickHouse migrations, not from a running instance. Newer releases add `events_*`
tables keyed on `start_time`, and `event_log` and `blob_storage_file_log` carry `created_at`. Run
`SHOW TABLES` and `DESCRIBE TABLE <name>` against your pinned version, and give every table that
holds call data the same TTL.

The TTL does not reach MinIO — event payloads sit in the `langfuse` bucket, so set a bucket
lifecycle rule there — or the `langfuse` Postgres database.

---

## Troubleshooting

**The backend or worker will not start: `LANGFUSE_ENABLED requires LANGFUSE_PUBLIC_KEY and
LANGFUSE_SECRET_KEY`.** The call log is on and a key is missing. On the host, set both in
`backend/.env`. Under Docker the compose file supplies the development keys; in production they
come from `LANGFUSE_INIT_PROJECT_PUBLIC_KEY` / `_SECRET_KEY` in `infra/.env`.

**No traces appear.**

- Wait 30 seconds and refresh — export is batched.
- Check `LANGFUSE_ENABLED=true` reached the process that made the call, and that you restarted it.
  The API answers questions; the **worker** runs checklist and mock-data generation.
- Check the keys match the project. On the host they must be the ones the stack created
  (`pk-lf-dev-askrepo` / `sk-lf-dev-askrepo` unless you changed them in `infra/.env`).
- Check the address. On the host `LANGFUSE_BASE_URL` is `http://localhost:3001`; inside Docker it is
  `http://langfuse-web:3000`.
- Look for `WARNING` lines in the backend or worker log. A failure to send is logged there and
  never fails the model call, so this log is the only place it shows.

**ClickHouse exits or restarts.** Almost always memory. See [Before you start](#before-you-start-memory).

**`langfuse-web` cannot reach its database.** The `langfuse` database was never created on this
Postgres volume. Run `make langfuse-db LANGFUSE=1` (or `make langfuse-db-prod LANGFUSE=1`) and
restart `langfuse-web`.

**`make up-prod LANGFUSE=1` refuses to start.** It names the variables it rejected. Each one is
unset or still a development value in `infra/.env` — set a real value and run it again.

**A colleague cannot sign up.** Sign-up is off by design. Follow
[Adding a colleague](#accounts-sign-up-is-off).

**The Langfuse containers are still running after `make infra-stop`.** You left out
`LANGFUSE=1`. Run it again with the variable.
