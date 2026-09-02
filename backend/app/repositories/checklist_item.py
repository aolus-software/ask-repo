"""Queries over `checklist_items`.

Every read is scoped by a `ProjectScope` from `access.resolve_project_scope`, applied
here so no caller can forget it. `project_id` is denormalised onto the row precisely so
this layer can filter across modules without a join (spec 3.2).
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, Select, func, select, update

from app.core.access import ProjectScope
from app.models.checklist import ChecklistItem
from app.repositories.base import BaseRepository


class ChecklistItemRepository(BaseRepository[ChecklistItem]):
    """Reads and writes for checklist items, always inside a project scope."""

    model = ChecklistItem

    SORTABLE_FIELDS = frozenset(
        {"feature", "test_name", "status", "position", "created_at", "updated_at"}
    )

    def _scoped(
        self,
        scope: ProjectScope,
        *,
        project_id: uuid.UUID | None = None,
        module_id: uuid.UUID | None = None,
        feature: str | None = None,
        status: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> Select[tuple[ChecklistItem]]:
        """The base query the page, the count, and the export are all built from."""
        statement = self.active_select()
        if not scope.unrestricted:
            statement = statement.where(ChecklistItem.project_id.in_(scope.ids))
        if project_id is not None:
            statement = statement.where(ChecklistItem.project_id == project_id)
        if module_id is not None:
            statement = statement.where(ChecklistItem.module_id == module_id)
        if feature:
            statement = statement.where(ChecklistItem.feature.ilike(f"%{feature.strip()}%"))
        if status:
            statement = statement.where(ChecklistItem.status == status)
        if source:
            statement = statement.where(ChecklistItem.source == source)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                ChecklistItem.test_name.ilike(term)
                | ChecklistItem.expected_result.ilike(term)
                | ChecklistItem.current_result.ilike(term)
            )
        return statement

    async def list_page(
        self,
        *,
        scope: ProjectScope,
        page: int,
        limit: int,
        sort: str,
        descending: bool,
        project_id: uuid.UUID | None = None,
        module_id: uuid.UUID | None = None,
        feature: str | None = None,
        status: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> tuple[list[ChecklistItem], int]:
        """One page of items, plus the unpaginated total for the same filters."""
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"cannot sort checklist items by {sort!r}")

        base = self._scoped(
            scope,
            project_id=project_id,
            module_id=module_id,
            feature=feature,
            status=status,
            source=source,
            search=search,
        )
        column = getattr(ChecklistItem, sort)
        rows = await self.session.execute(
            base.order_by(column.desc() if descending else column.asc(), ChecklistItem.id.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        total = await self.session.execute(select(func.count()).select_from(base.subquery()))
        return list(rows.scalars().all()), total.scalar_one()

    async def list_all(
        self,
        *,
        scope: ProjectScope,
        cap: int,
        project_id: uuid.UUID | None = None,
        module_id: uuid.UUID | None = None,
        feature: str | None = None,
        status: str | None = None,
        source: str | None = None,
        search: str | None = None,
    ) -> list[ChecklistItem]:
        """Every matching item, up to `cap + 1` rows, in the grid's own order.

        No `sort` parameter, unlike `list_page`: the export's order is fixed at
        (feature, position) so the sheet reads in the order a tester works (spec 7).
        One extra row is fetched so the service can refuse an over-large export
        without a second COUNT.
        """
        base = self._scoped(
            scope,
            project_id=project_id,
            module_id=module_id,
            feature=feature,
            status=status,
            source=source,
            search=search,
        )
        rows = await self.session.execute(
            base.order_by(
                ChecklistItem.feature.asc(),
                ChecklistItem.position.asc(),
                ChecklistItem.id.asc(),
            ).limit(cap + 1)
        )
        return list(rows.scalars().all())

    async def list_for_module(self, module_id: uuid.UUID) -> list[ChecklistItem]:
        """Every live item of one module, in grid order.

        Unscoped on purpose: the caller has already resolved the module through
        `ChecklistModuleRepository.get_in_scope`, so scoping again here would be a
        second read-scoping site -- the thing `docs/PRD.md` 7 forbids.
        """
        rows = await self.session.execute(
            self.active_select()
            .where(ChecklistItem.module_id == module_id)
            .order_by(
                ChecklistItem.feature.asc(),
                ChecklistItem.position.asc(),
                ChecklistItem.id.asc(),
            )
        )
        return list(rows.scalars().all())

    async def get_in_scope(
        self, item_id: uuid.UUID, *, scope: ProjectScope
    ) -> ChecklistItem | None:
        """One item, if it is in the caller's scope."""
        result = await self.session.execute(self._scoped(scope).where(ChecklistItem.id == item_id))
        return result.scalar_one_or_none()

    async def next_position(self, *, module_id: uuid.UUID, feature: str) -> int:
        """Where the next item in this feature goes. Zero when the feature is new.

        Filters `deleted_at` explicitly rather than through `active_select()`: this is a
        scalar aggregate, and `active_select()` returns a full-row `Select[tuple[ChecklistItem]]`
        that cannot express `func.max(...)`. The filter is therefore remembered here rather
        than structural, which is why it is called out.
        """
        result = await self.session.execute(
            select(func.max(ChecklistItem.position)).where(
                ChecklistItem.module_id == module_id,
                ChecklistItem.feature == feature,
                ChecklistItem.deleted_at.is_(None),
            )
        )
        highest = result.scalar_one_or_none()
        return 0 if highest is None else highest + 1

    async def status_counts(
        self, *, module_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, dict[str, int]]:
        """Per-module counts by status, in one query.

        One query rather than one per module: the module list renders these on every
        row, and an N+1 there is the difference between one round trip and twenty-five.

        Filters `deleted_at` explicitly rather than through `active_select()`, for the same
        reason `next_position` does: a grouped projection cannot come from a full-row select.
        """
        if not module_ids:
            return {}
        result = await self.session.execute(
            select(ChecklistItem.module_id, ChecklistItem.status, func.count())
            .where(ChecklistItem.module_id.in_(module_ids), ChecklistItem.deleted_at.is_(None))
            .group_by(ChecklistItem.module_id, ChecklistItem.status)
        )
        counts: dict[uuid.UUID, dict[str, int]] = {}
        for module_id, status, count in result.all():
            counts.setdefault(module_id, {})[status] = count
        return counts

    async def soft_delete_for_module(self, module_id: uuid.UUID) -> int:
        """Soft-delete every item of a module. `updated_at` set explicitly (bulk)."""
        result = await self.session.execute(
            update(ChecklistItem)
            .where(ChecklistItem.module_id == module_id, ChecklistItem.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every item of a project, for every creator."""
        result = await self.session.execute(
            update(ChecklistItem)
            .where(ChecklistItem.project_id == project_id, ChecklistItem.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
