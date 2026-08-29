---
paths:
  - "backend/app/ingestion/**/*.py"
  - "backend/app/queue/**/*.py"
  - "backend/app/worker.py"
---

# Ingestion & Queue Rules

M1 established a handful of patterns that look like over-engineering until the thing they
prevent happens in production. Each rule below states what the pattern is, what breaks without
it, and what the tempting-but-wrong simplification looks like — because the risk here is not
someone writing these badly, it is someone removing them on purpose.

The design reasoning lives in `docs/superpowers/specs/2026-08-25-m1-project-ingestion-design.md`;
the decision to use Kafka at all, and its accepted costs, is `docs/PRD.md` §5.

## The database lease is the deduplication boundary

Kafka delivers **at least once**. The same job arrives twice for ordinary reasons: a rebalance
redelivers an uncommitted offset, a reconcile sweep re-enqueues a job whose produce it could not
confirm, a retry lands while a fresh reindex is already queued.

What stops two workers indexing the same project is a lease on the project row —
`ProjectRepository.claim`, gating on `lease_expires_at` and `last_job_id`. Not the offset, not
the partition key, not the service's busy check.

- **The service-level "already running?" check is a fast path**, there so the API can answer
  nicely. Removing the lease because "the service already checks" is a defect. The service check
  runs in the API process against a different session at a different time; it cannot serialise
  two workers.
- **The partition key does not deduplicate either.** Keying by `project_id` orders a project's
  messages *within one topic*. The retry ladder crosses topics, so a queued retry and a fresh
  reindex can be delivered simultaneously on different partitions.
- A duplicate delivery must stay **cheap** — one refused claim. That is what licenses the
  consumer to absorb an error and leave the offset uncommitted.

## Long jobs pause their partitions and keep polling

aiokafka measures liveness as *fetcher idle time*: go longer than `max.poll.interval.ms` without
calling `getmany` and the client leaves the group by itself. An index can run for twenty minutes.

So a consumer running a long job pauses every assigned partition and **keeps polling for the
duration**. Each poll returns nothing and holds the member's seat.

- **Pause every assigned partition, not just the one being worked.** A keep-alive poll discards
  what it returns, so an unpaused sibling has its jobs read and thrown away — silently lost, not
  redelivered.
- **Re-apply the pause on every tick.** A rebalance rebuilds per-partition state un-paused.
  `_RepauseOnRebalance` closes that window properly; the per-tick re-pause is the backstop.
- **Raising `max.poll.interval.ms` is not an acceptable substitute**, and there is deliberately
  no `Settings` field for it. A documented knob is an invitation to reach for it. The one seam
  that exists — `IngestionConsumer._build_consumer(**overrides)` — is there so the integration
  test can shorten the interval enough to observe an eviction, and for nothing else.
- The same pattern serves the retry ladder. Kafka has no delay primitive, so `RetryConsumer`
  holds the partition head until it is due. **It must not `sleep` through the delay** — the
  longest rung is ten minutes against a five-minute default interval, so sleeping would get the
  member evicted on every long retry.

## Commit after the work, and commit one partition

The offset moves only once the job is done and its outcome is durable, and a commit names the
partition and offset explicitly.

- **Never commit before producing or completing.** An offset committed early acknowledges work
  that never happened; the job is simply gone.
- **Never call a bare `commit()`.** It advances every assigned partition to its current position,
  acknowledging messages this consumer has not handled.
- Losing a partition mid-job is normal. `resume` and `commit` both raise for a partition no
  longer assigned, and letting either escape a `finally` ends the polling loop for every other
  job on that worker. Catch it, log it, and let the record be redelivered — the lease makes that
  safe.

## Every failure is classified

Every exception leaving the pipeline is either `TerminalIngestionError` (do not retry — a bad
URL, a repo over the size cap, an unsupported branch) or `RetryableIngestionError` (a network
blip, a broker hiccup, a temporarily unreachable embedder).

An **unclassified** exception is treated as retryable exactly once and then dead-lettered, so a
bug neither silently eats jobs nor loops forever. That default is a safety net, not a design:
reaching it means a failure mode nobody classified, and the fix is to classify it — not to widen
the net.

A terminal failure is recorded on the project before the outcome is decided; a retryable one is
not, because the job is coming back and a `failed` status would lie about it.

## Chunk line ranges are load-bearing

Every chunk carries the file path and the start/end line it came from. **Citations are the
product** — an answer that cannot point at a file and a line is not grounded, it is a guess. Any
change to the chunker must preserve exact line attribution, including for the overlap region.
A chunker that returns text without a verifiable range is broken even if retrieval scores well.

## The collection name carries provider, model, and dimensions

Collections are named by `collection_name(provider=, model=, dimensions=)`, and the width is
**probed at worker startup**, never declared in config.

- **Never hardcode a collection name**, and never assume a dimension. A model swap that reuses a
  collection mixes incompatible vectors, and the failure is silently degraded retrieval rather
  than an error.
- Each project records the collection it wrote to, which is how `DELETE /projects/{id}` finds its
  points. Deriving the collection at delete time from current settings would miss points written
  under a previous model.

## Reindex is a generation swap

New vectors are written under an incremented `active_generation`; the project switches to reading
it only on success; the old generation is deleted afterwards.

The project stays `ready` and queryable throughout, and **a reindex that fails part-way leaves
the previous index intact and serving**. Do not "simplify" this into delete-then-rebuild: that
takes a working project offline for the length of a clone-and-embed, and loses it entirely if the
run fails.

## Soft delete does not reach Qdrant

Postgres rows soft-delete; the matching Qdrant points **hard-delete, in the same operation**.
Vector points have no `deleted_at`, and a query-time filter would be one forgotten call away
from serving deleted content. See `persistence.md`.

## Nothing derived from clone output is stored or logged unscrubbed

A PAT is embedded in the clone URL, so it can surface in git's stderr, an exception message, or a
traceback. Everything on that path goes through `scrub` (`app/core/crypto.py`) before it reaches
`Project.error` or a log line — `docs/PRD.md` §9: a token must not survive into anything an
operator can read.

Where a layer holds no PAT and so cannot scrub one out of an arbitrary exception — the consumer,
for instance — record the exception's **class name** rather than its message, and let the text go
only to the log.

## Testing

- Unit tests use `InMemoryIngestionQueue` and `tests/fakes.FakeConsumer`; they never need a
  broker. `FakeConsumer` encodes aiokafka's real pause/commit rules — extend it rather than
  writing a second stand-in.
- Anything requiring a real broker goes behind the `integration` marker, which `make check`
  excludes. Keep that set as small as it can be: right now it is the properties a fake would only
  assert our own assumptions back at us — eviction, redelivery, and rejoin.
- When a test claims to prove a safety property, **check that it fails when the property is
  removed.** Several of these mechanisms are invisible to the obvious assertion: an eviction
  mid-job does not produce a second run, because the lease refuses the redelivery. A test that
  cannot fail is documentation with a green tick.
