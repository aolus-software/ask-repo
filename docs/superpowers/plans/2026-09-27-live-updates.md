# Live Updates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 3 s job-status polls and the 60 s bell poll with a per-user SSE stream of id-only invalidation events, fed by Kafka, with polling kept as the fallback.

**Architecture:** State-changing code stages a `LiveEvent` on the SQLAlchemy session; an `after_commit` hook hands staged events to a process-wide publisher (Kafka in the API and worker, an in-memory bus in tests). Each API process runs one group-less Kafka consumer (`KafkaLiveEventHub`) that fans events into per-connection queues; `GET /events` re-checks access per event through `app/core/access.py` and streams `invalidate` events. The frontend's `LiveEventsProvider` turns them into React Query invalidations and relaxes the hooks' polling while connected.

**Tech Stack:** FastAPI, SQLAlchemy async (asyncpg), aiokafka, pytest; Next.js 16, React 19, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-09-27-live-updates-design.md` — read it before any task. Where this plan and the spec disagree, the spec wins; stop and report.

## Global Constraints

- Events carry `kind`, `id`, `projectId` (and internally `recipients` for notifications) — never a name, status value, or text (spec §0.3).
- Code never publishes directly: it calls `stage_live_event(session, event)` inside the transaction; only the `after_commit` hook publishes (spec §2.1, §7.2).
- Visibility is decided only by `live_event_visible_to` in `app/core/access.py` (spec §4.2).
- `/events` is **not** added to `GATE_EXEMPT_PREFIXES`.
- Every SSE payload model inherits `StreamEvent`/`ApiModel` and is listed in `SSE_EVENT_MODELS` (`app/schemas/__init__.py`).
- `ErrorCode` members are added, never renamed. New member: `LIVE_EVENTS_UNAVAILABLE`.
- A new `Settings` field lands in `app/config.py`, `backend/.env.example` and `docs/configuration.md` in the same change.
- Settings (exact): `live_events_enabled: bool = True`, `kafka_live_events_topic: str = "askrepo.live.events"`, `live_events_heartbeat_seconds: int = Field(default=25, ge=1)`, `live_events_max_stream_minutes: int = Field(default=60, ge=1)`.
- Topic: one partition, `retention.ms` = `3600000`.
- Frontend: design tokens only; no `dark:` colour utility; `render=`, never `asChild`.
- `# noqa` / `# type: ignore` need a reason on the same line.
- Backend commands from `backend/` (`uv run ...`), frontend from `frontend/` (`bunx vitest run`, `bun lint`, `bunx tsc --noEmit`).
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`. Never push; work is on `feat/live-updates`.

## File map

**Backend — create:** `app/live/__init__.py`, `app/live/events.py` (event model + constructors), `app/live/staging.py` (stage + commit hooks + publisher registry), `app/live/fanout.py` (per-connection queues), `app/live/bus.py` (`InMemoryLiveEventBus`), `app/live/kafka.py` (`KafkaLivePublisher`, `KafkaLiveEventHub`), `app/live/stream.py` (the SSE generator), `app/schemas/live.py`, `app/api/routes/events.py`.

**Backend — modify:** `app/config.py`, `app/queue/producer.py` (`ensure_topics` topic configs), `app/main.py`, `app/worker.py`, `app/core/errors.py`, `app/core/middleware.py`, `app/core/access.py`, `app/schemas/__init__.py`, `app/repositories/project.py`, `app/repositories/checklist_module.py`, `app/repositories/mock_data_dataset.py`, `app/services/project.py`, `app/services/checklist_module.py`, `app/services/mock_data_dataset.py`, `app/services/checklist_change_set.py`, `app/services/mock_data_change_set.py`, `app/services/notification_fanout.py`, `tests/conftest.py`.

**Backend tests — create:** `tests/test_live_staging.py`, `tests/test_live_fanout.py`, `tests/test_live_event_sites.py`, `tests/test_live_stream.py`, `tests/test_events_api.py`, `tests/test_live_kafka_integration.py`.

**Frontend — create:** `lib/live/invalidation.ts` (+ test), `lib/live/backoff.ts` (+ test), `components/live/live-events-provider.tsx` (+ test), `hooks/use-live-events.ts`.

**Frontend — modify:** `app/api/[...path]/route.ts` (+ test), `components/layout/app-shell.tsx`, `hooks/use-projects.ts`, `hooks/use-checklist.ts`, `hooks/use-mock-data.ts`, `hooks/use-notifications.ts`.

**Docs:** `docs/PRD.md`, `.claude/rules/live-events.md` (new), `.claude/rules/notifications.md`, `.claude/rules/frontend-bff.md`, `CLAUDE.md`, `docs/architecture.md`, `docs/langgraph.md`, `docs/notifications.md`, `docs/configuration.md`, `backend/.env.example`, `backend/README.md`, `CHANGELOG.md`.

---

### Task 1: The event, staging on commit, and the in-memory bus

**Files:**
- Create: `backend/app/live/__init__.py` (empty docstring module), `backend/app/live/kinds.py`, `backend/app/live/events.py`, `backend/app/live/staging.py`, `backend/app/live/fanout.py`, `backend/app/live/bus.py`
- Modify: `backend/tests/conftest.py`
- Test: `backend/tests/test_live_staging.py`, `backend/tests/test_live_fanout.py`

**Interfaces:**
- Produces:
  - `LiveKind = Literal["project", "checklist_module", "mock_data", "notification"]` in `app/live/kinds.py` — a module that imports nothing from `app`, so `app/schemas/live.py` (Task 5) can import it without a cycle through `app/schemas/__init__.py`
  - `class LiveEvent(ApiModel)`: `kind: LiveKind`, `id: uuid.UUID`, `project_id: uuid.UUID | None`, `recipients: tuple[uuid.UUID, ...] = ()`; methods `to_bytes() -> bytes`, `@classmethod from_bytes(raw: bytes) -> LiveEvent`
  - constructors `project_event(project_id)`, `checklist_module_event(module_id, project_id)`, `mock_data_event(module_id, project_id)`, `notification_event(event_id, project_id, recipients: Iterable[uuid.UUID])` — all return `LiveEvent`
  - `class LivePublisher(Protocol)`: `def submit(self, events: Sequence[LiveEvent]) -> None`
  - `stage_live_event(session: AsyncSession | Session, event: LiveEvent) -> None`; `set_live_publisher(publisher: LivePublisher) -> None`; `get_live_publisher() -> LivePublisher`; `NullPublisher`
  - `RESYNC: Final = "resync"`; `QueueItem = LiveEvent | Literal["resync"]`; `QUEUE_SIZE: Final = 100`; `class LiveEventFanout` with `subscribe() -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]`, `deliver(event: LiveEvent) -> None`, `subscriber_count: int` (property)
  - `class LiveEventHub` (a small base class in `app/live/bus.py`): `available: bool` (property), `subscribe() -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]`
  - `class InMemoryLiveEventBus` implementing both `LivePublisher` and `LiveEventHub`; attribute `published: list[LiveEvent]`; `available: bool` settable
  - conftest fixture `live_bus -> InMemoryLiveEventBus` (autouse; installs it as the publisher)

- [ ] **Step 1: Write the failing staging tests**

Create `backend/tests/test_live_staging.py`:

```python
"""Live events leave only on commit.

`stage_live_event` queues an event on the session; the `after_commit` hook hands the queue
to the process's publisher and `after_rollback` discards it. These tests pin that a
rolled-back change never announces itself and that a broken publisher never fails the
write it rides on.
"""

import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.live.bus import InMemoryLiveEventBus
from app.live.events import LiveEvent, notification_event, project_event
from app.live.staging import set_live_publisher, stage_live_event


async def test_commit_publishes_staged_events(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    event = project_event(uuid.uuid4())
    stage_live_event(db_session, event)
    assert live_bus.published == []

    await db_session.commit()

    assert live_bus.published == [event]


async def test_rollback_publishes_nothing(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    stage_live_event(db_session, project_event(uuid.uuid4()))

    await db_session.rollback()
    await db_session.commit()

    assert live_bus.published == []


async def test_duplicates_in_one_transaction_collapse(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project_id = uuid.uuid4()
    stage_live_event(db_session, project_event(project_id))
    stage_live_event(db_session, project_event(project_id))

    await db_session.commit()

    assert live_bus.published == [project_event(project_id)]


async def test_a_failing_publisher_never_fails_the_commit(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        def submit(self, events: Sequence[LiveEvent]) -> None:
            raise RuntimeError("broker gone")

    set_live_publisher(Broken())
    stage_live_event(db_session, project_event(uuid.uuid4()))

    await db_session.commit()

    assert "live event publish failed" in caplog.text


def test_an_event_round_trips_through_bytes() -> None:
    event = notification_event(uuid.uuid4(), uuid.uuid4(), [uuid.uuid4(), uuid.uuid4()])
    assert LiveEvent.from_bytes(event.to_bytes()) == event
```

Create `backend/tests/test_live_fanout.py`:

```python
"""Per-connection queues: every subscriber sees every event; a slow one gets `resync`."""

import uuid

from app.live.events import project_event
from app.live.fanout import QUEUE_SIZE, RESYNC, LiveEventFanout


async def test_every_subscriber_receives_each_event() -> None:
    fanout = LiveEventFanout()
    event = project_event(uuid.uuid4())
    async with fanout.subscribe() as first, fanout.subscribe() as second:
        fanout.deliver(event)
        assert first.get_nowait() == event
        assert second.get_nowait() == event


async def test_a_full_queue_is_replaced_by_one_resync() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe() as queue:
        for _ in range(QUEUE_SIZE + 5):
            fanout.deliver(project_event(uuid.uuid4()))
        assert queue.get_nowait() == RESYNC
        assert queue.empty()


async def test_leaving_the_context_unsubscribes() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe():
        assert fanout.subscriber_count == 1
    assert fanout.subscriber_count == 0
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_live_staging.py tests/test_live_fanout.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.live'` (the `live_bus` fixture does not exist yet either).

- [ ] **Step 3: Write `app/live/kinds.py` and `app/live/events.py`**

`app/live/kinds.py` imports nothing from `app`. It is separate because `app/live/events.py`
imports `app.schemas.base`, which runs `app/schemas/__init__.py`, which (from Task 5) imports
`app/schemas/live.py` — and that module needs `LiveKind`. Defined here, the chain has no cycle.

```python
"""What a live event can be about. Imports nothing from `app`, so any module may use it."""

from typing import Literal

LiveKind = Literal["project", "checklist_module", "mock_data", "notification"]
```

`app/live/events.py`:

```python
"""The live-update event: what changed, never what it changed to.

A browser receives `kind`, `id` and `projectId` and refetches through REST, whose
`404`/`403` rules still decide what it sees. `recipients` exists only so the API can route a
notification to the people it was for; it never leaves the server.
"""

import uuid
from collections.abc import Iterable

from app.live.kinds import LiveKind
from app.schemas.base import ApiModel


class LiveEvent(ApiModel):
    """One change, as it travels between processes."""

    kind: LiveKind
    id: uuid.UUID
    project_id: uuid.UUID | None
    recipients: tuple[uuid.UUID, ...] = ()

    def to_bytes(self) -> bytes:
        """Serialize for Kafka."""
        return self.model_dump_json(by_alias=True).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "LiveEvent":
        """Parse what `to_bytes` wrote."""
        return cls.model_validate_json(raw)


def project_event(project_id: uuid.UUID) -> LiveEvent:
    """A project's status, lease, reindex flag or existence changed."""
    return LiveEvent(kind="project", id=project_id, project_id=project_id)


def checklist_module_event(module_id: uuid.UUID, project_id: uuid.UUID) -> LiveEvent:
    """A checklist module's generation status changed."""
    return LiveEvent(kind="checklist_module", id=module_id, project_id=project_id)


def mock_data_event(module_id: uuid.UUID, project_id: uuid.UUID) -> LiveEvent:
    """A mock dataset's status changed.

    `id` is the **checklist module** id: the frontend keys mock data by module
    (`keys.mockData.detail(moduleId)`), so that is the id it can invalidate.
    """
    return LiveEvent(kind="mock_data", id=module_id, project_id=project_id)


def notification_event(
    event_id: uuid.UUID, project_id: uuid.UUID, recipients: Iterable[uuid.UUID]
) -> LiveEvent:
    """A notification was written for these users."""
    return LiveEvent(
        kind="notification",
        id=event_id,
        project_id=project_id,
        recipients=tuple(sorted(recipients)),
    )
```

- [ ] **Step 4: Write `app/live/staging.py`**

```python
"""Stage on the session, publish on commit — the only way a live event leaves a process.

A service never publishes: it stages. The `after_commit` hook hands the staged events to the
process's publisher, and `after_rollback` drops them, so a change that rolled back can never
announce itself and no call site has to order a publish against a commit by hand
(`.claude/rules/live-events.md`).

The publisher is process-wide: `KafkaLivePublisher` in the API and the worker,
`InMemoryLiveEventBus` in tests, and `NullPublisher` until one is installed.
"""

import logging
from collections.abc import Sequence
from typing import Protocol

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.live.events import LiveEvent

logger = logging.getLogger(__name__)

_STAGED_KEY = "askrepo.live_events"


class LivePublisher(Protocol):
    """Takes a committed transaction's events. Must not block and must not raise."""

    def submit(self, events: Sequence[LiveEvent]) -> None: ...


class NullPublisher:
    """Drops everything. The default before the lifespan installs a real one."""

    def submit(self, events: Sequence[LiveEvent]) -> None:
        return None


_publisher: LivePublisher = NullPublisher()


def set_live_publisher(publisher: LivePublisher) -> None:
    """Install the process-wide publisher."""
    global _publisher  # noqa: PLW0603 -- one publisher per process, installed at startup
    _publisher = publisher


def get_live_publisher() -> LivePublisher:
    """The process-wide publisher."""
    return _publisher


def stage_live_event(session: AsyncSession | Session, live_event: LiveEvent) -> None:
    """Queue an event to publish if, and only if, this session's transaction commits.

    A repeat of the same event in one transaction is kept once.
    """
    staged: list[LiveEvent] = session.info.setdefault(_STAGED_KEY, [])
    if live_event not in staged:
        staged.append(live_event)


@event.listens_for(Session, "after_commit")
def _publish_staged(session: Session) -> None:
    staged: list[LiveEvent] = session.info.pop(_STAGED_KEY, [])
    if not staged:
        return
    try:
        _publisher.submit(staged)
    except Exception:
        # Never let a broker problem surface as a failed write: the change is committed,
        # and the frontend's safety poll will show it.
        logger.warning("live event publish failed for %d event(s)", len(staged), exc_info=True)


@event.listens_for(Session, "after_rollback")
def _discard_staged(session: Session) -> None:
    session.info.pop(_STAGED_KEY, None)
```

If ruff rejects the `noqa` code (the rule may not be selected), remove the `noqa` comment rather than adding a rule.

- [ ] **Step 5: Write `app/live/fanout.py`**

```python
"""Per-connection queues for one process.

Every open `/events` stream registers a bounded queue; each event goes to all of them. A
client too slow to keep up is not given an unbounded backlog: its queue is emptied and one
`resync` marker put in its place, telling it to refetch everything.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, Literal

from app.live.events import LiveEvent

RESYNC: Final = "resync"
QUEUE_SIZE: Final = 100

QueueItem = LiveEvent | Literal["resync"]


class LiveEventFanout:
    """The set of open streams in this process."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[QueueItem]] = set()

    @property
    def subscriber_count(self) -> int:
        """How many streams are open."""
        return len(self._queues)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[QueueItem]]:
        """Register a queue for the life of the `async with` block."""
        queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)

    def deliver(self, live_event: LiveEvent) -> None:
        """Put an event on every queue, replacing a full one's backlog with `resync`."""
        for queue in self._queues:
            try:
                queue.put_nowait(live_event)
            except asyncio.QueueFull:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(RESYNC)
```

- [ ] **Step 6: Write `app/live/bus.py`**

```python
"""The in-memory stand-in for Kafka: publisher and hub in one object.

Route, service and staging tests use it the way `InMemoryIngestionQueue` stands in for the
job queue, so nothing needs a broker. Events submitted are delivered straight to this
process's open streams and recorded in `published`.
"""

from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
import asyncio

from app.live.events import LiveEvent
from app.live.fanout import LiveEventFanout, QueueItem


class LiveEventHub:
    """What the `/events` route needs from a hub. Implemented by the Kafka hub and the bus."""

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        raise NotImplementedError


class InMemoryLiveEventBus(LiveEventHub):
    """Publisher and hub for tests."""

    def __init__(self) -> None:
        self.published: list[LiveEvent] = []
        self._available = True
        self._fanout = LiveEventFanout()

    @property
    def available(self) -> bool:
        return self._available

    @available.setter
    def available(self, value: bool) -> None:
        self._available = value

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        return self._fanout.subscribe()

    def submit(self, events: Sequence[LiveEvent]) -> None:
        for live_event in events:
            self.published.append(live_event)
            self._fanout.deliver(live_event)
```

Sort the imports as ruff requires. (`LiveEventHub` is a small base class rather than a
`Protocol` so the Kafka hub and the bus share one declared interface the route can type
against.)

- [ ] **Step 7: Install the bus in every test**

In `backend/tests/conftest.py`, add near the other fixtures:

```python
@pytest.fixture(autouse=True)
def live_bus() -> Iterator[InMemoryLiveEventBus]:
    """The in-memory publisher and hub, installed for every test.

    Autouse because staging happens deep inside repositories: a test that never asked for
    live events still commits through the hook, and must not reach for a real broker.
    """
    bus = InMemoryLiveEventBus()
    set_live_publisher(bus)
    yield bus
    set_live_publisher(NullPublisher())
```

with imports `from app.live.bus import InMemoryLiveEventBus` and
`from app.live.staging import NullPublisher, set_live_publisher`.

- [ ] **Step 8: Run the tests**

Run: `uv run pytest tests/test_live_staging.py tests/test_live_fanout.py -v`
Expected: PASS (8 tests).

- [ ] **Step 9: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`
(If `make check` uses a different mypy invocation, use the one in the `Makefile`.)
Expected: all green.

```bash
git add backend/app/live backend/tests/conftest.py backend/tests/test_live_staging.py backend/tests/test_live_fanout.py
git commit -m "feat(live): stage live events on the session and publish on commit

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Stage events at every state write

**Files:**
- Modify: `backend/app/repositories/project.py`, `backend/app/repositories/checklist_module.py`, `backend/app/repositories/mock_data_dataset.py`, `backend/app/services/project.py`, `backend/app/services/checklist_module.py`, `backend/app/services/mock_data_dataset.py`, `backend/app/services/checklist_change_set.py`, `backend/app/services/mock_data_change_set.py`, `backend/app/services/notification_fanout.py`
- Test: `backend/tests/test_live_event_sites.py`

**Interfaces:**
- Consumes: Task 1's `stage_live_event`, `project_event`, `checklist_module_event`, `mock_data_event`, `notification_event`, the `live_bus` fixture.
- Produces: every site below stages exactly one event on success; public method signatures and return values are **unchanged**.

The sites (spec §2.2). In each repository method, stage **only when the write took effect** (the method would return `True`, or a row came back):

| File | Method / line | Event |
| --- | --- | --- |
| `repositories/project.py` | `claim`, `set_status`, `release`, `abandon` | `project_event(project_id)` — `project_id` is already a parameter |
| `services/project.py` | `create` (after `self._repository.add(project)`), `reindex` (beside `project.reindex_in_progress = True`, ~line 257), `delete` (beside `self._repository.soft_delete(project)`, ~line 306) | `project_event(project.id)` |
| `repositories/checklist_module.py` | `claim`, `release`, `mark_in_review`, `defer` | `checklist_module_event(module_id, project_id)` — add `.returning(ChecklistModule.project_id)` to the `UPDATE`, take `project_id = result.scalar_one_or_none()`, and treat `None` as "no row updated" (return `False`/stage nothing) |
| `repositories/checklist_module.py` | `claim_stranded` | one event per returned row — change `.returning(ChecklistModule.id)` to `.returning(ChecklistModule.id, ChecklistModule.project_id)`, stage each, still return the list of ids |
| `services/checklist_module.py` | the `generate` path, beside `module.status = ChecklistModuleStatus.GENERATING.value` (~line 312) | `checklist_module_event(module.id, module.project_id)` |
| `services/checklist_change_set.py` | beside the READY/EMPTY status assignment (~line 368) | `checklist_module_event(<module>.id, <module>.project_id)` |
| `repositories/mock_data_dataset.py` | `claim`, `release`, `mark_in_review`, `defer`, `claim_stranded` | `mock_data_event(checklist_module_id, project_id)` — the dataset has no `project_id` column, so return it through a scalar subquery (below) |
| `services/mock_data_dataset.py` | beside `dataset.status = MockDataDatasetStatus.GENERATING.value` (~line 147) | `mock_data_event(dataset.checklist_module_id, <project id>)` — the service authorizes against the module's project before this line; use that project id. If it is not in a local variable, load it with `ChecklistModuleRepository(self.session).get(dataset.checklist_module_id)` |
| `services/mock_data_change_set.py` | beside the READY/EMPTY assignment (~line 285) | `mock_data_event(...)` the same way |
| `services/notification_fanout.py` | end of `_write`, only when `recipients` is non-empty | `notification_event(event.id, project_id, recipients)` |

The `RETURNING` shapes:

```python
# checklist_module.py — e.g. in claim():
result = await self.session.execute(
    update(ChecklistModule)
    .where(...)            # unchanged
    .values(...)           # unchanged
    .returning(ChecklistModule.project_id)
)
project_id = result.scalar_one_or_none()
if project_id is None:
    return False
stage_live_event(self.session, checklist_module_event(module_id, project_id))
return True
```

```python
# mock_data_dataset.py — module-level helper:
def _dataset_project_id() -> ScalarSelect[uuid.UUID]:
    """The dataset's project, reached through its module (datasets carry no project_id)."""
    return (
        select(ChecklistModule.project_id)
        .where(ChecklistModule.id == MockDataDataset.checklist_module_id)
        .scalar_subquery()
    )

# e.g. in claim():
result = await self.session.execute(
    update(MockDataDataset)
    .where(...)            # unchanged
    .values(...)           # unchanged
    .returning(MockDataDataset.checklist_module_id, _dataset_project_id())
)
row = result.one_or_none()
if row is None:
    return False
module_id, project_id = row
stage_live_event(self.session, mock_data_event(module_id, project_id))
return True
```

Methods that returned `None` (`set_status`, `mark_in_review`) keep returning `None`; they stage when a row came back.

- [ ] **Step 1: Write the failing site tests**

Create `backend/tests/test_live_event_sites.py`. Use the existing factories (`tests/factories.py`: `create_project`, and the checklist/mock-data factories that exist there — read the file for their names) and the `live_bus` fixture. One test per site, each asserting the exact event after `await db_session.commit()`. The representative shapes:

```python
"""Every state write the frontend shows stages exactly one live event.

This is the test the rule "every status write stages" leans on: a new write site added
without staging is caught in review, and the ones that exist are pinned here.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.live.bus import InMemoryLiveEventBus
from app.live.events import checklist_module_event, mock_data_event, project_event
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository
from tests.factories import create_project


async def test_project_set_status_stages_a_project_event(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    live_bus.published.clear()

    await ProjectRepository(db_session).set_status(
        project_id=project.id, status=ProjectStatus.INDEXING
    )
    await db_session.commit()

    assert live_bus.published == [project_event(project.id)]


async def test_a_refused_claim_stages_nothing(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project = await create_project(db_session, grant_owner=False, status=ProjectStatus.FAILED)
    await db_session.commit()
    live_bus.published.clear()

    claimed = await ProjectRepository(db_session).claim(
        project_id=uuid.uuid4(), job_id=uuid.uuid4(), worker_id="w", lease_seconds=60
    )
    await db_session.commit()

    assert claimed is False
    assert live_bus.published == []
```

Write the remaining tests to the same shape — one each for: project `claim` (success), `release`, `abandon`; `ProjectService.create`, `.reindex`, `.delete` (drive them through the HTTP API with `client_for_user_a`/`authed_client` and `grant_membership`, as `tests/test_projects_api.py` does, then assert `project_event(id)` is in `live_bus.published`); checklist module `claim`, `release`, `mark_in_review`, `defer`, `claim_stranded` (assert `checklist_module_event(module.id, module.project_id)`); the generate request (`POST /checklist-modules/{id}/generate`); a checklist change-set apply; the five mock-dataset repository methods (assert `mock_data_event(module.id, module.project_id)`); the mock-data generate request; a mock-data change-set apply; and a `NotificationFanout.raise_event` with at least one recipient (assert `notification_event(<event id>, project_id, recipients)` — read the event id back from `notification_events`) plus one with no recipients (assert nothing staged). Copy each call's argument shapes from the method signatures listed in the table above and from the existing tests that already exercise those methods (`grep -rn "\.claim(\|mark_in_review\|claim_stranded" tests/`).

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_live_event_sites.py -v`
Expected: FAIL — each assertion sees `live_bus.published == []`.

- [ ] **Step 3: Stage at every site in the table**

Add `from app.live.events import ...` and `from app.live.staging import stage_live_event` to each file and make the edits the table describes. Do not change any public signature or return value.

- [ ] **Step 4: Run the site tests, then the full suite**

Run: `uv run pytest tests/test_live_event_sites.py -v` → PASS.
Run: `uv run pytest -q` → PASS (the `RETURNING` changes must not break any existing claim/release/defer test).

- [ ] **Step 5: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`

```bash
git add backend/app/repositories backend/app/services backend/tests/test_live_event_sites.py
git commit -m "feat(live): stage an event at every job-status and notification write

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Kafka publisher, Kafka hub, settings and wiring

**Files:**
- Create: `backend/app/live/kafka.py`
- Modify: `backend/app/config.py`, `backend/app/queue/producer.py` (`ensure_topics`), `backend/app/main.py` (lifespan), `backend/app/worker.py`, `backend/.env.example`, `docs/configuration.md`
- Test: `backend/tests/test_live_kafka.py` (unit), `backend/tests/test_live_kafka_integration.py` (`integration` marker)

**Interfaces:**
- Consumes: Task 1's `LiveEvent`, `LiveEventFanout`, `LiveEventHub`, `set_live_publisher`.
- Produces:
  - `ensure_topics(*, bootstrap_servers, partitions, topics=ALL_TOPICS, topic_configs: Mapping[str, str] | None = None)`
  - `KafkaLivePublisher(*, bootstrap_servers: str, topic: str)` with `async start()`, `async stop()`, `submit(events)`
  - `KafkaLiveEventHub(*, bootstrap_servers: str, topic: str)` (subclass of `LiveEventHub`) with `async start()`, `async stop()`, `available`, `subscribe()`, and `dispatch(raw: bytes) -> None` (decode + deliver; public for the unit test)
  - `DisabledLiveEventHub` (subclass of `LiveEventHub`, `available` always `False`)
  - `app.state.live_hub: LiveEventHub` set by the lifespan
  - `LIVE_TOPIC_CONFIGS: Final = {"retention.ms": "3600000"}` in `app/live/kafka.py`

- [ ] **Step 1: Add the settings**

In `backend/app/config.py`, after the mock-data Kafka settings:

```python
    # Live updates (issue #48). `GET /events` streams id-only invalidations fed by this
    # topic; off, the route answers 503 and every client polls. See docs/configuration.md.
    live_events_enabled: bool = True
    kafka_live_events_topic: str = "askrepo.live.events"
    live_events_heartbeat_seconds: int = Field(default=25, ge=1)
    live_events_max_stream_minutes: int = Field(default=60, ge=1)
```

Add the same four names with their defaults, in a new "Live updates" group, to `backend/.env.example`
(`LIVE_EVENTS_ENABLED=true`, `KAFKA_LIVE_EVENTS_TOPIC=askrepo.live.events`,
`LIVE_EVENTS_HEARTBEAT_SECONDS=25`, `LIVE_EVENTS_MAX_STREAM_MINUTES=60`), no inline prose.

In `docs/configuration.md`, add a "Live updates" section documenting each: meaning, default,
and when to change it (spec §6's table text).

- [ ] **Step 2: Let `ensure_topics` pass topic configs**

In `backend/app/queue/producer.py`, add `topic_configs: Mapping[str, str] | None = None` to
`ensure_topics` and pass `topic_configs=dict(topic_configs or {})` to each `NewTopic(...)`.
Document the parameter in the docstring. Existing callers are unchanged.

- [ ] **Step 3: Write the failing unit test**

Create `backend/tests/test_live_kafka.py`:

```python
"""The Kafka hub's decoding and fan-out, without a broker."""

import uuid

from app.live.events import project_event
from app.live.kafka import DisabledLiveEventHub, KafkaLiveEventHub


async def test_dispatch_decodes_and_delivers() -> None:
    hub = KafkaLiveEventHub(bootstrap_servers="unused:9092", topic="t")
    event = project_event(uuid.uuid4())
    async with hub.subscribe() as queue:
        hub.dispatch(event.to_bytes())
        assert queue.get_nowait() == event


async def test_an_undecodable_message_is_dropped() -> None:
    hub = KafkaLiveEventHub(bootstrap_servers="unused:9092", topic="t")
    async with hub.subscribe() as queue:
        hub.dispatch(b"not json")
        assert queue.empty()


def test_a_hub_is_unavailable_until_it_connects() -> None:
    assert KafkaLiveEventHub(bootstrap_servers="unused:9092", topic="t").available is False
    assert DisabledLiveEventHub().available is False
```

Run: `uv run pytest tests/test_live_kafka.py -v` → FAIL (`ModuleNotFoundError: app.live.kafka`).

- [ ] **Step 4: Write `app/live/kafka.py`**

```python
"""Live events over Kafka: a best-effort publisher, and one group-less consumer per API process.

The consumer has no `group_id`: it assigns itself every partition of the topic and seeks to
the end, so there are no rebalances and no offset commits, and each API process receives
every event. `CLAUDE.md`'s pause-and-poll rule is about group members holding a seat through
a long job; a group-less consumer that polls continuously has no seat to lose.
"""

import asyncio
import contextlib
import logging
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Final

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from pydantic import ValidationError

from app.live.bus import LiveEventHub
from app.live.events import LiveEvent
from app.live.fanout import LiveEventFanout, QueueItem

logger = logging.getLogger(__name__)

# Nothing reads history: the consumer starts at the end. An hour is margin, not a promise.
LIVE_TOPIC_CONFIGS: Final = {"retention.ms": "3600000"}
_RECONNECT_BACKOFF_SECONDS: Final = (1, 2, 5, 10, 30)


class KafkaLivePublisher:
    """Sends committed events. Never raises: a lost event costs a delayed screen update."""

    def __init__(self, *, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer: AIOKafkaProducer | None = None
        self._pending: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers, acks=1)
        await self._producer.start()

    async def stop(self) -> None:
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    def submit(self, events: Sequence[LiveEvent]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("live event dropped: no running event loop")
            return
        task = loop.create_task(self._send(list(events)))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _send(self, events: list[LiveEvent]) -> None:
        if self._producer is None:
            return
        for live_event in events:
            try:
                await self._producer.send(self._topic, value=live_event.to_bytes())
            except Exception:
                logger.warning(
                    "live event publish failed: kind=%s id=%s",
                    live_event.kind,
                    live_event.id,
                    exc_info=True,
                )


class KafkaLiveEventHub(LiveEventHub):
    """One consumer for the process, fanning out to every open stream."""

    def __init__(self, *, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._fanout = LiveEventFanout()
        self._available = False
        self._task: asyncio.Task[None] | None = None

    @property
    def available(self) -> bool:
        return self._available

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        return self._fanout.subscribe()

    async def start(self) -> None:
        """Start consuming in the background. Never raises: an absent broker means
        `available` stays False and clients poll."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def dispatch(self, raw: bytes) -> None:
        """Decode one message and deliver it. An undecodable message is logged and dropped."""
        try:
            live_event = LiveEvent.from_bytes(raw)
        except ValidationError:
            logger.warning("undecodable live event dropped")
            return
        self._fanout.deliver(live_event)

    async def _run(self) -> None:
        attempt = 0
        while True:
            consumer = AIOKafkaConsumer(bootstrap_servers=self._bootstrap_servers)
            try:
                await consumer.start()
                partitions = await consumer.partitions_for_topic(self._topic) or {0}
                assigned = [TopicPartition(self._topic, p) for p in partitions]
                consumer.assign(assigned)
                await consumer.seek_to_end(*assigned)
                self._available = True
                attempt = 0
                async for message in consumer:
                    if message.value is not None:
                        self.dispatch(message.value)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("live event consumer lost the broker; retrying", exc_info=True)
            finally:
                self._available = False
                with contextlib.suppress(Exception):
                    await consumer.stop()
            delay = _RECONNECT_BACKOFF_SECONDS[min(attempt, len(_RECONNECT_BACKOFF_SECONDS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)


class DisabledLiveEventHub(LiveEventHub):
    """`LIVE_EVENTS_ENABLED=false`: never available, so `/events` answers 503."""

    def __init__(self) -> None:
        self._fanout = LiveEventFanout()

    @property
    def available(self) -> bool:
        return False

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        return self._fanout.subscribe()
```

Run: `uv run pytest tests/test_live_kafka.py -v` → PASS.

- [ ] **Step 5: Wire the lifespan and the worker**

`backend/app/main.py` lifespan, in the non-test branch:
- add a fourth `ensure_topics` call:
  `await ensure_topics(bootstrap_servers=settings.kafka_bootstrap_servers, partitions=1, topics=(settings.kafka_live_events_topic,), topic_configs=LIVE_TOPIC_CONFIGS)`
- after `await queue.start()`:

```python
    live_publisher = KafkaLivePublisher(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=settings.kafka_live_events_topic,
    )
    await live_publisher.start()
    set_live_publisher(live_publisher)
    live_hub: LiveEventHub = (
        KafkaLiveEventHub(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            topic=settings.kafka_live_events_topic,
        )
        if settings.live_events_enabled
        else DisabledLiveEventHub()
    )
    if isinstance(live_hub, KafkaLiveEventHub):
        await live_hub.start()
    app.state.live_hub = live_hub
```

- in the `finally`, before `await queue.stop()`: stop the hub if it is a `KafkaLiveEventHub`, then `await live_publisher.stop()` and `set_live_publisher(NullPublisher())`.
- in the `APP_ENV == "test"` branch (before its `yield`), set `app.state.live_hub = DisabledLiveEventHub()` so the attribute always exists; tests override the dependency (Task 5).

The publisher starts even when `LIVE_EVENTS_ENABLED` is false: the worker must keep publishing for any other API process that has it on, and publishing to a topic nobody reads is harmless.

`backend/app/worker.py`: add the same `ensure_topics` call for the live topic beside the other three, then after `await producer.start()` create, start and `set_live_publisher(...)` a `KafkaLivePublisher`, and stop it in the same `finally` that stops `producer`.

- [ ] **Step 6: Write the integration test**

Create `backend/tests/test_live_kafka_integration.py`, marked like `tests/test_ingestion_integration.py` (read that file for the marker and how it gets bootstrap servers):

```python
"""A real Kafka round trip: publish on one side, a subscribed hub receives it."""

import asyncio
import uuid

import pytest

from app.config import get_settings
from app.live.events import project_event
from app.live.kafka import LIVE_TOPIC_CONFIGS, KafkaLiveEventHub, KafkaLivePublisher
from app.queue.producer import ensure_topics

pytestmark = pytest.mark.integration


async def test_a_published_event_reaches_a_subscriber() -> None:
    settings = get_settings()
    topic = f"askrepo.live.test.{uuid.uuid4().hex[:8]}"
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=1,
        topics=(topic,),
        topic_configs=LIVE_TOPIC_CONFIGS,
    )
    hub = KafkaLiveEventHub(bootstrap_servers=settings.kafka_bootstrap_servers, topic=topic)
    publisher = KafkaLivePublisher(bootstrap_servers=settings.kafka_bootstrap_servers, topic=topic)
    await hub.start()
    await publisher.start()
    try:
        for _ in range(100):
            if hub.available:
                break
            await asyncio.sleep(0.1)
        assert hub.available
        event = project_event(uuid.uuid4())
        async with hub.subscribe() as queue:
            publisher.submit([event])
            assert await asyncio.wait_for(queue.get(), timeout=10) == event
    finally:
        await publisher.stop()
        await hub.stop()
```

Run: `uv run pytest -m integration tests/test_live_kafka_integration.py -v` (Kafka is running locally).
Expected: PASS. If it fails because of the local broker rather than the code, record the output in the report.

- [ ] **Step 7: Full suite, lint, commit**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`

```bash
git add backend/app/live/kafka.py backend/app/config.py backend/app/queue/producer.py \
  backend/app/main.py backend/app/worker.py backend/.env.example docs/configuration.md \
  backend/tests/test_live_kafka.py backend/tests/test_live_kafka_integration.py
git commit -m "feat(live): publish and consume live events over Kafka

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Visibility in `access.py`, and a reusable user loader

**Files:**
- Modify: `backend/app/core/middleware.py`, `backend/app/core/access.py`
- Test: `backend/tests/test_access.py`

**Interfaces:**
- Consumes: Task 1's `LiveEvent`, constructors.
- Produces:
  - `async def load_authenticated_user(session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID | None) -> AuthenticatedUser | None` in `app/core/middleware.py` — `None` when the user row is missing or soft-deleted
  - `def live_event_visible_to(user: AuthenticatedUser, event: LiveEvent) -> bool` in `app/core/access.py`

- [ ] **Step 1: Write the failing access tests**

Append to `backend/tests/test_access.py`, building `AuthenticatedUser`s the way the file already does:

```python
def test_a_project_event_is_visible_only_within_scope() -> None:
    member_of = uuid.uuid4()
    other = uuid.uuid4()
    member = _user(grants={member_of: ProjectGrant(project_id=member_of, role="viewer", permissions=frozenset())})
    admin = _user(is_admin=True)

    assert live_event_visible_to(member, project_event(member_of)) is True
    assert live_event_visible_to(member, project_event(other)) is False
    assert live_event_visible_to(admin, project_event(other)) is True


def test_a_notification_is_visible_only_to_its_recipients() -> None:
    reader = _user()
    admin = _user(is_admin=True)
    event = notification_event(uuid.uuid4(), uuid.uuid4(), [reader.id])

    assert live_event_visible_to(reader, event) is True
    assert live_event_visible_to(admin, event) is False  # rule 5: no admin bypass on notifications
```

If `tests/test_access.py` has no `_user` helper, add one at the top of the new tests that
constructs `AuthenticatedUser(id=uuid.uuid4(), name="U", email=f"{uuid.uuid4().hex}@example.com", is_admin=is_admin, must_change_password=False, grants=grants or {})`.

Run: `uv run pytest tests/test_access.py -k live_event -v` → FAIL (`ImportError`).

- [ ] **Step 2: Implement `live_event_visible_to`**

In `backend/app/core/access.py` (import `LiveEvent` from `app.live.events`):

```python
def live_event_visible_to(user: AuthenticatedUser, event: LiveEvent) -> bool:
    """Whether an open `/events` stream may forward this event to this caller.

    A notification goes only to the users the fan-out resolved — with no administrator
    bypass, for the reason `.claude/rules/notifications.md` rule 5 gives. Every other kind
    follows project read scope, so an administrator sees every project's invalidations
    (ids only) and a member only their own projects'.
    """
    if event.kind == "notification":
        return user.id in event.recipients
    if event.project_id is None:
        return False
    scope = resolve_project_scope(user)
    return scope.unrestricted or event.project_id in scope.ids
```

Run: `uv run pytest tests/test_access.py tests/test_scoping_is_single_point.py -v` → PASS.

- [ ] **Step 3: Extract `load_authenticated_user`**

In `backend/app/core/middleware.py`, add:

```python
async def load_authenticated_user(
    session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID | None
) -> AuthenticatedUser | None:
    """The request-scoped identity for one user, or `None` if the row is gone.

    Shared by the middleware and by long-lived streams that must re-check who is on the
    other end without a new request (`GET /events`).
    """
    user = await UserRepository(session).get(user_id)
    if user is None:
        return None
    grants = await _load_grants(session, user.id)
    return AuthenticatedUser(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
        grants=grants,
        session_id=session_id,
    )
```

and change `_resolve` to call it inside its `async with get_sessionmaker()() as session:` block,
returning `AuthContext(user=None, error=ErrorCode.INVALID_TOKEN)` when it returns `None`.
Behaviour is unchanged.

- [ ] **Step 4: Run, lint, commit**

Run: `uv run pytest tests/test_access.py tests/test_auth_middleware.py tests/test_middleware_grants.py tests/test_scoping_is_single_point.py -q && uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`

```bash
git add backend/app/core/middleware.py backend/app/core/access.py backend/tests/test_access.py
git commit -m "feat(live): decide live-event visibility in access.py

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: The `GET /events` stream

**Files:**
- Create: `backend/app/schemas/live.py`, `backend/app/live/stream.py`, `backend/app/api/routes/events.py`
- Modify: `backend/app/schemas/__init__.py` (`SSE_EVENT_MODELS`), `backend/app/core/errors.py`, `backend/app/main.py` (include router), `backend/tests/conftest.py` (override the hub dependency), `backend/README.md`
- Test: `backend/tests/test_live_stream.py`, `backend/tests/test_events_api.py`

**Interfaces:**
- Consumes: Task 1 (`InMemoryLiveEventBus`, `RESYNC`, `LiveEventHub`), Task 3 (`app.state.live_hub`, settings), Task 4 (`load_authenticated_user`, `live_event_visible_to`).
- Produces:
  - `ReadyEvent`, `InvalidateEvent` (`kind: LiveKind`, `id: uuid.UUID`, `project_id: uuid.UUID | None`), `ResyncEvent` — all subclasses of `StreamEvent` (`app/schemas/conversation.py`) with `event_name` `"ready"`, `"invalidate"`, `"resync"`
  - `HEARTBEAT: Final = b": ping\n\n"`
  - `async def live_event_stream(*, user: AuthenticatedUser, hub: LiveEventHub, sessionmaker: async_sessionmaker[AsyncSession], heartbeat_seconds: float, max_seconds: float) -> AsyncIterator[bytes]`
  - `def get_live_hub(request: Request) -> LiveEventHub` in `app/api/routes/events.py`
  - `ErrorCode.LIVE_EVENTS_UNAVAILABLE`

- [ ] **Step 1: Write the failing stream tests**

Create `backend/tests/test_live_stream.py`. These drive the generator directly: an infinite
SSE body cannot be read to its end through httpx's ASGI transport, and the generator is where
the behaviour lives.

```python
"""The `/events` generator: ready first, access re-checked per event, closed on deactivation."""

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.grant_cache import get_grant_cache
from app.core.middleware import load_authenticated_user
from app.live.bus import InMemoryLiveEventBus
from app.live.events import notification_event, project_event
from app.live.stream import HEARTBEAT, live_event_stream
from app.models import User
from app.models.membership import ProjectMembership
from tests.conftest import GrantMembership
from tests.factories import create_project


async def _next(stream: AsyncIterator[bytes]) -> bytes:
    return await asyncio.wait_for(anext(stream), timeout=2)


async def _open(
    user: User,
    bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    heartbeat: float = 5,
    max_seconds: float = 30,
) -> AsyncIterator[bytes]:
    async with sessionmaker() as session:
        actor = await load_authenticated_user(session, user.id, None)
    assert actor is not None
    return live_event_stream(
        user=actor, hub=bus, sessionmaker=sessionmaker,
        heartbeat_seconds=heartbeat, max_seconds=max_seconds,
    )


async def test_ready_comes_first(
    authed_user: User, live_bus: InMemoryLiveEventBus, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    stream = await _open(authed_user, live_bus, sessionmaker)
    assert (await _next(stream)).startswith(b"event: ready\n")
    await stream.aclose()


async def test_a_member_receives_their_projects_events_and_not_others(
    authed_user: User,
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    mine = await create_project(db_session, grant_owner=False)
    theirs = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    await grant_membership(authed_user.id, mine.id, "viewer")
    stream = await _open(authed_user, live_bus, sessionmaker)
    await _next(stream)  # ready

    live_bus.submit([project_event(theirs.id), project_event(mine.id)])

    frame = await _next(stream)
    assert frame.startswith(b"event: invalidate\n")
    assert str(mine.id).encode() in frame
    assert str(theirs.id).encode() not in frame
    await stream.aclose()


async def test_an_admin_receives_every_projects_events(
    admin_user: User,
    db_session: AsyncSession,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    stream = await _open(admin_user, live_bus, sessionmaker)
    await _next(stream)

    live_bus.submit([project_event(project.id)])

    assert str(project.id).encode() in await _next(stream)
    await stream.aclose()


async def test_a_notification_reaches_only_its_recipients(
    user_a: User,
    user_b: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    stream_a = await _open(user_a, live_bus, sessionmaker, heartbeat=0.2)
    stream_b = await _open(user_b, live_bus, sessionmaker, heartbeat=0.2)
    await _next(stream_a)
    await _next(stream_b)

    live_bus.submit([notification_event(uuid.uuid4(), uuid.uuid4(), [user_a.id])])

    assert (await _next(stream_a)).startswith(b"event: invalidate\n")
    assert await _next(stream_b) == HEARTBEAT  # nothing for B, only its heartbeat
    await stream_a.aclose()
    await stream_b.aclose()


async def test_a_revoked_membership_stops_that_projects_events(
    authed_user: User,
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, "viewer")
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=0.2)
    await _next(stream)

    await db_session.execute(
        delete(ProjectMembership).where(ProjectMembership.user_id == authed_user.id)
    )
    await db_session.commit()
    await get_grant_cache().invalidate_user(authed_user.id)
    live_bus.submit([project_event(project.id)])

    assert await _next(stream) == HEARTBEAT
    await stream.aclose()


async def test_a_deactivated_user_is_disconnected_at_the_next_heartbeat(
    authed_user: User,
    db_session: AsyncSession,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=0.1)
    await _next(stream)

    authed_user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    frames = [frame async for frame in stream]
    assert frames == []


async def test_the_stream_ends_at_its_maximum_lifetime(
    authed_user: User, live_bus: InMemoryLiveEventBus, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=0.05, max_seconds=0.2)
    frames = [frame async for frame in stream]
    assert frames[0].startswith(b"event: ready\n")


async def test_a_resync_marker_is_forwarded(
    authed_user: User, live_bus: InMemoryLiveEventBus, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    from app.live.fanout import QUEUE_SIZE

    stream = await _open(authed_user, live_bus, sessionmaker)
    await _next(stream)
    live_bus.submit([project_event(uuid.uuid4()) for _ in range(QUEUE_SIZE + 1)])

    assert (await _next(stream)).startswith(b"event: resync\n")
    await stream.aclose()
```

If `User` has no `deleted_at` (soft delete via mixin under a different name), deactivate the
user the way `tests/test_users_api.py` does.

Run: `uv run pytest tests/test_live_stream.py -v` → FAIL (`ModuleNotFoundError: app.live.stream`).

- [ ] **Step 2: Write the schemas**

Create `backend/app/schemas/live.py`:

```python
"""The `/events` stream's payloads. Each is in `SSE_EVENT_MODELS`, the only enforcement an
SSE payload gets (`tests/test_api_model.py`)."""

import uuid
from typing import ClassVar

from app.live.kinds import LiveKind
from app.schemas.conversation import StreamEvent


class ReadyEvent(StreamEvent):
    """The stream is open. The client refetches everything live."""

    event_name: ClassVar[str] = "ready"


class InvalidateEvent(StreamEvent):
    """This row changed; refetch its queries. Ids only — never content."""

    event_name: ClassVar[str] = "invalidate"
    kind: LiveKind
    id: uuid.UUID
    project_id: uuid.UUID | None


class ResyncEvent(StreamEvent):
    """Events were dropped for this connection; refetch everything live."""

    event_name: ClassVar[str] = "resync"
```

Add the three to `SSE_EVENT_MODELS` in `backend/app/schemas/__init__.py` (import from
`app.schemas.live`).

Add `LIVE_EVENTS_UNAVAILABLE = "LIVE_EVENTS_UNAVAILABLE"` at the end of `ErrorCode` in
`backend/app/core/errors.py`.

- [ ] **Step 3: Write the generator**

Create `backend/app/live/stream.py`:

```python
"""The body of `GET /events`.

Access is re-checked, not trusted: before forwarding a project-scoped event the stream
reloads the caller's grants (through the grant cache) and asks `access.live_event_visible_to`,
and on every heartbeat it re-reads the user row, closing the stream when the user is gone or
must change their password. The access token expiring mid-stream is therefore harmless.

Each check opens its own session from the sessionmaker — never the request-scoped one, for
the reason `.claude/rules/rag.md` gives for the answer stream.
"""

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import live_event_visible_to
from app.core.middleware import AuthenticatedUser, load_authenticated_user
from app.live.bus import LiveEventHub
from app.live.fanout import RESYNC
from app.schemas.conversation import encode_event
from app.schemas.live import InvalidateEvent, ReadyEvent, ResyncEvent

HEARTBEAT: Final = b": ping\n\n"


async def _recheck(
    sessionmaker: async_sessionmaker[AsyncSession], user: AuthenticatedUser
) -> AuthenticatedUser | None:
    async with sessionmaker() as session:
        fresh = await load_authenticated_user(session, user.id, user.session_id)
    if fresh is None or fresh.must_change_password:
        return None
    return fresh


async def live_event_stream(
    *,
    user: AuthenticatedUser,
    hub: LiveEventHub,
    sessionmaker: async_sessionmaker[AsyncSession],
    heartbeat_seconds: float,
    max_seconds: float,
) -> AsyncIterator[bytes]:
    """Yield SSE frames until the client leaves, the user fails a re-check, or the cap."""
    deadline = time.monotonic() + max_seconds
    current = user
    async with hub.subscribe() as queue:
        yield encode_event(ReadyEvent())
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=min(heartbeat_seconds, remaining))
            except TimeoutError:
                refreshed = await _recheck(sessionmaker, current)
                if refreshed is None:
                    return
                current = refreshed
                if deadline - time.monotonic() > 0:
                    yield HEARTBEAT
                continue
            if item == RESYNC:
                yield encode_event(ResyncEvent())
                continue
            if item.kind != "notification":
                refreshed = await _recheck(sessionmaker, current)
                if refreshed is None:
                    return
                current = refreshed
            if live_event_visible_to(current, item):
                yield encode_event(
                    InvalidateEvent(kind=item.kind, id=item.id, project_id=item.project_id)
                )
```

Run: `uv run pytest tests/test_live_stream.py -v` → PASS (8 tests).

- [ ] **Step 4: Write the failing route tests**

Create `backend/tests/test_events_api.py`:

```python
"""`GET /events` pre-flight: every status that is not 200 is decided before the first byte."""

from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.live.bus import InMemoryLiveEventBus
from app.models import User


async def test_events_requires_a_token(client: AsyncClient) -> None:
    assert (await client.get("/events")).status_code == 401


async def test_events_is_behind_the_password_change_gate(
    authed_client: AsyncClient, authed_user: User, db_session: AsyncSession
) -> None:
    authed_user.must_change_password = True
    await db_session.commit()

    response = await authed_client.get("/events")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "PASSWORD_CHANGE_REQUIRED"


async def test_events_is_unavailable_when_the_hub_is_down(
    authed_client: AsyncClient, live_bus: InMemoryLiveEventBus
) -> None:
    live_bus.available = False

    response = await authed_client.get("/events")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "LIVE_EVENTS_UNAVAILABLE"


async def test_events_is_unavailable_when_disabled(
    app_with_queue: FastAPI, authed_client: AsyncClient
) -> None:
    base: Settings = get_settings()
    app_with_queue.dependency_overrides[get_settings] = lambda: base.model_copy(
        update={"live_events_enabled": False}
    )

    response = await authed_client.get("/events")

    assert response.status_code == 503
```

Run: `uv run pytest tests/test_events_api.py -v` → FAIL (`404` — no route).

- [ ] **Step 5: Write the route and register it**

Create `backend/app/api/routes/events.py`:

```python
"""`GET /events` — the per-user live-update stream (issue #48).

Behind the forced-password-change gate like every route outside `/auth`. Everything that
needs a status code is decided before the first byte (`.claude/rules/rag.md`'s pre-flight
split); after that the status is fixed at 200.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser
from app.api.routes.conversations import SSE_HEADERS
from app.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.db.session import get_sessionmaker
from app.live.bus import LiveEventHub
from app.live.stream import live_event_stream
from app.schemas.errors import ERROR_RESPONSES

router = APIRouter(prefix="/events", tags=["Live events"])


def get_live_hub(request: Request) -> LiveEventHub:
    """The process's hub, set by the lifespan."""
    hub: LiveEventHub = request.app.state.live_hub
    return hub


LiveHubDep = Annotated[LiveEventHub, Depends(get_live_hub)]


@router.get(
    "",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
    summary="Stream live-update signals for the caller",
    description=(
        "Server-sent events: `ready`, then `invalidate` ({kind, id, projectId}) for each "
        "visible change, and `resync` when events were dropped. Ids only — refetch through "
        "the REST routes. 503 means poll instead."
    ),
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 503)},
)
async def stream_events(
    current_user: CurrentUser,
    hub: LiveHubDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    if not settings.live_events_enabled or not hub.available:
        raise AppError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.LIVE_EVENTS_UNAVAILABLE,
            "Live updates are unavailable; poll instead.",
        )
    return StreamingResponse(
        live_event_stream(
            user=current_user,
            hub=hub,
            sessionmaker=get_sessionmaker(),
            heartbeat_seconds=settings.live_events_heartbeat_seconds,
            max_seconds=settings.live_events_max_stream_minutes * 60,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
```

If `SSE_HEADERS` is defined somewhere other than `app/api/routes/conversations.py`, import it
from where it is defined (`grep -rn "SSE_HEADERS =" app`).

Register it in `backend/app/main.py`: import `events` with the other routes and
`app.include_router(events.router)` after `notification_preferences.router`.

In `backend/tests/conftest.py`, in both the `app` and `app_with_queue` fixtures, add
`application.dependency_overrides[get_live_hub] = lambda: live_bus` (add `live_bus` as a
fixture parameter; import `get_live_hub` from `app.api.routes.events`).

Add `GET /events` to `backend/README.md`'s route table in its own "Live events" group.

- [ ] **Step 6: Run the tests, then the full suite**

Run: `uv run pytest tests/test_events_api.py tests/test_live_stream.py tests/test_api_model.py -v` → PASS.
Run: `uv run pytest -q` → PASS. `tests/test_audit_coverage.py` must still pass — `GET /events` is a read, so it needs no entry.

- [ ] **Step 7: Lint and commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy app tests`

```bash
git add backend/app/schemas/live.py backend/app/schemas/__init__.py backend/app/live/stream.py \
  backend/app/api/routes/events.py backend/app/core/errors.py backend/app/main.py \
  backend/tests/conftest.py backend/tests/test_live_stream.py backend/tests/test_events_api.py \
  backend/README.md
git commit -m "feat(live): stream id-only invalidations on GET /events

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The BFF abort signal

**Files:**
- Modify: `frontend/app/api/[...path]/route.ts` (`forward`)
- Test: `frontend/app/api/[...path]/route.test.ts`

**Interfaces:**
- Produces: `forward()` passes the incoming request's `signal` to `fetch`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/app/api/[...path]/route.test.ts`, reusing its `proxyRequest`, `context`
and `jsonOk` helpers:

```ts
it("forwards the browser's abort signal so a closed tab ends the backend stream", async () => {
  const spy = vi.fn(async () => jsonOk({}));
  vi.stubGlobal("fetch", spy);
  const request = proxyRequest("/api/events", "askrepo_access=jwt; askrepo_session=s%3D1");

  await GET(request, context(["events"]));

  const [, init] = spy.mock.calls[0] as unknown as [string, RequestInit];
  expect(init.signal).toBe(request.signal);
});
```

Run: `bunx vitest run "app/api/[...path]/route.test.ts"` → FAIL (`init.signal` is undefined).

- [ ] **Step 2: Pass the signal**

In `forward()`, add `signal: request.signal,` to the `fetch` options, with a comment:
"A closed tab aborts the backend request too — without it a long-lived stream (`/events`)
would run until its next heartbeat write failed."

Run the test → PASS. Then `bunx vitest run` (whole suite) → PASS.

- [ ] **Step 3: Lint and commit**

Run: `bun lint && bunx tsc --noEmit`

```bash
git add "frontend/app/api/[...path]/route.ts" "frontend/app/api/[...path]/route.test.ts"
git commit -m "fix(bff): forward the abort signal so closed tabs end backend streams

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `LiveEventsProvider`, and polling as the fallback

**Files:**
- Create: `frontend/lib/live/invalidation.ts` (+ `.test.ts`), `frontend/lib/live/backoff.ts` (+ `.test.ts`), `frontend/hooks/use-live-events.ts`, `frontend/components/live/live-events-provider.tsx` (+ `.test.tsx`)
- Modify: `frontend/components/layout/app-shell.tsx`, `frontend/hooks/use-projects.ts`, `frontend/hooks/use-checklist.ts`, `frontend/hooks/use-mock-data.ts`, `frontend/hooks/use-notifications.ts`, `frontend/lib/api/endpoints.ts`

**Interfaces:**
- Consumes: `parseSseStream(body, signal)` and `SseEvent` from `lib/ask/sse.ts`; `keys` from `lib/query/keys.ts`.
- Produces:
  - `type LiveKind = "project" | "checklist_module" | "mock_data" | "notification"`; `interface InvalidatePayload { kind: LiveKind; id: string; projectId: string | null }`
  - `keysToInvalidate(payload: InvalidatePayload): QueryKey[]`; `ALL_LIVE_KEYS: QueryKey[]`
  - `nextDelay(attempt: number, random?: () => number): number` — ms
  - `LiveEventsContext`, `useLiveEvents(): { connected: boolean }` (default `{ connected: false }` outside the provider)
  - `LiveEventsProvider({ children })`
  - `endpoints.events = "/events"`

- [ ] **Step 1: Write the failing pure-function tests**

`frontend/lib/live/invalidation.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { ALL_LIVE_KEYS, keysToInvalidate } from "@/lib/live/invalidation";
import { keys } from "@/lib/query/keys";

describe("keysToInvalidate", () => {
  it("refetches every project query for a project event", () => {
    expect(keysToInvalidate({ kind: "project", id: "p1", projectId: "p1" })).toEqual([
      keys.projects.all,
    ]);
  });

  it("refetches the module, the module list and its change sets", () => {
    expect(keysToInvalidate({ kind: "checklist_module", id: "m1", projectId: "p1" })).toEqual([
      keys.checklistModules.detail("m1"),
      keys.checklistModules.all,
      keys.checklistChangeSets.forModule("m1"),
    ]);
  });

  it("refetches mock data by module id", () => {
    expect(keysToInvalidate({ kind: "mock_data", id: "m1", projectId: "p1" })).toEqual([
      keys.mockData.detail("m1"),
      keys.mockDataChangeSets.forModule("m1"),
    ]);
  });

  it("refetches the bell for a notification", () => {
    expect(keysToInvalidate({ kind: "notification", id: "e1", projectId: "p1" })).toEqual([
      keys.notifications.all,
    ]);
  });

  it("names every top-level live key for a full refetch", () => {
    expect(ALL_LIVE_KEYS).toEqual([
      keys.projects.all,
      keys.checklistModules.all,
      keys.checklistChangeSets.all,
      ["mock-data"],
      ["mock-data-change-sets"],
      keys.notifications.all,
    ]);
  });
});
```

`frontend/lib/live/backoff.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { nextDelay } from "@/lib/live/backoff";

describe("nextDelay", () => {
  it("starts at one second and doubles", () => {
    const noJitter = () => 0.5;
    expect(nextDelay(0, noJitter)).toBe(1000);
    expect(nextDelay(1, noJitter)).toBe(2000);
    expect(nextDelay(3, noJitter)).toBe(8000);
  });

  it("caps at sixty seconds", () => {
    expect(nextDelay(20, () => 0.5)).toBe(60_000);
  });

  it("jitters by up to a fifth either way", () => {
    expect(nextDelay(2, () => 0)).toBe(3200);
    expect(nextDelay(2, () => 1)).toBe(4800);
  });
});
```

Run: `bunx vitest run lib/live` → FAIL (modules not found).

- [ ] **Step 2: Implement them**

`frontend/lib/live/invalidation.ts`:

```ts
import type { QueryKey } from "@tanstack/react-query";

import { keys } from "@/lib/query/keys";

export type LiveKind = "project" | "checklist_module" | "mock_data" | "notification";

/** The `invalidate` event's payload. Ids only — the refetch is what shows the change. */
export interface InvalidatePayload {
  kind: LiveKind;
  id: string;
  projectId: string | null;
}

/**
 * The queries one change makes stale. `mock_data`'s `id` is the checklist module id,
 * because mock data is keyed by module.
 */
export function keysToInvalidate(payload: InvalidatePayload): QueryKey[] {
  switch (payload.kind) {
    case "project":
      return [keys.projects.all];
    case "checklist_module":
      return [
        keys.checklistModules.detail(payload.id),
        keys.checklistModules.all,
        keys.checklistChangeSets.forModule(payload.id),
      ];
    case "mock_data":
      return [keys.mockData.detail(payload.id), keys.mockDataChangeSets.forModule(payload.id)];
    case "notification":
      return [keys.notifications.all];
  }
}

/**
 * Every live query, for `ready` and `resync`. `mockData` and `mockDataChangeSets` have no
 * `.all` key, so their prefixes are spelled here — the same arrays their `detail`/`forModule`
 * keys start with.
 */
export const ALL_LIVE_KEYS: QueryKey[] = [
  keys.projects.all,
  keys.checklistModules.all,
  keys.checklistChangeSets.all,
  ["mock-data"],
  ["mock-data-change-sets"],
  keys.notifications.all,
];
```

`frontend/lib/live/backoff.ts`:

```ts
const BASE_MS = 1000;
const CAP_MS = 60_000;
const JITTER = 0.2;

/**
 * Reconnect delay: one second doubling to a minute, ±20% so many tabs do not reconnect in
 * lockstep after an outage. `random` is injectable for tests.
 */
export function nextDelay(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(CAP_MS, BASE_MS * 2 ** attempt);
  if (base === CAP_MS) return CAP_MS;
  return Math.round(base * (1 - JITTER + random() * 2 * JITTER));
}
```

Run: `bunx vitest run lib/live` → PASS.

- [ ] **Step 3: Write the failing provider test**

`frontend/components/live/live-events-provider.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LiveEventsProvider } from "@/components/live/live-events-provider";
import { useLiveEvents } from "@/hooks/use-live-events";
import { keys } from "@/lib/query/keys";

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(frame));
      // Left open: a live stream does not end on its own.
    },
  });
}

function Probe() {
  const { connected } = useLiveEvents();
  return <p>{connected ? "connected" : "polling"}</p>;
}

function renderProvider(client: QueryClient) {
  return render(
    <QueryClientProvider client={client}>
      <LiveEventsProvider>
        <Probe />
      </LiveEventsProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("LiveEventsProvider", () => {
  it("connects on ready and invalidates on an event", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          sseBody([
            "event: ready\ndata: {}\n\n",
            'event: invalidate\ndata: {"kind":"project","id":"p1","projectId":"p1"}\n\n',
          ]),
          { status: 200, headers: { "content-type": "text/event-stream" } },
        ),
      ),
    );
    const client = new QueryClient();
    const spy = vi.spyOn(client, "invalidateQueries");

    renderProvider(client);

    expect(await screen.findByText("connected")).toBeInTheDocument();
    await waitFor(() =>
      expect(spy).toHaveBeenCalledWith({ queryKey: keys.projects.all }),
    );
  });

  it("stays on polling when the stream is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: { code: "LIVE_EVENTS_UNAVAILABLE", message: "poll" } },
          { status: 503 },
        ),
      ),
    );

    renderProvider(new QueryClient());

    expect(await screen.findByText("polling")).toBeInTheDocument();
  });
});
```

Run: `bunx vitest run components/live` → FAIL (module not found).

- [ ] **Step 4: Write the context hook and the provider**

`frontend/hooks/use-live-events.ts`:

```ts
"use client";

import { createContext, useContext } from "react";

export interface LiveEventsState {
  connected: boolean;
}

/** Outside the provider — signed-out pages, tests — hooks see `connected: false` and poll. */
export const LiveEventsContext = createContext<LiveEventsState>({ connected: false });

export function useLiveEvents(): LiveEventsState {
  return useContext(LiveEventsContext);
}
```

`frontend/components/live/live-events-provider.tsx`:

```tsx
"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { LiveEventsContext } from "@/hooks/use-live-events";
import { parseSseStream } from "@/lib/ask/sse";
import { endpoints } from "@/lib/api/endpoints";
import { nextDelay } from "@/lib/live/backoff";
import { ALL_LIVE_KEYS, type InvalidatePayload, keysToInvalidate } from "@/lib/live/invalidation";

/**
 * One live-update stream per tab (issue #48). Events are hints: each becomes a React
 * Query invalidation, and the REST refetch shows the change. While `connected` is false the
 * hooks poll exactly as they did before this provider existed.
 *
 * `fetch` rather than `EventSource`, so the BFF's refresh-on-401 applies and the backoff is
 * ours. The stream closes while the tab is hidden and reopens — with a full refetch on
 * `ready` — when it is visible again.
 */
export function LiveEventsProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let stopped = false;
    let controller: AbortController | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let attempt = 0;

    function invalidateAll() {
      for (const queryKey of ALL_LIVE_KEYS) void queryClient.invalidateQueries({ queryKey });
    }

    function schedule() {
      if (stopped || document.visibilityState === "hidden") return;
      timer = setTimeout(() => void connect(), nextDelay(attempt));
      attempt += 1;
    }

    async function connect() {
      if (stopped || document.visibilityState === "hidden") return;
      controller = new AbortController();
      try {
        const response = await fetch(`/api${endpoints.events}`, {
          signal: controller.signal,
          cache: "no-store",
          headers: { accept: "text/event-stream" },
        });
        // An unrefreshable session: stop, and let the normal session handling redirect.
        if (response.status === 401) return;
        if (!response.ok || !response.body) {
          schedule();
          return;
        }
        for await (const event of parseSseStream(response.body, controller.signal)) {
          if (event.event === "ready") {
            attempt = 0;
            setConnected(true);
            invalidateAll();
          } else if (event.event === "resync") {
            invalidateAll();
          } else if (event.event === "invalidate") {
            for (const queryKey of keysToInvalidate(event.data as InvalidatePayload)) {
              void queryClient.invalidateQueries({ queryKey });
            }
          }
        }
      } catch {
        // Aborted or dropped — fall through to reconnect.
      }
      setConnected(false);
      schedule();
    }

    function disconnect() {
      if (timer) clearTimeout(timer);
      timer = null;
      controller?.abort();
      controller = null;
      setConnected(false);
    }

    function onVisibilityChange() {
      if (document.visibilityState === "hidden") {
        disconnect();
      } else if (!controller) {
        attempt = 0;
        void connect();
      }
    }

    void connect();
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      stopped = true;
      document.removeEventListener("visibilitychange", onVisibilityChange);
      disconnect();
    };
  }, [queryClient]);

  return <LiveEventsContext.Provider value={{ connected }}>{children}</LiveEventsContext.Provider>;
}
```

Add `events: "/events",` to `endpoints` in `frontend/lib/api/endpoints.ts`.

If the `react-hooks/set-state-in-effect` lint rule rejects the `setConnected` calls, they are
inside async callbacks, not the effect body; if it still fires, move the state updates into a
`useReducer` dispatch and keep the same behaviour.

Run: `bunx vitest run components/live` → PASS.

- [ ] **Step 5: Mount it, and relax the polls while connected**

In `frontend/components/layout/app-shell.tsx`, wrap the shell's children (inside the existing
`SessionProvider`) in `<LiveEventsProvider>`.

In each hook, read `const { connected } = useLiveEvents();` and change the interval:

- `hooks/use-projects.ts` (`useProjects`, `useProject`): `return moving ? (connected ? 60_000 : 3000) : false;`
- `hooks/use-checklist.ts` (`useChecklistModule`) and `hooks/use-mock-data.ts` (`useMockDataDataset`): `query.state.data?.status === "generating" ? (connected ? 60_000 : 3000) : false`
- `hooks/use-notifications.ts`: `refetchInterval: connected ? CONNECTED_POLL_INTERVAL_MS : POLL_INTERVAL_MS`, with `const CONNECTED_POLL_INTERVAL_MS = 5 * 60_000;` beside `POLL_INTERVAL_MS`, on both hooks.

Update each hook's comment to say the interval is the fallback and the safety net for a lost
event. Keep `refetchIntervalInBackground: false`.

- [ ] **Step 6: Verify and commit**

Run: `bunx vitest run && bun lint && bunx tsc --noEmit && bun run build`
Expected: all green.

```bash
git add frontend/lib/live frontend/hooks frontend/components/live \
  frontend/components/layout/app-shell.tsx frontend/lib/api/endpoints.ts
git commit -m "feat(live): refetch on live events and poll only as the fallback

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: PRD, rules and docs, and final verification

**Files:** `docs/PRD.md`, `.claude/rules/live-events.md` (new), `.claude/rules/notifications.md`, `.claude/rules/frontend-bff.md`, `CLAUDE.md`, `docs/architecture.md`, `docs/langgraph.md`, `docs/notifications.md`, `CHANGELOG.md`.

Every edit states a fact about the tree; verify each against the code before writing it.

- [ ] **Step 1: `docs/PRD.md`**

1. **§2.1 Phase 2.3** — find "In-app delivery is a polled unread count at 60 seconds, and
   deliberately no socket." Keep the sentence, and append an amendment paragraph dated
   2026-09-27: the per-user stream now exists for job status (issue #48), with its own failure
   handling — ids-only events, per-event access re-check, fail-open to polling — so the bell
   rides it instead of a second mechanism; the 60 s poll is the fallback (5 min while
   connected). Name spec §4.4/§5.3 as where the original lifecycle objection is answered.
2. **§5** — where the Kafka topics are listed, add `askrepo.live.events` (one partition, one
   hour retention, consumed by every API process with no consumer group).
3. **§6** — after the profile page's amendment paragraph, add: "**Phase 2.3 amendment — live
   updates (in progress, 2026-09-27).** Not a milestone of its own: job status and the bell
   pushed over one per-user SSE stream fed by Kafka, with polling as the fallback. See §2.1."

- [ ] **Step 2: The new rule, `.claude/rules/live-events.md`**

Write it with the five rules from spec §7, each with its reason, in the register of
`.claude/rules/notifications.md` (a scope line naming `app/live/`, `app/api/routes/events.py`,
`live_event_visible_to`, the staging sites, `components/live/`; then one section per rule).
Include: events are ids never content; stage never publish, and why the commit hook is the
mechanism; every displayed state write stages, and `tests/test_live_event_sites.py` pins the
existing sites; visibility only in `access.py`, re-checked per event, no admin bypass for
notifications; the stream is a hint, so polling must keep working.

- [ ] **Step 3: The other rules and `CLAUDE.md`**

- `.claude/rules/notifications.md` — in rule 2's section, add one paragraph: the fan-out also
  stages a `notification` live event carrying the resolved recipients, which leaves only on
  commit — the same transaction the rows ride in.
- `.claude/rules/frontend-bff.md` — the catch-all relays any `text/event-stream` unbuffered
  (the answer stream and `/events`), and forwards the request's abort signal so a closed tab
  ends the backend request.
- `CLAUDE.md` — change "Sixteen rule files" to "Seventeen rule files", add a `live-events.md`
  row to the table ("Anything under `app/live/`, `GET /events`, a status write the frontend
  shows, or `components/live/` — ids only, stage never publish, visibility in `access.py`,
  polling stays the fallback"), and add a short "### Live updates are hints over Kafka"
  section under Architecture linking `.claude/rules/live-events.md` and saying the API
  process now consumes Kafka as well as producing to it. The "Redis has exactly two readers"
  text stays unchanged — verify it is still true.

- [ ] **Step 4: Reference docs and CHANGELOG**

- `docs/architecture.md` — the API process consumes `askrepo.live.events`; the event flow
  (stage → commit hook → Kafka → hub → `/events` → invalidate → REST refetch).
- `docs/langgraph.md` — a section for the second SSE contract: `ready` first, `invalidate`
  `{kind, id, projectId}`, `resync`, `: ping` heartbeats; no terminator (the stream ends by
  disconnect, re-check failure or the cap).
- `docs/notifications.md` — the bell is pushed over `/events`; the 60 s poll is the fallback.
- `CHANGELOG.md` under `## [Unreleased]`:
  - `### Added`: "**Live updates.** Project status and reindex, checklist and mock-data
    generation, and the notification bell update the moment they change, over one per-user
    stream (`GET /events`). Screens fall back to polling when it is unavailable." ; "`GET /events`,
    `ErrorCode.LIVE_EVENTS_UNAVAILABLE`, and the settings `LIVE_EVENTS_ENABLED`,
    `KAFKA_LIVE_EVENTS_TOPIC`, `LIVE_EVENTS_HEARTBEAT_SECONDS`, `LIVE_EVENTS_MAX_STREAM_MINUTES`."
  - `### Changed`: "While the live stream is connected, job screens poll every 60 s instead of
    3 s and the bell every 5 min instead of 60 s."
  - `### Fixed`: "The frontend's API proxy now forwards the browser's abort signal, so closing
    a tab ends the backend request."

- [ ] **Step 5: Full verification**

Run from the repo root: `make check` → green. Paste the tail into the report.
Run from `frontend/`: `bun run build` → succeeds.
Run from `backend/`: `uv run pytest -m integration tests/test_live_kafka_integration.py -v` → PASS (Kafka is running locally).

Do not start dev servers, Docker services or Ollama. The manual check — open two browsers,
start a reindex in one, watch the other update without polling; stop Kafka and confirm the
screens still update by polling — is handed to the user.

- [ ] **Step 6: Commit**

```bash
git add docs .claude CLAUDE.md CHANGELOG.md
git commit -m "docs(live): record live updates and amend the no-socket decision

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
