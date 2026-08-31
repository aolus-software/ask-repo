"""Queries over `users`."""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, or_, select

from app.models.user import User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    """Reads and writes for accounts. All reads exclude soft-deleted rows."""

    model = User

    # Allowlisted rather than free-form: `sort` arrives from a query parameter, and
    # interpolating an arbitrary column name would expose `password_hash` ordering
    # at best and be an injection point at worst.
    SORTABLE_FIELDS = frozenset({"name", "email", "created_at", "last_login_at"})

    async def get_by_email(self, email: str) -> User | None:
        """Find a live account by address. Normalises case, as storage does."""
        result = await self.session.execute(
            self.active_select().where(User.email == email.strip().lower())
        )
        return result.scalar_one_or_none()

    async def email_exists(self, email: str) -> bool:
        """Whether a live account already uses this address."""
        return (await self.get_by_email(email)) is not None

    async def list_page(
        self, *, page: int, limit: int, search: str | None, sort: str, descending: bool
    ) -> tuple[Sequence[User], int]:
        """One page of accounts plus the total matching count.

        The total uses the same filters as the rows, so the last page is never empty.
        """
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"unknown sort field: {sort}")

        statement = self.active_select()
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(or_(User.name.ilike(pattern), User.email.ilike(pattern)))

        count_result = await self.session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        total = count_result.scalar_one()

        column = getattr(User, sort)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * limit).limit(limit)

        rows = await self.session.execute(statement)
        return rows.scalars().all(), total

    async def by_ids(self, ids: set[uuid.UUID]) -> Sequence[User]:
        """Every live user among `ids`, in one query rather than N.

        Used by the QA export to resolve `created_by`/`reviewed_by` to names — a
        5,000-row export otherwise costs 10,000 round trips if this were a loop.
        """
        if not ids:
            return []
        result = await self.session.execute(self.active_select().where(User.id.in_(ids)))
        return result.scalars().all()

    async def count_active_admins(self, excluding: uuid.UUID | None = None) -> int:
        """How many live admins exist, optionally ignoring one.

        `excluding` answers "would this operation leave the instance with none?" — the
        last-admin guard (D17), which exists because the alternative is recovery by
        manual SQL.
        """
        statement = self.active_select().where(User.is_admin.is_(True))
        if excluding is not None:
            statement = statement.where(User.id != excluding)
        result = await self.session.execute(select(func.count()).select_from(statement.subquery()))
        return result.scalar_one()
