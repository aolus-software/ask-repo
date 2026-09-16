"""Retention: an operator sets a window; nobody erases a row."""

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent
from app.repositories.audit_event import AuditEventRepository


async def test_delete_older_than_takes_only_a_cutoff(db_session: AsyncSession) -> None:
    """The one delete path cannot be aimed at anyone's entries.

    No actor filter and no event-type filter is what keeps the append-only claim true
    in the presence of a prune.
    """
    now = datetime.now(UTC)
    db_session.add_all(
        [
            AuditEvent(
                event_type="auth.login.succeeded",
                outcome="success",
                details={},
                created_at=now - timedelta(days=40),
            ),
            AuditEvent(
                event_type="auth.login.succeeded",
                outcome="success",
                details={},
                created_at=now - timedelta(days=5),
            ),
        ]
    )
    await db_session.commit()

    pruned = await AuditEventRepository(db_session).delete_older_than(now - timedelta(days=30))
    await db_session.commit()

    assert pruned == 1
    remaining = (await db_session.execute(AuditEvent.__table__.select())).all()
    assert len(remaining) == 1


def test_retention_is_off_by_default() -> None:
    """A fresh instance must not silently start discarding the one record whose
    purpose is being the record."""
    from app.config import Settings

    assert Settings().audit_retention_days == 0
