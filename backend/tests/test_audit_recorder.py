"""The audit trail: the append-only model, and the repository built over it."""

import logging

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


async def test_the_table_carries_neither_mixin() -> None:
    """Append-only is a property of the model, not a convention.

    Without `SoftDeleteMixin` there is no soft-delete path to reach these rows
    through at all, because `BaseRepository.active_select()` only filters when the
    mixin is present. Without `TimestampMixin` there is no `updated_at`, which a row
    that is never mutated has no business carrying.
    """
    from app.models import AuditEvent
    from app.models.base import SoftDeleteMixin, TimestampMixin

    assert not issubclass(AuditEvent, SoftDeleteMixin)
    assert not issubclass(AuditEvent, TimestampMixin)
    assert "deleted_at" not in AuditEvent.__table__.columns
    assert "updated_at" not in AuditEvent.__table__.columns
    assert "created_at" in AuditEvent.__table__.columns


async def test_the_repository_has_no_update_path() -> None:
    """One delete path, driven by a cutoff, and no update path at all.

    `delete_older_than` takes a cutoff and nothing else — no actor filter, no
    event-type filter — so the one code path that removes these rows cannot be aimed
    at anyone's entries.
    """
    import inspect

    from app.repositories.audit_event import AuditEventRepository

    assert not hasattr(AuditEventRepository, "update")
    signature = inspect.signature(AuditEventRepository.delete_older_than)
    assert list(signature.parameters) == ["self", "cutoff"]


def test_details_builds_the_changed_envelope() -> None:
    from app.core.audit import AuditEntry, AuditEventType

    entry = AuditEntry(
        event_type=AuditEventType.USER_UPDATED,
        changed={"isAdmin": (False, True)},
    )

    assert entry.details() == {"changed": {"isAdmin": {"before": False, "after": True}}}


def test_details_rejects_a_field_outside_the_allowlist() -> None:
    """A generic differ would write `password_hash` the moment someone adds a column.

    The allowlist is what makes a new column invisible to the trail until it is named.
    """
    from app.core.audit import AuditEntry, AuditEventType

    entry = AuditEntry(
        event_type=AuditEventType.USER_UPDATED,
        changed={"passwordHash": ("old", "new")},
    )

    with pytest.raises(ValueError, match="passwordHash"):
        entry.details()


def test_details_rejects_a_context_key_outside_the_allowlist() -> None:
    from app.core.audit import AuditEntry, AuditEventType

    entry = AuditEntry(
        event_type=AuditEventType.AUTH_LOGIN_SUCCEEDED,
        context={"password": "hunter2"},
    )

    with pytest.raises(ValueError, match="password"):
        entry.details()


def test_details_omits_an_empty_changed_block() -> None:
    from app.core.audit import AuditEntry, AuditEventType

    entry = AuditEntry(event_type=AuditEventType.USER_DEACTIVATED)

    assert entry.details() == {}


def test_details_truncates_past_the_cap() -> None:
    """A payload too large to store is replaced, not silently written half-way."""
    from app.core.audit import AuditEntry, AuditEventType

    entry = AuditEntry(
        event_type=AuditEventType.ROLE_UPDATED,
        changed={"permissions": ([], ["perm" + str(n) for n in range(5000)])},
    )

    assert entry.details() == {"truncated": True}


async def test_record_writes_a_row(
    sessionmaker: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    from app.core.audit import AuditEntry, AuditEventType, AuditRecorder
    from app.models import AuditEvent

    recorder = AuditRecorder(sessionmaker)

    await recorder.record(
        AuditEntry(
            event_type=AuditEventType.AUTH_LOGIN_SUCCEEDED,
            actor_user_id=None,
            actor_email="someone@example.com",
            ip_address="10.0.0.9",
            context={"mustChangePassword": False},
        )
    )

    rows = (await db_session.execute(AuditEvent.__table__.select())).all()
    assert len(rows) == 1
    assert rows[0].event_type == AuditEventType.AUTH_LOGIN_SUCCEEDED
    assert rows[0].actor_email == "someone@example.com"
    assert rows[0].ip_address == "10.0.0.9"
    assert rows[0].details == {"mustChangePassword": False}
    # The actor was unknown; nothing was invented to fill the column.
    assert rows[0].actor_user_id is None


async def test_record_swallows_a_write_failure_and_logs_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Spec §4.2's trade-off, as a test.

    A login must not fail because a log write did. The accepted consequence is a
    silently missing row — so the WARNING is the only trace, and it has to be there.
    """
    from app.core.audit import AuditEntry, AuditEventType, AuditRecorder

    class ExplodingSessionmaker:
        def __call__(self) -> object:
            raise RuntimeError("postgres is gone")

    recorder = AuditRecorder(ExplodingSessionmaker())  # type: ignore[arg-type]  # deliberate failure double

    with caplog.at_level(logging.WARNING):
        await recorder.record(AuditEntry(event_type=AuditEventType.AUTH_LOGOUT))

    assert "audit write failed" in caplog.text
    assert AuditEventType.AUTH_LOGOUT in caplog.text


async def test_record_swallows_an_invalid_payload(caplog: pytest.LogCaptureFixture) -> None:
    """An allowlist violation is a programming error, but it still must not 500 a user.

    It is loud in the log and caught by `tests/test_audit_write_sites.py` in CI.
    """
    from app.core.audit import AuditEntry, AuditEventType, AuditRecorder

    recorder = AuditRecorder(None)  # type: ignore[arg-type]  # never reached: details() raises first

    with caplog.at_level(logging.WARNING):
        await recorder.record(
            AuditEntry(event_type=AuditEventType.AUTH_LOGOUT, changed={"nope": (1, 2)})
        )

    assert "audit write failed" in caplog.text
