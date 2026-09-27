# Live updates — job status and the bell over one per-user stream: Design

**Date:** 2026-09-27
**Intent:** GitHub issue #48; `docs/PRD.md` §2.1 Phase 2.3 (amended by this change)
**Depends on:** M1 ingestion, M4/M5 generation, Phase 2.1 access, Phase 2.3 notifications
**Milestone placement:** an unnumbered amendment line in `docs/PRD.md` §6, like the profile page

---

## 0. What this document covers

Several screens learn about background work by polling. The project list and detail, a
checklist module and a mock dataset poll every 3 s while a job is moving; the bell polls every
60 s. A reindex or a generation runs for minutes, so an open tab issues dozens to hundreds of
requests per job, and each state change reaches the screen up to one interval late.

This change pushes a signal instead. The worker (or the API) commits a state change, publishes
a small event to Kafka after the commit, every API process's consumer receives it, and each
open browser stream it is visible to receives an `invalidate`. The browser then refetches the
same REST routes it polls today. Polling stays as the fallback.

What is **not** in scope: pushing content (the stream carries ids only); a WebSocket; pushing
anything for the Ask screen or refinement chats, which already stream; per-user notification
*content* over the stream; a delivery guarantee — the stream is a hint.

### 0.1 The decisions, made

1. **Scope: job status and the bell.** Project status and reindex, checklist generation, mock-data
   generation, and new notifications all travel on one stream. This amends PRD §2.1's
   "deliberately no socket" (§0.2).
2. **Transport: Kafka.** A new topic, `askrepo.live.events`. Each API process runs one consumer
   with no consumer group, assigns itself every partition, reads from the end, and fans out in
   memory to that process's open streams. The issue's objection — "a per-connection consumer
   group is heavy" — applies to a group per browser connection, which this design does not use.
   Kafka was chosen over Redis pub/sub so that `CLAUDE.md`'s "Redis has exactly two readers"
   stays true, and because `docs/PRD.md` §1/§2 name event streaming as a learning goal.
3. **Events are hints, never content.** A browser receives `{kind, id, projectId}` and
   refetches through REST, whose `404`/`403` rules still decide what it sees.
4. **Publish only on commit, by construction.** State-changing code *stages* an event on the
   session; a SQLAlchemy `after_commit` hook publishes staged events and `after_rollback`
   discards them. No call site orders a publish against a commit by hand.
5. **Access is re-checked per event.** Before a project-scoped event is forwarded, the stream
   reloads the user's grants through the grant cache and asks `app/core/access.py` whether the
   event is visible. The user row is re-read on every heartbeat, so deactivation closes a quiet
   stream within one heartbeat interval.
6. **Polling becomes the fallback.** Connected, job hooks keep a 60 s safety poll while a job
   moves and the bell polls every 5 min; disconnected, today's intervals apply unchanged.
7. **Fail open to polling.** No Kafka connection, or `LIVE_EVENTS_ENABLED=false`, means
   `GET /events` answers `503 LIVE_EVENTS_UNAVAILABLE` and every client polls as it does today.

### 0.2 Amendments to `docs/PRD.md` and the rules, made in the implementation change

- **§2.1 Phase 2.3** — "In-app delivery is a polled unread count at 60 seconds, and deliberately
  no socket" is amended: the per-user stream now exists for job status, with its own failure
  handling (§4, §5), so the bell rides it rather than a second mechanism; the 60 s poll becomes
  the fallback when the stream is unavailable. The objection the original text raised — a
  per-user stream has a different lifecycle and failure modes from the answer stream — is
  answered by §4.4 and §5.3, not dismissed.
- **§5** — the Kafka topic list gains `askrepo.live.events`, and the architecture notes the
  API process now consumes as well as produces.
- **§6** — an unnumbered amendment line pointing at §2.1.
- **New rule `.claude/rules/live-events.md`** — the invariants in §7 of this document.
  `CLAUDE.md`'s rule count goes from sixteen to seventeen.
- **`.claude/rules/notifications.md`** — the fan-out also stages a live event.
- **`.claude/rules/frontend-bff.md`** — the catch-all pipes any `text/event-stream` unbuffered
  and forwards the request's abort signal.

### 0.3 The constraints that are not negotiable

- **No content on the stream.** No project name, module name, notification text, or status
  value — only kind, id, and project id.
- **Visibility is decided in `app/core/access.py` and nowhere else**, and the single-point grep
  test covers the new function.
- **A rolled-back change never announces itself.**
- **The app works with the stream absent.** Every screen that goes live must still update by
  polling when `/events` is unavailable.

---

## 1. The event

### 1.1 Internal message (Kafka)

```json
{
  "kind": "project" | "checklist_module" | "mock_data" | "notification",
  "id": "<uuid>",
  "projectId": "<uuid> | null",
  "recipients": ["<user uuid>", "..."]
}
```

- `kind` names what changed; `id` names the row the frontend keys its queries on:
  - `project` — the project id.
  - `checklist_module` — the module id.
  - `mock_data` — the **checklist module** id the dataset belongs to, because the frontend keys
    mock data by module (`keys.mockData.detail(moduleId)`).
  - `notification` — the `notification_events` row id.
- `projectId` is the project the row belongs to. It is what visibility checks for every kind
  except `notification`, whose visibility is `recipients` alone; a notification event still
  carries its event's project id (every current notification type has one), but nothing
  decides on it.
- `recipients` is set **only** for `notification`, holding the user ids the fan-out resolved.
  It never reaches a browser.

A pydantic model, `LiveEvent`, in `app/live/events.py`, owns this shape and its serialization.

### 1.2 Browser payload (SSE)

| Event | Payload | Meaning |
| --- | --- | --- |
| `ready` | `{}` | The stream is open. Sent first, and first again after every reconnect. The client refetches everything live. |
| `invalidate` | `{kind, id, projectId}` | This row changed; refetch its queries. |
| `resync` | `{}` | Events were dropped for this connection; refetch everything live. |
| `: ping` | comment line | Every `LIVE_EVENTS_HEARTBEAT_SECONDS`; keeps proxies from idling the stream out. |

`ReadyEvent`, `InvalidateEvent` and `ResyncEvent` inherit `ApiModel` and are added to
`SSE_EVENT_MODELS`, which is the only enforcement an SSE payload gets
(`tests/test_api_model.py`).

---

## 2. Producing events

### 2.1 Stage, don't publish

```python
def stage_live_event(session: AsyncSession, event: LiveEvent) -> None:
    """Queue an event to publish if, and only if, this session's transaction commits."""
```

- Appends to a list in `session.info`.
- `after_commit` on the sync session hands the list to the process's `LiveEventPublisher`
  (scheduling the async publish on the running loop) and clears it.
- `after_rollback` clears it.
- Duplicate `(kind, id)` pairs within one transaction collapse to one event.

This mirrors what notifications already guarantee — the announcement commits with the state it
describes — from the other side: notifications write *inside* the transaction; live events
leave only *after* it.

### 2.2 Where events are staged

In the repository or service method that writes the state, never in a route:

| Kind | Sites |
| --- | --- |
| `project` | `ProjectRepository`: create, `claim`, `set_status`, `release`, `abandon`, raising the reindex flag, soft delete |
| `checklist_module` | `ChecklistModuleRepository`: `claim`, `release`, `mark_in_review`, `defer`, `claim_stranded`; the service write that moves a module to `generating` on request, and the apply/discard that returns it |
| `mock_data` | `MockDataDatasetRepository`: the same set as the module; the service writes on request and on apply/discard |
| `notification` | `NotificationFanout._write` — one event per fan-out (`raise_event` and `raise_direct`), carrying the resolved recipients |

`tests/test_live_event_staging.py` asserts, per site, that the write stages exactly one event
of the right kind and id. A new status write without staging is caught by the rule and by
review; the test pins the ones that exist.

### 2.3 The publisher

`LiveEventPublisher` wraps the existing aiokafka producer (`app/queue/producer.py`) in both the
API and the worker.

- **Best-effort, never raises.** On failure it logs at `WARNING` — kind and id only — and
  returns. A lost event costs a delayed screen update, never a failed action: the same trade
  `AuditRecorder` makes, for the same reason.
- **Accepted gap, stated rather than hidden:** a process that commits and dies before its
  publish sends nothing. The safety poll (§5.2) is what recovers it.

### 2.4 The topic

`askrepo.live.events`, created idempotently by `ensure_topics` beside the job topics: one
partition, `retention.ms` of one hour. Ordering across kinds does not matter, and nothing reads
history — the consumer starts at the end.

---

## 3. Receiving events: `LiveEventHub`

One per API process, started and stopped in the FastAPI lifespan.

- **Consumer:** aiokafka `AIOKafkaConsumer` with **no `group_id`**, `assign()`ed every partition
  of the topic, `seek_to_end()` on start. No rebalances, no offset commits. The pause-and-poll
  rule in `CLAUDE.md` concerns group members holding a seat through a long job; a group-less
  consumer that polls continuously has no seat to lose.
- **Fan-out:** each open stream registers a bounded `asyncio.Queue` (a module constant,
  `QUEUE_SIZE = 100`, not a setting). A message goes to every registered queue. A
  full queue is drained and given a single `resync` marker instead of an unbounded backlog.
- **Availability:** `hub.available` is `False` until the consumer has connected, and whenever
  it loses the broker. A background task retries with backoff. `LIVE_EVENTS_ENABLED=false`
  never starts the consumer.
- **Test double:** `InMemoryLiveEventBus` implements both the publisher and the hub interface,
  so route, service and staging tests run with no broker (the same pattern as
  `InMemoryIngestionQueue`). One real-Kafka round trip sits behind the `integration` marker.

---

## 4. The endpoint: `GET /events`

### 4.1 Route and pre-flight

`app/api/routes/events.py`, `router = APIRouter(prefix="/events", tags=["Live events"])`,
behind `CurrentUser` and the forced-password-change gate (`/events` is **not** added to
`GATE_EXEMPT_PREFIXES`). The pre-flight/stream split from `.claude/rules/rag.md` applies:
everything that needs a status code happens before the first byte.

| Status | When |
| --- | --- |
| `401` | No or invalid token |
| `403 PASSWORD_CHANGE_REQUIRED` | The middleware gate |
| `503 LIVE_EVENTS_UNAVAILABLE` | `LIVE_EVENTS_ENABLED` is off, or `hub.available` is false |
| `200` `text/event-stream` | Otherwise |

`LIVE_EVENTS_UNAVAILABLE` is a new `ErrorCode`. Headers match the answer stream:
`Cache-Control: no-cache`, `X-Accel-Buffering: no`.

### 4.2 Visibility — in `app/core/access.py`

```python
def live_event_visible_to(user: AuthenticatedUser, event: LiveEvent) -> bool:
```

- `notification`: `user.id in event.recipients`.
- every other kind: `event.project_id` is in `resolve_project_scope(user)` (unrestricted for an
  administrator).

An administrator therefore receives every project's invalidations — ids only, and admin
screens already list every project — but only the notifications they are a recipient of, so
`.claude/rules/notifications.md` rule 5 ("an administrator with no membership receives
nothing") is untouched.

### 4.3 Per-event re-check

The middleware's user-and-grants loading is extracted into a reusable
`load_authenticated_user(session, user_id, session_id)` in `app/core/middleware.py`, and the
middleware calls it.

- Before forwarding a project-scoped event, the stream opens a session from the sessionmaker,
  reloads the user through `load_authenticated_user` (grants via the grant cache, falling back
  to Postgres), and calls `live_event_visible_to`. Invisible events are dropped silently.
- On every heartbeat the user row is re-read. If the user is gone (deactivated) or
  `must_change_password` is set, the stream closes.
- The stream uses its **own** sessions from the sessionmaker, never the request-scoped one, for
  the reason `.claude/rules/rag.md` gives for the answer stream.

Consequences: a revoked membership stops that project's events from the next event on;
deactivation ends a quiet stream within one heartbeat; the access token expiring mid-stream is
harmless, because the re-check — not the token — is what keeps the stream honest.

### 4.4 Lifetime

- `ready` first.
- Events and heartbeats until: the client disconnects (`CancelledError`, cleanup in `finally`
  unregisters the queue), the user fails a re-check, or `LIVE_EVENTS_MAX_STREAM_MINUTES`
  elapses — a cap so one connection cannot pin a process indefinitely. The client reconnects.

### 4.5 The BFF

`forward()` in `frontend/app/api/[...path]/route.ts` passes `signal: request.signal` to `fetch`,
so a closed tab aborts the backend stream at once rather than leaving it to fail on the next
heartbeat write. Refresh on the `401` status line and unbuffered relay already work for a `GET`
stream.

---

## 5. Frontend

### 5.1 `LiveEventsProvider`

Mounted in the app shell layout (not the auth layout, so signed-out pages never open a stream).

- Opens `GET /api/events` with `fetch` and parses it with `parseSseStream` from
  `lib/ask/sse.ts`, rather than `EventSource`, to keep the BFF's refresh-on-`401` path and to
  control backoff.
- Exposes `useLiveEvents(): { connected: boolean }`.
- Maps events to invalidations through `keys`:

| `kind` | Invalidates |
| --- | --- |
| `project` | `keys.projects.all` |
| `checklist_module` | `keys.checklistModules.detail(id)`, `keys.checklistModules.all`, `keys.checklistChangeSets.forModule(id)` |
| `mock_data` | `keys.mockData.detail(id)`, `keys.mockDataChangeSets.forModule(id)` |
| `notification` | `keys.notifications.all` |
| `ready` / `resync` | every key above |

### 5.2 Polling as the fallback

| Hook | Connected | Not connected (unchanged from today) |
| --- | --- | --- |
| `useProjects`, `useProject`, `useChecklistModule`, `useMockDataDataset` | 60 s while a job is moving | 3 s while a job is moving |
| bell count + list | 5 min | 60 s |

The safety poll is what recovers a lost publish or a dropped message. `refetchIntervalInBackground:
false` stays everywhere.

### 5.3 Lifecycle

- Reconnect with exponential backoff, 1 s doubling to a 60 s cap, with jitter; a `503` backs
  off the same way.
- Close when the document is hidden; reopen when visible, and the new `ready` refetches.
- A `401` the BFF could not refresh stops reconnecting; the existing session handling redirects.

---

## 6. Configuration

Each lands in `config.py`, `backend/.env.example` and `docs/configuration.md` together.

| Setting | Default | Meaning |
| --- | --- | --- |
| `LIVE_EVENTS_ENABLED` | `true` | Off: `/events` answers `503`, no consumer starts, clients poll. For a proxy in front that buffers streams. |
| `KAFKA_LIVE_EVENTS_TOPIC` | `askrepo.live.events` | The topic. |
| `LIVE_EVENTS_HEARTBEAT_SECONDS` | `25` | Heartbeat interval; also bounds how late a deactivation is noticed. |
| `LIVE_EVENTS_MAX_STREAM_MINUTES` | `60` | Server-side cap on one connection. |

The production compose file needs no change: the API container already reaches Kafka.

---

## 7. The rule file, `.claude/rules/live-events.md`

1. **Events are ids, never content.**
2. **Stage, never publish directly.** `stage_live_event` inside the transaction; the commit hook
   publishes. A direct publish from a service is a defect even when its ordering is right.
3. **Every state write the frontend displays stages an event**, in the repository or service
   that writes it.
4. **Visibility is decided by `live_event_visible_to` in `app/core/access.py`**, re-checked per
   event against freshly loaded grants.
5. **The stream is a hint.** Every screen it serves must still update by polling.

---

## 8. Audit

`GET /events` is an ordinary read — `.claude/rules/audit-trail.md` exemption 1. No event.

---

## 9. Testing

### 9.1 Backend

- **Staging** (`test_live_event_staging.py`): commit publishes staged events; rollback
  publishes none; duplicates in one transaction collapse; a publisher failure never raises;
  each site in §2.2 stages exactly one event of the right kind and id.
- **Hub** (`test_live_event_hub.py`): fans out to every subscriber; a full queue yields one
  `resync`; `available` gates the route.
- **Route** (`test_events_api.py`): `401`; `403 PASSWORD_CHANGE_REQUIRED`; `503` when
  disabled and when the hub is unavailable; `ready` first; a non-member never receives a
  project event; an admin does; a notification reaches only its recipients; a membership
  revoked mid-stream stops that project's events; a user deactivated mid-stream is closed at
  the next heartbeat.
- **Existing suites:** `test_api_model.py` walks the new events; `test_scoping_is_single_point.py`
  passes with `live_event_visible_to` in `access.py`.
- **Integration** (`integration` marker): one real Kafka round trip, API-produced event to
  a connected stream.

### 9.2 Frontend (Vitest)

- Provider: each `kind` invalidates the right keys; `ready`/`resync` invalidate all.
- Backoff grows and caps; `503` backs off.
- `connected` switches the hooks' intervals.
- Hidden closes, visible reopens.
- BFF: `forward()` passes the abort signal.

### 9.3 Checks

`make check` and `bun run build` pass.

---

## 10. Documentation changed in the implementation change

| Doc | Change |
| --- | --- |
| `docs/PRD.md` | §0.2's amendments |
| `.claude/rules/live-events.md` | new |
| `.claude/rules/notifications.md` | the fan-out stages a live event |
| `.claude/rules/frontend-bff.md` | SSE piping for any stream; abort signal |
| `CLAUDE.md` | a live-updates paragraph linking the rule; rule count 17 and the table row |
| `docs/architecture.md` | the API process consumes; the event flow |
| `docs/langgraph.md` | the second SSE contract |
| `docs/notifications.md` | the bell is pushed, with polling as fallback |
| `docs/configuration.md`, `backend/.env.example` | the four settings |
| `backend/README.md` | `GET /events` |
| `CHANGELOG.md` | under `[Unreleased]`: the route, `LIVE_EVENTS_UNAVAILABLE`, the settings, the changed polling |

The PR closes #48.

---

## 11. Out of scope, and where it would go

- **Content on the stream** — would need its own serialization path and its own access review;
  refetching through REST is what keeps one.
- **Live updates for the checklist grid's rows, members, roles or audit screens** — each is one
  more `kind` and a staging site, following §7.
- **Guaranteed delivery** — an outbox table drained by the worker; not worth it for a hint
  backed by a safety poll.
