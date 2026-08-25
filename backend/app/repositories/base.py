"""The base repository — and the single place the soft-delete filter is applied.

`docs/PRD.md:323` requires every query to exclude soft-deleted rows. Relying on each
query to remember would make that a convention; `active_select()` makes it structural.
A caller that genuinely wants deleted rows uses a differently named method, so the
intent is visible at the call site and greppable.

Repositories are the only layer allowed to import `select` / `insert` / `update`.
"""

import uuid
from datetime import UTC, datetime
from typing import Protocol, cast

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

from app.models.base import Base, SoftDeleteMixin


class _HasId(Protocol):
    """Structural shape assumed by the primary-key lookups below.

    `Base` itself declares no `id` column — each concrete model does, independently —
    so `ModelT` cannot be bound to something that already promises `.id`. This Protocol
    documents that local assumption at the two call sites that need it, instead of a
    blanket `# type: ignore` that would silence unrelated attribute typos too.
    """

    id: Mapped[uuid.UUID]


class BaseRepository[ModelT: Base]:
    """CRUD shared by every repository. Subclasses set `model`.

    `ModelT` is bound to `Base` rather than `Any` so that a subclass such as
    `UserRepository(BaseRepository[User])` gets real return types — `get()` returns
    `User | None`, not `Any` — which keeps mypy strict checking every call site that
    consumes the result, instead of silently stopping at the repository boundary.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def active_select(self) -> Select[tuple[ModelT]]:
        """A `SELECT` that already excludes soft-deleted rows.

        Every read in every repository starts here. Models without `SoftDeleteMixin`
        (`refresh_tokens`) get a plain select, so the method is safe to use uniformly.
        """
        statement = select(self.model)
        if issubclass(self.model, SoftDeleteMixin):
            statement = statement.where(self.model.deleted_at.is_(None))
        return statement

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Fetch by primary key, excluding soft-deleted rows."""
        model_with_id = cast(type[_HasId], self.model)
        result = await self.session.execute(
            self.active_select().where(model_with_id.id == entity_id)
        )
        return result.scalar_one_or_none()

    async def get_including_deleted(self, entity_id: uuid.UUID) -> ModelT | None:
        """Fetch by primary key without the soft-delete filter. Name says so on purpose."""
        model_with_id = cast(type[_HasId], self.model)
        result = await self.session.execute(select(self.model).where(model_with_id.id == entity_id))
        return result.scalar_one_or_none()

    async def add(self, entity: ModelT) -> ModelT:
        """Stage an insert. The caller's service owns the commit."""
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def soft_delete(self, entity: ModelT) -> None:
        """Mark a row deleted. The caller's service owns the commit.

        Guarded at runtime rather than by types alone: a model without
        `SoftDeleteMixin` has no `deleted_at` column, and because SQLAlchemy
        instances have no `__slots__`, assigning one would land in `__dict__`,
        persist nothing, and raise nothing — a delete that silently does not happen.
        """
        if not isinstance(entity, SoftDeleteMixin):
            raise TypeError(
                f"{type(entity).__name__} does not support soft delete: it has no deleted_at column"
            )
        entity.deleted_at = datetime.now(UTC)
        await self.session.flush()
