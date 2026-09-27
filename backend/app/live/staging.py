"""Stage on the session, publish on commit — the only way a live event leaves a process.

A service never publishes: it stages. The `after_commit` hook hands the staged events to the
process's publisher, and `after_soft_rollback` drops them, so a change that rolled back can never
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
from sqlalchemy.orm import Session, SessionTransaction

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
    global _publisher
    _publisher = publisher


def get_live_publisher() -> LivePublisher:
    """The process-wide publisher."""
    return _publisher


def stage_live_event(session: AsyncSession | Session, live_event: LiveEvent) -> None:
    """Queue an event to publish if, and only if, this session's transaction commits.

    A repeat of the same event in one transaction is kept once. Begins a transaction if none
    is open, so rollback events fire reliably.
    """
    # Ensure a transaction is open so that a later rollback triggers after_soft_rollback;
    # a rollback with no open transaction fires no event and staged events would leak.
    sync_session = session.sync_session if isinstance(session, AsyncSession) else session
    if not sync_session.in_transaction():
        sync_session.begin()

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


@event.listens_for(Session, "after_soft_rollback")
def _discard_staged(session: Session, previous_transaction: SessionTransaction) -> None:
    session.info.pop(_STAGED_KEY, None)
