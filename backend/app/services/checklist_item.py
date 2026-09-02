"""Item business rules.

Two writes with two different rules, and the split is the design (spec 2.5):

- `update` changes what a test *expects*, and needs `created_by` or `is_admin`.
- `set_result` records what a tester *observed*, and is open to everyone.

A tester who did not author the checklist must be able to record what they saw without
being able to quietly rewrite the expectation -- otherwise the cheapest way to make a
failing test pass is to edit what it was supposed to do.
"""

import builtins
import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.checklist import (
    ChecklistItem,
    ChecklistItemSource,
    ChecklistItemStatus,
    ChecklistModule,
)
from app.repositories.checklist_item import ChecklistItemRepository
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.project import ProjectRepository
from app.repositories.user import UserRepository
from app.schemas.checklist import (
    ChecklistItemCreateRequest,
    ChecklistItemListQuery,
    ChecklistItemResponse,
    ChecklistItemResultRequest,
    ChecklistItemUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse
from app.services.checklist_export import build_workbook

DEFAULT_SORT = "position"


class ChecklistItemService:
    """CRUD over test cases, the ungated result write, and the export."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.items = ChecklistItemRepository(session)
        self.modules = ChecklistModuleRepository(session)
        self.projects = ProjectRepository(session)
        self.users = UserRepository(session)

    async def list(
        self, query: ChecklistItemListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[ChecklistItemResponse]:
        """A page of items the caller may read."""
        try:
            rows, total = await self.items.list_page(
                scope=access.resolve_project_scope(actor),
                page=query.page,
                limit=query.limit,
                sort=query.sort or DEFAULT_SORT,
                descending=query.sort_direction == "desc",
                project_id=query.project_id,
                module_id=query.module_id,
                feature=query.feature,
                status=query.status.value if query.status else None,
                source=query.source.value if query.source else None,
                search=query.search,
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_SORT_FIELD, str(error)
            ) from error
        return PaginatedResponse.build(
            [ChecklistItemResponse.model_validate(row) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def create(
        self, payload: ChecklistItemCreateRequest, *, actor: AuthenticatedUser
    ) -> ChecklistItemResponse:
        """Add a test case by hand.

        `source` is set here and never taken from the request: `generated` means "a
        model proposed this and a human reviewed it", and a client that could claim it
        would make the column meaningless.
        """
        module = await self._require_readable_module(payload.module_id, actor)
        item = await self.items.add(
            ChecklistItem(
                id=uuid.uuid4(),
                module_id=module.id,
                # Denormalised from the module at insert, never updated: a module
                # cannot move between projects.
                project_id=module.project_id,
                feature=payload.feature.strip(),
                test_name=payload.test_name.strip(),
                expected_result=payload.expected_result.strip(),
                current_result=None,
                status=ChecklistItemStatus.UNTESTED.value,
                notes=payload.notes,
                source=ChecklistItemSource.MANUAL.value,
                position=await self.items.next_position(
                    module_id=module.id, feature=payload.feature.strip()
                ),
                created_by=actor.id,
            )
        )
        await self.session.commit()
        return ChecklistItemResponse.model_validate(item)

    async def update(
        self,
        item_id: uuid.UUID,
        payload: ChecklistItemUpdateRequest,
        *,
        actor: AuthenticatedUser,
    ) -> ChecklistItemResponse:
        """Change what a test expects. Gated on `created_by`/`is_admin`."""
        item = await self._require_readable(item_id, actor)
        self._require_destructive_rights(item, actor)
        if payload.feature is not None:
            item.feature = payload.feature.strip()
        if payload.test_name is not None:
            item.test_name = payload.test_name.strip()
        if payload.expected_result is not None:
            item.expected_result = payload.expected_result.strip()
        if payload.notes is not None:
            item.notes = payload.notes
        item.updated_at = datetime.now(UTC)
        await self.session.commit()
        return ChecklistItemResponse.model_validate(item)

    async def set_result(
        self,
        item_id: uuid.UUID,
        payload: ChecklistItemResultRequest,
        *,
        actor: AuthenticatedUser,
    ) -> ChecklistItemResponse:
        """Record what a tester observed. Open to every authenticated user.

        Both fields together -- which is why the route is `PUT`. `untested` clears the
        reviewer: it means nobody has looked, and leaving a name on it would say
        somebody did.
        """
        item = await self._require_readable(item_id, actor)
        item.current_result = payload.current_result
        item.status = payload.status.value
        if payload.status is ChecklistItemStatus.UNTESTED:
            item.reviewed_by = None
            item.reviewed_at = None
        else:
            item.reviewed_by = actor.id
            item.reviewed_at = datetime.now(UTC)
        item.updated_at = datetime.now(UTC)
        await self.session.commit()
        return ChecklistItemResponse.model_validate(item)

    async def delete(self, item_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete one test case. Gated on `created_by`/`is_admin`."""
        item = await self._require_readable(item_id, actor)
        self._require_destructive_rights(item, actor)
        await self.items.soft_delete(item)
        await self.session.commit()

    async def export(self, query: ChecklistItemListQuery, *, actor: AuthenticatedUser) -> bytes:
        """The same filters as the list route, with pagination ignored (spec 7)."""
        cap = self.settings.checklist_export_max_rows
        rows = await self.items.list_all(
            scope=access.resolve_project_scope(actor),
            cap=cap,
            project_id=query.project_id,
            module_id=query.module_id,
            feature=query.feature,
            status=query.status.value if query.status else None,
            source=query.source.value if query.source else None,
            search=query.search,
        )
        if len(rows) > cap:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EXPORT_TOO_LARGE,
                f"That filter matches more than {cap} rows. Narrow it and try again.",
            )
        return build_workbook(
            rows,
            names=await self._display_names(rows),
            module_names=await self._module_names(rows),
        )

    async def _display_names(self, rows: builtins.list[ChecklistItem]) -> dict[uuid.UUID, str]:
        """Project and user ids mapped to something a human recognises, in two queries."""
        project_ids = {row.project_id for row in rows}
        user_ids = {row.reviewed_by for row in rows if row.reviewed_by}
        names: dict[uuid.UUID, str] = {}
        for project in await self.projects.get_many(list(project_ids)):
            names[project.id] = project.name
        for user in await self.users.get_many(list(user_ids)):
            names[user.id] = user.name
        return names

    async def _module_names(self, rows: builtins.list[ChecklistItem]) -> dict[uuid.UUID, str]:
        """Module ids mapped to names, in one query."""
        modules = await self.modules.get_many({row.module_id for row in rows})
        return {module.id: module.name for module in modules}

    async def _require_readable(
        self, item_id: uuid.UUID, actor: AuthenticatedUser
    ) -> ChecklistItem:
        """The item, if it is in the caller's scope. A miss is `404`."""
        item = await self.items.get_in_scope(item_id, scope=access.resolve_project_scope(actor))
        if item is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.CHECKLIST_ITEM_NOT_FOUND,
                "Checklist item not found.",
            )
        return item

    async def _require_readable_module(
        self, module_id: uuid.UUID, actor: AuthenticatedUser
    ) -> ChecklistModule:
        """The parent module, if it is in the caller's scope."""
        module = await self.modules.get_in_scope(
            module_id, scope=access.resolve_project_scope(actor)
        )
        if module is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.CHECKLIST_MODULE_NOT_FOUND,
                "Checklist module not found.",
            )
        return module

    @staticmethod
    def _require_destructive_rights(item: ChecklistItem, actor: AuthenticatedUser) -> None:
        """`created_by` or an admin. `403`, because existence is not a secret."""
        if item.created_by != actor.id and not actor.is_admin:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                ErrorCode.NOT_CHECKLIST_OWNER,
                "Only the person who added this test, or an admin, can change what it expects.",
            )
