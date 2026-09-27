# Live Events Rules

Everything under `app/live/` (`kinds.py`, `events.py`, `staging.py`, `fanout.py`, `bus.py`,
`kafka.py`), `app/api/routes/events.py`, `live_event_visible_to` in `app/core/access.py`, the
staging call sites in `ProjectRepository`, `ChecklistModuleRepository`,
`MockDataDatasetRepository`, `ProjectService`, `ChecklistModuleService`,
`MockDataDatasetService`, `ChecklistChangeSetService`/`MockDataChangeSetService`, and
`NotificationFanout._write`, plus `frontend/components/live/`, `frontend/lib/live/` and
`frontend/hooks/use-live-events.ts`. Read `notifications.md` alongside this — the two systems
share a shape (stage inside a transaction, decide who through one resolver) and diverge on
purpose in exactly the places called out below.

Design: `docs/superpowers/specs/2026-09-27-live-updates-design.md`.
Intent: `docs/PRD.md` §2.1, Phase 2.3 amendment (GitHub issue #48).

Every invariant here fails **silently** when broken — no exception, no failing request, just a
screen that goes stale until the next poll, or worse, an event describing a project the caller
was never given. That is what makes these rules rather than preferences.

## 1. Events are ids, never content

`LiveEvent` carries `kind`, `id`, `projectId` and, for a `notification` event only,
`recipients` — never a project name, a module name, a status value, or notification text. The
browser payloads (`ready`, `invalidate {kind, id, projectId}`, `resync`) carry the same shape:
an `id` to key a refetch on, nothing to render directly.

The reason is not caution for its own sake. A client refetches through the same REST routes it
already polls, whose `404`/`403` rules are what actually decide what the caller may see
(`.claude/rules/response-api.md`). An event that carried a display name would be a second,
unchecked channel for exactly the content those routes exist to gate — a private repository's
name reaching a stream the access re-check (rule 4) had not yet had the chance to refuse.
Widening `LiveEvent` to carry a label is the same mistake `.claude/rules/mail.md` calls out for
the composer's signature: the fix for "the frontend has to make an extra request" is never "let
this one channel skip the check that everything else goes through."

## 2. Stage, never publish directly

`stage_live_event(session, event)` appends to a list on `session.info`; nothing calls a
publisher directly. A SQLAlchemy `after_commit` hook hands the staged list to the process's
`LivePublisher` and clears it; `after_transaction_end` discards whatever is left once the
outermost transaction ends — a rollback, or a close — with no publish at all. A savepoint ending
is not the outermost transaction ending (`transaction.parent is not None`), so a nested rollback
cannot drop events staged before it opened.

This is the mechanism, not a convention a call site has to get right by hand. Publishing after a
`session.commit()` line by hand is one `await` away from publishing an event whose transaction
then fails for an unrelated reason later in the same request, or from being skipped entirely on
a code path that returns early. Because the commit hook is what fires the publish, a rolled-back
change is *structurally* incapable of announcing itself — the same property
`.claude/rules/notifications.md` rule 2 gets from staging the fan-out write inside the
transaction, arrived at from the opposite direction: notifications commit *with* the row they
describe; live events leave only *after* the commit that made them true, because there is
nothing in Kafka to roll back once a message is sent. A direct publish from a service is a
defect even on the one call path where its ordering happens to be correct — the next person to
copy that call site will not be so lucky, and nothing will tell them.

## 3. Every state write the frontend displays stages an event

A project's status, lease, reindex flag or soft delete; a checklist module's or mock-data
dataset's claim, release, `mark_in_review`, `defer`, `claim_stranded`, the service write that
moves it to `generating`, and the apply/discard that returns it; a notification fan-out —
each of these stages exactly one `LiveEvent` of the right kind and id, in the repository or
service method that writes the state, never in a route (the same layering
`.claude/rules/router.md` requires for everything else a route touches).

`tests/test_live_event_sites.py` pins the sites that exist today. A new status write the
frontend polls for is not finished until it stages an event here too — the failure mode of
skipping it is not a test failure, it is a screen that only ever updates on its own poll
interval, which looks like it works until someone opens a second tab.

## 4. Visibility is decided by `live_event_visible_to`, re-checked per event, with no admin bypass

`app/core/access.py` is the one place read scoping happens (`docs/PRD.md` §7,
`tests/test_scoping_is_single_point.py`), and `live_event_visible_to` is that decision asked
for a stream instead of a request: a `notification` event is visible only to a user id in its
`recipients`; every other kind follows `resolve_project_scope(user)`, unrestricted for an
administrator. Forwarding a project-scoped event to someone outside that scope, or inventing a
second visibility check in `app/api/routes/events.py` or in `LiveEventHub`, is the same defect
`.claude/rules/notifications.md` rule 1 names for a second recipient resolver — it can drift
from the one the rest of the app trusts, and here drift means a stream naming a project id to
someone who holds no membership on it.

**Re-checked per event, not decided once at connect.** The stream reloads the caller through
`load_authenticated_user` (grants via the grant cache, falling back to Postgres) before
forwarding a project-scoped event, and again on every heartbeat. A revoked membership stops that
project's events from the next event on; a deactivated account, a `must_change_password` flag,
or a signed-out/revoked session (the caller's own refresh-token family, via
`RefreshTokenRepository.family_is_live`) closes the stream within one heartbeat interval. The
access token's own expiry is irrelevant to this — the re-check, not the token, is what keeps a
long-lived stream honest.

**Bounded so it cannot become its own outage.** Every open stream in a process can re-check at
once — the pool is small — so `app/live/stream.py` caps concurrent re-checks at
`_RECHECK_CONCURRENCY` (4) with a module-level semaphore, and reuses a successful re-check for
`_RECHECK_REUSE_SECONDS` (2 seconds): an event or heartbeat due inside that window sees the
already-checked user rather than opening a second session. A re-check that raises is logged and
treated as "closed" rather than propagating out of the generator — one flaky check costs one
client a reconnect, not the request.

**No administrator bypass for a `notification` event**, matching
`.claude/rules/notifications.md` rule 5: `require_permission` lets an administrator through
every other check, and giving `live_event_visible_to` the same bypass for notifications would
turn permission to see a project into interest in hearing about it — the exact symmetry that
rule refuses. An administrator does receive every project's `invalidate`s (ids only, and admin
screens already list every project), which is not the same thing.

## 5. The stream is a hint — every screen it serves must still update by polling

`GET /events` answers `503 LIVE_EVENTS_UNAVAILABLE` when `LIVE_EVENTS_ENABLED` is off or the hub
has no broker connection, and nothing else changes. "No broker connection" has to be noticed by
hand — a group-less consumer raises nothing when the broker drops — so `KafkaLiveEventHub` runs a
metadata round trip every `_HEALTH_CHECK_SECONDS` (10) and, on any loss, marks itself unavailable
and ends every open stream (`close_all`), so each client reconnects into the `503` rather than
sitting "connected" to a hub that will never deliver; a reconnect sends every stream a `resync`,
since what was published during the gap is gone. Beyond that: `LiveEventsProvider` backs off and retries,
and every hook it would otherwise quiet down keeps its unconnected interval. A published event
can also simply never arrive — a process that commits and dies before its publish, a full
per-connection queue collapsed to one `resync` marker, a broker that drops a message Kafka
delivered at most once here (there is no consumer group, no offset, and nothing replays). None
of these are failures to fix; they are the reason every job hook still polls every 60 seconds
while connected (5 minutes for the bell) instead of stopping, and why a screen must never be
written so that it *only* updates from an `invalidate`.

Treat "the stream will tell me" as a latency improvement over polling, never as a replacement
for it. A screen that regresses to polling-only behavior when `/events` is unavailable is
correct; a screen that goes silent is a bug, and it is the kind of bug rule 3 exists to catch
before it ships, not after a proxy in front of the instance starts buffering SSE.
