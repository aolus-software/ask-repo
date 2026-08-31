"""QA pair persistence.

Every read is scoped by a `ProjectScope` the caller obtained from
`access.resolve_project_scope`. The scope is applied here, at the layer that builds
the query, so no caller can forget it — `docs/PRD.md` §7's phase-2 readiness
criterion is that read scoping lives in exactly one function and is confirmed by
grep.
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, Select, func, select, update

from app.core.access import ProjectScope
from app.models.qa_pair import QAPair
from app.repositories.base import BaseRepository


class QAPairRepository(BaseRepository[QAPair]):
    """Reads and writes QA pairs, always inside a project scope."""

    model = QAPair

    # Allowlisted, never interpolated: passing a query parameter into
    # getattr(Model, ...) unchecked exposes every column on the table.
    SORTABLE_FIELDS = frozenset(
        {"created_at", "updated_at", "last_run_at", "module", "status"}
    )

    def _scoped(
        self,
        scope: ProjectScope,
        *,
        project_id: uuid.UUID | None = None,
        module: str | None = None,
        tag: str | None = None,
        source: str | None = None,
        status: str | None = None,
        created_by: uuid.UUID | None = None,
        search: str | None = None,
    ) -> Select[tuple[QAPair]]:
        """The base query the page, the count, and the export are all built from."""
        statement = self.active_select()
        if not scope.unrestricted:
            # `in_` over an empty collection renders `WHERE false`, which is the
            # wanted behaviour: an empty scope means no access, never all of it.
            statement = statement.where(QAPair.project_id.in_(scope.ids))
        if project_id is not None:
            # A filter *within* the scope, not the scope itself. A phase-2 caller
            # naming a project they cannot see gets an empty page, not rows.
            statement = statement.where(QAPair.project_id == project_id)
        if module:
            statement = statement.where(QAPair.module.ilike(f"%{module.strip()}%"))
        if tag:
            statement = statement.where(QAPair.tags.contains([tag]))
        if source:
            statement = statement.where(QAPair.source == source)
        if status:
            statement = statement.where(QAPair.status == status)
        if created_by is not None:
            statement = statement.where(QAPair.created_by == created_by)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                QAPair.question.ilike(term) | QAPair.answer.ilike(term)
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
        module: str | None = None,
        tag: str | None = None,
        source: str | None = None,
        status: str | None = None,
        created_by: uuid.UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[QAPair], int]:
        """One page of pairs, plus the unpaginated total for the same filters."""
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"cannot sort qa pairs by {sort!r}")

        base = self._scoped(
            scope,
            project_id=project_id,
            module=module,
            tag=tag,
            source=source,
            status=status,
            created_by=created_by,
            search=search,
        )
        column = getattr(QAPair, sort)
        # `id` breaks ties so a page boundary is stable across requests: `module`
        # and `status` are far from unique, and without it two pages can show the
        # same row or skip one.
        rows = await self.session.execute(
            base.order_by(column.desc() if descending else column.asc(), QAPair.id.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        total = await self.session.execute(
            select(func.count()).select_from(base.subquery())
        )
        return list(rows.scalars().all()), total.scalar_one()

    async def list_all(
        self,
        *,
        scope: ProjectScope,
        sort: str,
        descending: bool,
        project_id: uuid.UUID | None = None,
        module: str | None = None,
        tag: str | None = None,
        source: str | None = None,
        status: str | None = None,
        created_by: uuid.UUID | None = None,
        search: str | None = None,
        cap: int,
    ) -> list[QAPair]:
        """Every matching pair, up to `cap + 1` rows.

        The export reads through here. One extra row is fetched deliberately: the
        service compares the length against the cap to decide whether to refuse,
        so it never has to run a second COUNT over the same filters.
        """
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"cannot sort qa pairs by {sort!r}")

        base = self._scoped(
            scope,
            project_id=project_id,
            module=module,
            tag=tag,
            source=source,
            status=status,
            created_by=created_by,
            search=search,
        )
        column = getattr(QAPair, sort)
        rows = await self.session.execute(
            base.order_by(
                column.desc() if descending else column.asc(), QAPair.id.asc()
            ).limit(cap + 1)
        )
        return list(rows.scalars().all())

    async def count_for_project(self, project_id: uuid.UUID) -> int:
        """How many live pairs a project has. Used by the project detail response."""
        result = await self.session.execute(
            select(func.count()).select_from(
                self.active_select().where(QAPair.project_id == project_id).subquery()
            )
        )
        return result.scalar_one()

    async def distinct_tags(self, *, scope: ProjectScope) -> list[str]:
        """Every tag in use across the caller's scope, sorted, for the filter."""
        base = self._scoped(scope).subquery()
        tag = func.unnest(base.c.tags).column_valued("tag")
        result = await self.session.execute(select(tag).distinct().order_by(tag))
        return list(result.scalars().all())

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every pair against a project, for every creator.

        `updated_at` is set explicitly and from `func.now()` — the database clock.
        `TimestampMixin.onupdate` renders during an ORM flush and does not fire on a
        bulk `UPDATE` (`.claude/rules/persistence.md`), and mixing Python's clock
        with the server default used everywhere else lets an update land before the
        `created_at` of the row it is updating.

        Not scoped by creator, deliberately: the project was shared, so its pairs
        belong to several people and all of them go.
        """
        result = await self.session.execute(
            update(QAPair)
            .where(QAPair.project_id == project_id, QAPair.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        # `execute` is typed as returning `Result`, which declares no `rowcount`; a
        # bulk UPDATE really returns a `CursorResult`. Same cast as
        # `ConversationRepository.soft_delete_for_project`.
        return cast(CursorResult[Any], result).rowcount
