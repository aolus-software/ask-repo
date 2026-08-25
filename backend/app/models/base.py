"""Declarative base and the column mixins every table shares.

The explicit naming convention matters more than it looks: without it, Postgres
names constraints itself, Alembic autogenerate produces churn on every run, and a
migration cannot reliably drop a constraint it did not name.
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Root of every ORM model. `metadata` is Alembic's autogenerate target."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TimestampMixin:
    """`created_at` / `updated_at`, both timezone-aware.

    `onupdate=func.now()` is a **server-side SQL expression**, not a Python-side
    default: SQLAlchemy renders `now()` directly into the `UPDATE` it builds during
    an ORM flush. It does NOT fire for a bulk `UPDATE` Core statement, because that
    path never goes through the ORM's per-row `UPDATE` construction that would apply
    it. Repository methods issuing bulk updates set `updated_at` explicitly — see
    `.claude/rules/persistence.md`.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class SoftDeleteMixin:
    """`deleted_at`. Rows are never removed; queries filter `deleted_at IS NULL`.

    Carrying this mixin is what makes `BaseRepository.active_select()` apply the
    filter, so a model that should be soft-deletable and lacks it will silently
    return deleted rows.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
