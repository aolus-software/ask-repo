# Contributing to AskRepo

Thanks for your interest. AskRepo is a learning project first and a usable tool second —
that shapes what makes a good contribution: clarity beats cleverness, and a change that
teaches something is worth more than a micro-optimization.

Read [`docs/PRD.md`](docs/PRD.md) before proposing anything substantial. It records what's
planned, what's deliberately out of scope for v1, and which questions are still open.

## Getting set up

```bash
git clone <your-fork> && cd ask-repo
make setup    # uv sync + bun install
make infra    # postgres + qdrant + redis + kafka + ollama
make dev      # both dev servers
```

`make help` lists every target. Or run everything in Docker with `make up`, or drive the
pieces directly — see [`README.md`](README.md) → "Starting without `make`".

## Workflow

1. **Open an issue first** for anything beyond a typo or an obvious bug fix. It's cheaper
   to disagree about an approach in an issue than in a finished PR.
2. Branch from `main`: `feat/short-description`, `fix/short-description`,
   `docs/short-description`, or `chore/short-description`.
3. Make the change, with tests.
4. Run the checks below.
5. Open a PR and fill in the template — particularly **How this was verified**.

## Checks

From the repo root, `make check` runs everything CI would — for **both** apps: lint, format
check, typecheck, and
tests across both apps. **Run `make infra` first** — the backend suite runs against real
Postgres and Redis rather than mocks or SQLite (see `backend/tests/conftest.py`), and
`typecheck` now runs mypy over the backend as well as `tsc` over the frontend. The individual
commands, if you want them:

**Backend**

```bash
cd backend
uv run ruff check .      # lint
uv run ruff format .     # format
uv run mypy .            # typecheck
uv run pytest            # tests (integration tests excluded)
```

### Integration tests

Most of the suite fakes the broker, so `make check` needs no Kafka. A small set of tests
cannot be faked — a consumer being evicted mid-job, a redelivery, a rejoin — and those run
against a **real broker** behind the `integration` marker, which `pytest`'s default
`addopts` deselects:

```bash
make infra              # a real Kafka and Qdrant must be up
make test-integration   # cd backend && uv run pytest -m integration -v
```

Expect it to take around 40 seconds. That is not slowness to optimise away: one test
deliberately runs a job past `max.poll.interval.ms` to prove the worker keeps its place in
the consumer group, so the wall-clock time *is* the assertion.

If you add a test to that marker, check it fails when you break the thing it tests. Several
of these safety properties are invisible to the obvious assertion — an eviction mid-job does
not cause a second index, because the database lease refuses the redelivery. See
[`.claude/rules/ingestion.md`](.claude/rules/ingestion.md).

**Frontend**

```bash
cd frontend
bun lint
bun run build            # catches type errors the dev server tolerates
```

**Infra**

```bash
cd infra && docker compose config --quiet
```

## Conventions

These are settled in [`docs/PRD.md`](docs/PRD.md) §5.1 — worth reading in full, but the
short version:

- **`snake_case` internally, `camelCase` on the wire.** Python attributes and Postgres
  columns are `snake_case`; every JSON request and response body is `camelCase`. The
  translation lives in one place — the `ApiModel` base class in
  `backend/app/schemas/base.py`. Inherit it for anything that crosses the HTTP boundary;
  a schema on plain `BaseModel` silently ships `snake_case` keys.
- **UTC, timezone-aware timestamps** (`timestamptz`), ISO-8601 on the wire.
- **UUIDs in URLs**, never sequential integers.
- **Soft delete** via `deleted_at` on every table; queries filter `deleted_at IS NULL`.
  Qdrant points are the exception: they're **hard**-deleted, because a vector store has no
  soft-delete and a query-time filter is one forgotten call away from serving deleted data.
- **Error codes carry meaning:** `403` when the caller may see a thing but not do this to
  it; `404` when they shouldn't know it exists; `409` for valid-but-wrong-state; `429` for
  rate limits.
- **Read scoping lives in one function.** Never filter projects inside a route handler.
  Phase 2 swaps one access resolver for per-project RBAC; scattered filtering would make
  that a rewrite.
- **Frontend colour goes through tokens.** Never a `dark:` colour utility and never a
  palette utility (`bg-zinc-50`) — use the semantic role (`bg-card`,
  `text-muted-foreground`). `frontend/app/globals.css` is the only file allowed a raw hex.
  See [`docs/design.md`](docs/design.md).

Keep files focused. When one grows large enough that you can't hold it in your head, that's
usually a sign it's doing more than one job.

## Commit messages

Conventional-commit prefixes, imperative mood, and a body explaining *why* when the reason
isn't obvious from the diff:

```
feat(auth): rotate refresh tokens on use

Presenting an already-used refresh token now revokes the whole chain, so a
stolen token is detectable rather than silently valid for 30 days.
```

Prefixes in use: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `infra`.

## Tests

New behaviour needs a test. Two categories matter more than the rest, because they encode
decisions rather than mechanics:

- **Access tests.** Every rule in PRD §7 — a non-creator gets `403` on delete, an admin
  succeeds, one user can't read another's conversation. These are the tests that stop a
  refactor from quietly turning shared-by-design into leaked-by-accident.
- **Ingestion validation tests.** URL scheme, host allowlist, and private-address
  rejection (PRD §9). The clone client runs inside a private network, so a regression here
  is an SSRF, not a cosmetic bug.

## Reporting security issues

Don't open a public issue. See [`SECURITY.md`](SECURITY.md).

## Things that won't be merged

Not because they're bad ideas, but because they're out of scope — see PRD §2:

- Multi-tenancy, or anything that makes one instance serve two organizations.
- Public registration or social login.
- Per-project roles and permissions — that's phase 2, and it wants a design first.
- Model fine-tuning.
- Automatic code changes written back to a repo. AskRepo reads and explains.
- Large refactors bundled into a feature PR. Split them.
