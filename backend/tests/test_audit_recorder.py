"""The audit trail: the append-only model, and the repository built over it."""


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
