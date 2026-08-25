# M1 — Project Ingestion: Design

**Milestone:** M1 (`docs/PRD.md` §6)
**Date:** 2026-08-25
**Status:** Approved design, not yet implemented
**Depends on:** M0 (auth & accounts), shipped

---

## 1. What this milestone delivers

A user pastes a repository URL. The app clones it, splits it into chunks, embeds those
chunks, writes them to Qdrant, deletes the working copy, and tracks the whole thing as a
`Project` with a visible status. A second endpoint re-runs that pipeline on demand.

Concretely, at the end of M1:

- `POST /projects` creates a project and enqueues an ingestion job.
- A worker process performs clone → walk → chunk → embed → write, out of band.
- `GET /projects` and `GET /projects/{id}` report status, counts, and failure detail.
- `POST /projects/{id}/reindex` re-runs the pipeline, and is a no-op when one is already running.
- `DELETE /projects/{id}` soft-deletes the row and hard-deletes its vectors.

Not in M1: any retrieval or question-answering. Nothing reads from Qdrant yet — that is M2.
M1's job is to put correct, well-formed data there and to prove it got there.

---

## 2. Decisions that override the PRD

Two decisions taken during design contradict `docs/PRD.md` as currently written. Per
`.claude/rules/contradiction-halt.md` they were raised, the trade-offs stated, and the owner
decided. Per `.claude/rules/documentation.md` the affected documents are amended **in the same
change that implements this spec** — the list is §12 below.

### 2.1 Kafka replaces Redis + ARQ as the job queue

`docs/PRD.md:370` currently argues against this by name: *"Kafka is the wrong tool here — it is
a partitioned, replicated event log for high-throughput streams with replaying consumer groups;
this workload is a handful of jobs a day that need retries and a status field, which is a task
queue, not a log."*

**That technical reasoning stands and is not disputed by this spec.** The reasons it was
overridden are explicit and non-technical: the owner wants to learn event streaming, and
`docs/PRD.md` §1 names learning as the project's primary goal. Kafka was not on §1's list of
things to learn; it is being added to that list.

The costs are accepted knowingly, and this design mitigates each of them rather than pretending
they are absent:

| Cost | Mitigation in this design |
| --- | --- |
| No delayed-retry primitive | Retry-topic chain with partition pausing (§4.3) |
| No per-message ack/redelivery | Manual offset commit after completion (§4.1) |
| Rebalance can duplicate a long job | Pause-the-partition pattern plus a database lease (§4.1, §4.2) |
| Concurrency is partition count, not a setting | Cap enforced structurally as 2 partitions × 2 replicas (§3) |
| Head-of-line blocking within a partition | Accepted; documented; lever is more partitions (§3) |
| A broker on a shared single VPS | Single-node KRaft, replication factor 1, no HA (§3) |

**Head-of-line blocking is the one cost with no mitigation.** A twenty-minute index occupies its
partition for twenty minutes, and every project whose id hashes to that partition waits behind
it even while the other worker sits idle. A shared work queue would not do this. At the expected
volume it may never be noticed; if it is, the remedy is more partitions and more worker
replicas, which raises the concurrency cap in the same step.

### 2.2 Reindex returns `202`, not `409`, when a run is already in progress

`docs/PRD.md` §5.1 defines `409` as the code for "valid-but-wrong-state." Triggering a reindex
while one is already running fits that description, and `409` was the recommendation.

The owner chose an idempotent `202` instead, so the client has no error branch. The information
`409` would have carried is preserved in the response body rather than the status code: the
endpoint returns `ReindexResponse { enqueued: bool, project: ProjectResponse }`, so a caller can
still distinguish "I started one" from "one was already running" and render accordingly.

§5.1 gains a line recording that idempotent action endpoints follow this shape, so the next
reader does not file it as a deviation.

### 2.3 Decisions taken where the PRD deferred to the owner

`docs/PRD.md` §8 lists these as open and asks for a decision before M1:

- **Who can add projects** — *any authenticated user*, per §4.1's existing default. No `is_admin`
  check on `POST /projects`.
- **Private repos and shared PATs** — *full PAT support ships at M1*. This is accepted with §8's
  caveat intact: a PAT supplied by any user grants every user on the instance read access to that
  repository's contents through Q&A. Operators should scope PATs read-only and single-repo. This
  is an operator instruction, not an enforced constraint.

§8's remaining open questions (departed users' projects, eval rigour, key rotation) are
untouched by this milestone and stay open.

---

## 3. Topology

One Kafka message means one project indexed end to end by one consumer. The pipeline's internal
stages are separate, testable units, but they are not separate jobs — a chain of per-stage
topics would put a project's status behind three independently-failing consumers and leave the
scratch-directory lifecycle without a clear owner.

```
POST /projects ──> backend (producer)
                        │
                        ▼
              askrepo.ingest.requested   (2 partitions, key = project_id)
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
         worker-0             worker-1        ← same image as backend,
        (partition 0)        (partition 1)      different entrypoint
              │                   │
              └────────┬──────────┘
                       ▼
         Postgres (status)  +  Qdrant (points)
```

**Kafka** runs as a single broker in KRaft mode — no ZooKeeper. Internal topics are pinned to
replication factor 1, which a single-broker cluster requires in order to finish starting. One
broker means no replication and no failover; that is consistent with `docs/PRD.md` §2, which
rules out high availability, and the source of truth for a project's state is its Postgres row,
not the log.

**The worker** is the backend image with a different command. It shares `Settings`, the ORM
models, the repository layer, and the access resolver rather than growing a parallel copy.

**Concurrency.** `docs/PRD.md` §4.1 caps concurrent ingestion at 2. Here that is not a
configuration value but the topology itself: two partitions, one consumer each. It cannot be
exceeded by misconfiguration.

**Topics** are created explicitly at startup through the admin client, idempotently. Broker-side
auto-creation is disabled — it would silently produce a one-partition topic and quietly halve
the concurrency cap.

---

## 4. Delivery semantics

This section is the load-bearing one. Kafka gives at-least-once delivery and nothing stronger,
and the thing at risk is `Project.status`.

### 4.1 Long jobs must not trigger a rebalance

Kafka's group protocol treats a consumer that stops calling `poll()` as dead.
`max.poll.interval.ms` defaults to five minutes; indexing a real repository will exceed that
routinely. When it does, the broker evicts the worker, reassigns the partition, and the other
worker **begins indexing the same project while the first is still running** — two workers, one
scratch directory, one set of Qdrant points.

Raising `max.poll.interval.ms` to a large value is not the fix: it guesses at the slowest repo
anyone will ever index, and a genuinely hung worker then holds its partition for that entire
window.

**The pattern:**

1. Receive the message.
2. `pause()` the partition.
3. Run the job as a task.
4. Keep the poll loop running — a paused partition returns no records, so the loop spins at
   heartbeat cadence and the member stays alive indefinitely.
5. On completion, write status to Postgres, **then** commit the offset, **then** `resume()`.

`enable_auto_commit=False`. The offset moves only after the work is done and durable.

### 4.2 The database lease is the real deduplication boundary

The pause pattern removes the common cause of duplication; it does not make delivery
exactly-once. A worker that finishes and dies before committing will redeliver. A broker restart
can redeliver. So the worker never assumes it is alone — it claims the project with a
conditional write and believes the row, not the message:

Every enqueue mints a **`job_id`**, carried in the message and recorded on the project when that
job finishes. The claim gates on two things and nothing else: no live lease, and this job has
not already been done.

```sql
UPDATE projects
   SET lease_owner         = :worker_id,
       lease_expires_at    = now() + interval '5 minutes',
       status              = CASE WHEN status = 'ready' THEN 'ready' ELSE 'cloning' END,
       reindex_in_progress = (status = 'ready'),
       updated_at          = now()
 WHERE id = :project_id
   AND deleted_at IS NULL
   AND last_job_id IS DISTINCT FROM :job_id
   AND (lease_expires_at IS NULL OR lease_expires_at < now())
```

One row updated: we own it. Zero rows: another worker holds a live lease, or this exact job was
already completed — commit the offset and skip. This is the same race-safe conditional-update
shape already used for email uniqueness in commit `cb992c6`.

**Why the claim gates on the lease rather than on status.** A reindex leaves the project `ready`
throughout (§6.5), so a status-based `WHERE` could never claim one and every reindex would
deadlock on its first poll. But merely allowing `ready` to be claimed reintroduces duplicate
delivery from the other direction: once a finished job clears its lease, a redelivered message
would re-claim the now-`ready` project and start an unwanted reindex. `last_job_id` is what
distinguishes "a new reindex was requested" from "an old message arrived twice" — the lease
alone cannot tell them apart.

The `CASE` is what makes one statement serve both modes: a first index moves to `cloning`, while
a reindex stays `ready` and instead raises `reindex_in_progress`.

On terminal completion — success or failure — the worker clears `lease_owner` and
`lease_expires_at`, clears `reindex_in_progress`, sets `last_job_id` to the job it just
finished, and writes the final `status`.

A running job **renews its lease every 60 seconds**. That is what allows a five-minute expiry
rather than a thirty-minute one: a slow-but-healthy index keeps extending its claim, while a
worker that dies mid-clone releases its project for reclaim within five minutes.

`updated_at` is set explicitly in the `values()` because this is a bulk `UPDATE` and
`TimestampMixin.onupdate` does not fire on that path — see `.claude/rules/persistence.md`.

### 4.3 Delayed retry, built from topics

Kafka has no delayed delivery, so the delay is constructed:

```
askrepo.ingest.requested ──> askrepo.ingest.retry.1m ──> askrepo.ingest.retry.10m ──> askrepo.ingest.dlq
         ▲                            │                            │
         └────────── due ─────────────┴────────────────────────────┘
```

Each message carries headers: `attempt`, `not_before` (epoch ms), `original_topic`, and
`project_id`.

The retry consumer reads the head of its partition and checks `not_before`. If the message is
not yet due it **pauses the partition and sleeps until it is** — it does not commit, does not
seek past, and does not spin. This is correct precisely because every message in a fixed-delay
topic was appended in time order, so the partition head is always the earliest-due message in
that partition. When due, the consumer re-produces to the main topic and commits.

### 4.4 Not every failure is retryable

Spending three attempts and ten minutes on a URL that failed validation is waste, and it parks
the project in a misleading non-terminal state. The pipeline raises a two-branch taxonomy:

**`TerminalIngestionError`** — straight to `failed`, message scrubbed into `Project.error`,
offset committed, no retry:
- URL rejected by validation, or host not on the allowlist
- PAT rejected by the remote (401/403)
- Branch does not exist
- Repository exceeds the 500 MB cap
- Clone exceeds the 120 s timeout
- Embedding provider returns 401

**`RetryableIngestionError`** — enters the retry chain:
- Clone network failure
- Embedding provider timeout or 5xx
- Qdrant unreachable

An unexpected `Exception` is treated as retryable once and terminal thereafter, so a bug neither
silently eats jobs nor loops forever.

### 4.5 Closing the gap between the row and the message

`POST /projects` writes the row and then produces. If the produce fails, the row exists at
`pending` and no message does, and nothing will ever pick it up. The producer runs with
`enable_idempotence=True` and awaits acknowledgement, which narrows the window without closing
it.

Rather than a transactional outbox, each worker runs a **reconcile sweep every 60 seconds**:
re-produce any project that is `pending` and older than two minutes, or `cloning`/`indexing`
with an expired lease. Concurrent sweeps by both workers are safe — the lease claim already
deduplicates, so a duplicate message costs one skipped poll.

That same 60-second tick is where `docs/PRD.md` §5.1's other M1 promise lands: hard-deleting
revoked and expired `refresh_tokens` rows, which the PRD schedules for "M1, with the job
scheduler."

---

## 5. Ingestion safety

`docs/PRD.md` §9 names the clone URL as "the sharpest risk, and worse on an internal network
than a public one." `repo_url` is user-supplied input handed to a network client running inside
a network where `10.0.x.x` and `169.254.169.254` resolve.

### 5.1 Validation must survive DNS rebinding

§9 requires rejection "resolved at connect time, not just parse time." The obvious
implementation — parse, resolve, check the IP, then shell out to `git clone` — **does not
satisfy this.** Git performs its own lookup when it runs, so an attacker controlling DNS returns
a public address for the check and a private one for git a moment later.

The fix is to make git use the address that was validated:

```
resolve host → validate every A/AAAA record → pin the winner
git -c http.curloptResolve=github.com:443:140.82.121.4 clone --depth 1 ...
```

`http.curloptResolve` maps onto curl's `CURLOPT_RESOLVE`, so git performs no lookup of its own
and there is no second resolution to poison. **Every** returned record is validated, not just
the one selected — a host resolving to both a public and a private address is rejected rather
than raced.

Three related holes close in the same place:

- **Redirects.** curl follows them, and a redirect to an internal host resolves unpinned.
  `http.followRedirects=false`. The cost is that renamed repositories must be added by their
  canonical URL; the error message says so.
- **Userinfo smuggling.** `https://github.com@10.0.0.1/repo.git` reads as `github.com` to a
  naive string check. The allowlist test runs against `urlsplit(url).hostname`, which returns
  `10.0.0.1` here.
- **Interactive hangs.** A private repo with no PAT makes git block on a credential prompt
  forever, holding both its partition and its lease. `GIT_TERMINAL_PROMPT=0` and an empty
  `credential.helper` turn that into an immediate terminal failure.

Rejected ranges: loopback, RFC1918 private, link-local (including `169.254.169.254`),
carrier-grade NAT, and IPv6 equivalents (`::1`, `fc00::/7`, `fe80::/10`).

### 5.2 The PAT never appears in a command line

Injecting the PAT into the clone URL leaks it into `ps` output, into git's own error messages,
and from there into `Project.error`. Instead it is placed in the subprocess environment and read
by a one-line inline credential helper.

Everything written to `Project.error` passes through a scrubber first. Clone stderr is the most
likely place for a secret to surface, and `docs/PRD.md` §4.0 and §9 both require that no secret
reaches a log, traceback, or response.

PATs are encrypted at rest with Fernet, keyed from `PAT_ENCRYPTION_KEY`. Per §9 that key is
backed up **separately** from the database — a backup containing both is equivalent to storing
the PATs in plaintext.

### 5.3 Enforcing the caps

`--depth 1 --single-branch --branch <branch>` bounds history but not working-tree size. Rather
than trusting a host-specific API, the worker watches its own scratch directory: poll size every
second while the subprocess runs, kill it on crossing 500 MB, and kill it at 120 seconds
regardless. Both are terminal — retrying will not make the repository smaller.

### 5.4 The walk

`docs/PRD.md` §4.1 describes the pipeline as "walk → `.gitignore`-aware filter → chunk → embed."
Worth stating precisely, because a fresh clone has **already** applied `.gitignore` — ignored
files were never committed, so they are not present to filter. The filter that matters is:

- **Binary detection** by null-byte sniff of the first few KB, not by extension guessing.
- **A per-file size cap**, so a committed minified bundle or generated schema does not consume
  the whole indexing budget.
- **A path denylist** for committed-but-worthless content: `package-lock.json`, `*.min.js`,
  `vendor/`, committed `node_modules/`, `.git/`.
- **`.gitignore` is still read**, but only for the genuine edge case of files committed before a
  rule was added.

§4.1's wording is clarified accordingly (§12).

---

## 6. Chunking, embedding, and Qdrant

### 6.1 The constraint that shapes this section

`docs/PRD.md` §4.1 deletes the working copy after indexing. **The chunk text must therefore live
in the Qdrant payload** — there is no file to re-read at query time. Qdrant is the system of
record for code content, not merely an index over it, and payload size is a real storage
consideration.

`docs/PRD.md` §4.3's `Citation` is "file path + chunk id + line range," so **every chunk carries
true start and end line numbers.** Any splitter working in character offsets must map back to
lines.

### 6.2 Chunking

`RecursiveCharacterTextSplitter.from_language()` — LangChain's language-aware separator
splitting, already in `docs/PRD.md` §5's stack for exactly this purpose. It ships behind a
`Chunker` protocol.

The protocol matters more than the implementation: `docs/PRD.md` §7's M5 success criterion
requires that eval scores "meaningfully drop when chunking/prompting is deliberately made
worse," which presupposes chunking is swappable and measurable. Its known weakness — separator
matching has no model of nesting, so a function longer than the chunk size is cut mid-body — is
accepted at M1 and is the first thing M5's harness should be pointed at. AST-aware chunking via
tree-sitter is the identified upgrade path.

Each chunk carries `file_path`, `start_line`, `end_line`, `language`, `symbol` (enclosing
function or class where known), `commit_sha`, and `chunk_index`.

**Context header.** Before embedding, each chunk is prefixed with its file path and enclosing
symbol as a comment line. A bare `validate()` body embeds as generic validation code; the same
chunk headed `backend/app/core/repo_url.py — validate_repo_url` embeds as this project's URL
validation. It costs a few tokens per chunk and is among the highest-return changes available in
a RAG pipeline.

Point IDs are `uuid5(project_id, file_path, chunk_index)` — deterministic, so a rewrite
overwrites rather than duplicating.

### 6.3 The embedder adapter

```python
class Embedder(Protocol):
    model_id: str
    dimensions: int
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
```

Two methods, not one, deliberately: `nomic-embed-text` and `voyage-code-*` require task prefixes
(`search_document:` versus `search_query:`), and using the wrong one degrades retrieval silently
— no error, only worse answers. Encoding the distinction in the interface means an
implementation cannot forget it.

Implementations: `OllamaEmbedder`, `OpenAIEmbedder`, `VoyageEmbedder`, selected by config.

**Dimensions are probed at worker startup**, not configured — one embed of a fixed string, read
the length. A number kept in sync by hand is a number that will eventually be wrong.

Embedding is batched (`EMBEDDING_BATCH_SIZE`, default 64). Provider 5xx and timeouts are
retryable; 401 is terminal.

### 6.4 Collection naming solves the dimension problem

A Qdrant collection's vector size is fixed at creation. `nomic-embed-text` is 768 dimensions,
`text-embedding-3-small` is 1536, `voyage-code-3` is 1024. Changing `EMBEDDING_PROVIDER` against
a single fixed collection would make existing points unqueryable and cause Qdrant to reject the
writes outright.

So the collection is named for what is in it:

```
code_chunks__ollama__nomic_embed_text__768
code_chunks__openai__text_embedding_3_small__1536
```

Switching provider therefore targets a **different** collection rather than corrupting the
existing one. Old points remain valid if the provider is switched back.

`Project` records `embedding_collection` (where its points actually live — needed in order to
delete them) and `embedding_model` (for display, and for M6's comparison). A project whose
collection is no longer the active one is not silently queried against the wrong vector space;
it reports as needing a reindex.

This also makes M6's local-versus-hosted benchmark non-destructive: index the same repository
under both providers, both sets coexist, compare directly.

`project_id` gets a Qdrant payload index — filtering without one degrades to a scan as the
collection grows.

### 6.5 Reindex uses a generation swap

Points carry an `index_generation`. On reindex the worker writes the new generation, flips the
project's `active_generation` pointer, and only then deletes the old generation's points.

Two consequences, both wanted:

- **The project stays `ready` and answerable throughout.** Reindexing is routine — it happens
  after every push worth re-asking about — and taking the project offline for the duration would
  penalise exactly the person who wanted to query it.
- **A failed reindex leaves the working index intact.** The naive alternative, deleting before
  writing, means a reindex failing at the embedding stage destroys a working index and leaves
  the project `failed` with no vectors at all.

Because the project stays `ready` during a reindex, `status` cannot express "a run is in
progress." A separate `reindex_in_progress` flag carries that, and the lease claim in §4.2
accounts for it.

Transient double storage during the swap is accepted.

`DELETE /projects/{id}` soft-deletes the row and hard-deletes **all** generations' points for
that project, in the same operation — `docs/PRD.md` §5.1's soft-delete-does-not-reach-Qdrant
rule.

---

## 7. API surface

| Method | Path | Status | Notes |
| --- | --- | --- | --- |
| `GET` | `/projects` | 200 | Paginated via the shared `ListQuery`; scoped through `resolve_project_scope` |
| `GET` | `/projects/{id}` | 200 | Status, last indexed commit, file/chunk counts, error detail |
| `POST` | `/projects` | 201 | Any authenticated user; accepts `repoUrl`, `branch`, `pat?` |
| `POST` | `/projects/{id}/reindex` | 202 | `ReindexResponse { enqueued, project }`; `created_by` or admin, else 403 |
| `DELETE` | `/projects/{id}` | 204 | Soft-deletes the row, hard-deletes the Qdrant points |

**No `PATCH`.** `.claude/rules/router.md` lists five canonical CRUD routes, but every mutable
field on `Project` is derived by the pipeline — status, counts, commit SHA — and
`docs/PRD.md` §4.1 defines no user-editable attribute. The omission is deliberate.

**The `created_by`-or-admin gate lives in the service**, shared by `reindex` and `delete`, so it
cannot drift between the two routes (`.claude/rules/router.md` → "Destructive operations are
gated").

**The access resolver is wired even though it changes nothing today.**
`ProjectRepository.list()` accepts a `ProjectScope` and applies it; the route never filters. In
phase 1 the scope is `unrestricted` and the `WHERE` clause is absent, so behaviour is identical
to not having it — which is the entire point of `docs/PRD.md` §7's grep criterion, and the only
reason phase 2 is a body change to one function.

**The reindex skip has two layers, and only one is load-bearing.** The service refuses to
produce when status is `pending`/`cloning`/`indexing` or `reindex_in_progress` is set — a fast
path, not a correctness boundary. Two simultaneous clicks both pass that check and both produce;
the worker's lease claim (§4.2) settles it. This split is stated explicitly so that nobody later
removes the worker-side lease on the grounds that the service already checks.

**No force-override on reindex.** A project with a live lease is either running or its worker
died, and the reconcile sweep reclaims the dead case within five minutes. A force flag would
allow a second index against a directory another worker is still writing to.

**No rate limit on reindex.** After the first call the status short-circuits every subsequent
one before Kafka is touched.

### 7.1 Status machine

```
              ┌────────── reindex (generation swap, stays queryable) ──────────┐
              │                                                                 │
  pending ──> cloning ──> indexing ──> ready ────────────────────────────────> ready
     │           │            │
     │           ▼            ▼
     └───────> failed <───────┘      terminal errors, or retries exhausted
                 │
                 └──> reindex allowed (no live lease)
```

---

## 8. Schema changes

Additions to `Project` beyond `docs/PRD.md` §4.1's declared schema. All are amendments to the
PRD (§12).

| Column | Type | Why |
| --- | --- | --- |
| `lease_owner` | `str \| None` | Which worker holds the claim (§4.2) |
| `lease_expires_at` | `datetime \| None` | Reclaim after a worker dies (§4.2) |
| `last_job_id` | `UUID \| None` | Distinguishes a new reindex from a redelivered message (§4.2) |
| `reindex_in_progress` | `bool` | A run is active while status stays `ready` (§6.5) |
| `active_generation` | `int` | Which Qdrant generation serves queries (§6.5) |
| `embedding_collection` | `str \| None` | Where this project's points live (§6.4) |
| `embedding_model` | `str \| None` | Display, and M6's comparison (§6.4) |

`Project` carries `TimestampMixin` and `SoftDeleteMixin`. Migration is a hand-written Alembic
revision with a working `downgrade()`, per `.claude/rules/persistence.md`.

---

## 9. Configuration

New `Settings` fields. Every one gets a matching entry in `backend/.env.example` — a setting
with no example entry is undiscoverable (`.claude/rules/documentation.md`).

```
# Kafka
KAFKA_BOOTSTRAP_SERVERS=kafka:9092
KAFKA_INGEST_TOPIC=askrepo.ingest.requested
KAFKA_CONSUMER_GROUP=askrepo-ingest
KAFKA_INGEST_PARTITIONS=2
KAFKA_MAX_ATTEMPTS=3

# Embedding
EMBEDDING_PROVIDER=ollama          # ollama | openai | voyage
EMBEDDING_MODEL=nomic-embed-text
EMBEDDING_BASE_URL=http://ollama:11434
EMBEDDING_API_KEY=
EMBEDDING_BATCH_SIZE=64

# Ingestion
REPO_HOST_ALLOWLIST=["github.com","gitlab.com"]
CLONE_TIMEOUT_SECONDS=120
REPO_MAX_SIZE_MB=500
REPO_SCRATCH_DIR=/data/repos
CHUNK_SIZE=1200
CHUNK_OVERLAP=150
MAX_INDEXED_FILE_BYTES=1048576

# Secrets
PAT_ENCRYPTION_KEY=
```

`PAT_ENCRYPTION_KEY` joins `SECRET_KEY` in `Settings._reject_development_defaults_in_production`
— an unset or placeholder key must refuse to boot under `APP_ENV=production`, because PATs
encrypted with a known key are not encrypted.

---

## 10. Testing

**Unit, no infrastructure** — the bulk of it, and why the stages sit behind protocols:

- `repo_url` validation: DNS rebinding (resolver returns public, then private), userinfo
  smuggling, non-https schemes, off-allowlist hosts, every rejected range, and a host resolving
  to mixed public and private records.
- The scrubber: a PAT appearing in clone stderr never reaches `Project.error`.
- The chunker: **line ranges are correct** — every citation at M2 and M4 depends on them.
- Retry classification: each error type lands terminal or retryable as intended.

**Against real Postgres**, per `.claude/rules/persistence.md` (migrations, never `create_all`):

- The lease claim under concurrency: two simultaneous claims, exactly one row updated, exactly
  one winner. This is the test that proves the duplicate-delivery guard holds.
- Expired-lease reclaim, and the reconcile sweep picking up a stranded `pending`.

**Access tests `docs/PRD.md` §7 requires by name:**

- User B lists and reads a project user A created — succeeds.
- User B reindexes or deletes it — `403`. An admin — succeeds.

**Kafka in tests.** Services depend on a narrow `IngestionQueue` protocol with a Kafka
implementation and an in-memory fake, so service and route tests need no broker. One integration
test exercises the real consumer loop, specifically the pause-during-long-job path, which cannot
be verified any other way. Integration tests carry `@pytest.mark.integration`, stay out of
`make check`, and run via a new `make test-integration` with infra up. Otherwise CI needs a
broker in order to lint a docstring.

---

## 11. Infrastructure changes

- **`kafka`** service: single-node KRaft, internal topics at replication factor 1, **not**
  published to the host beyond what local development needs.
- **`worker`** service: backend image, worker entrypoint, 2 replicas.
- **`ollama`** service: behind a Compose profile, **enabled by default in `make up`** to match
  §9's default of `EMBEDDING_PROVIDER=ollama`. An instance configured for a hosted provider drops
  the profile and does not pay for a model server it never calls. The profile must default to on,
  or the shipped default configuration would point at a service that was never started.
- `backend` gains the producer; `/health/ready` gains a broker check.

---

## 12. Documentation amendments — part of this change, not a follow-up

`.claude/rules/documentation.md` requires these in the same change as the code.

| Document | Change |
| --- | --- |
| `docs/PRD.md` §1 | Add event streaming to the stated learning goals |
| `docs/PRD.md` §4.1 | `Project` schema gains seven columns (§8); clarify the walk's filter (§5.4) |
| `docs/PRD.md` §5 | Stack table: background jobs → Kafka; rate-limiting row no longer claims Redis backs the job queue |
| `docs/PRD.md` §5 | Rewrite the "On the job queue" note — it currently argues against Kafka by name |
| `docs/PRD.md` §5.1 | Record that idempotent action endpoints return `202` with an outcome flag rather than `409` (§2.2) |
| `docs/PRD.md` §6 | M1 no longer "moves jobs to Redis + ARQ" |
| `docs/PRD.md` §8 | Mark "who can add projects" and the PAT question as decided (§2.3) |
| `CLAUDE.md` | Status banner → M1; job queue is Kafka, not ARQ; Qdrant is now read; new rule/route counts kept exact |
| `backend/README.md` | Route table gains the five project routes; new config values; worker command |
| `backend/.env.example` | Every field in §9; correct the `REDIS_URL` comment, which currently promises the ARQ queue |
| `infra/docker-compose.yml` | Header comment's service and port list must match the new services |
| `README.md` | Roadmap: tick M1; service table gains Kafka and the worker |
| `SECURITY.md` | New operator secret (`PAT_ENCRYPTION_KEY`, backed up separately from the database); new service in the deployment |
| `.claude/rules/` | A new rule covering the ingestion pipeline and queue conventions, since M1 establishes a pattern that has none |

---

## 13. Out of scope for M1

Retrieval and question-answering (M2). Webhook-driven auto-reindex, multi-branch indexing, and
deploy keys — all listed out of scope by `docs/PRD.md` §4.1. AST-aware chunking (identified
upgrade path, §6.2). Any frontend: the reindex button is a client for the endpoint this
milestone ships, and lands whenever the frontend does.
