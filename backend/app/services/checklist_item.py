"""Item business rules.

Two writes with two different rules, and the split is the design (spec 2.5):

- `update` changes what a test *expects*, and needs `item.edit`.
- `set_result` records what a tester *observed*, and needs only `result.record`, which
  every role on the project holds (`docs/PRD.md` §4.3).

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
from app.core.audit import AuditEntry, AuditEventType, AuditRecorder, ChangedValue
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.core.permissions import Permission
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
    ChecklistResultsClearRequest,
    ChecklistResultsClearResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.services.checklist_export import build_workbook

DEFAULT_SORT = "position"


class ChecklistItemService:
    """CRUD over test cases, the ungated result write, and the export."""

    def __init__(
        self, session: AsyncSession, settings: Settings, *, recorder: AuditRecorder
    ) -> None:
        self.session = session
        self.settings = settings
        self.items = ChecklistItemRepository(session)
        self.modules = ChecklistModuleRepository(session)
        self.projects = ProjectRepository(session)
        self.users = UserRepository(session)
        self._recorder = recorder

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
                kind=query.kind.value if query.kind else None,
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
                kind=payload.kind.value,
                position=await self.items.next_position(
                    module_id=module.id, feature=payload.feature.strip()
                ),
                created_by=actor.id,
            )
        )
        await self.session.commit()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.CHECKLIST_ITEM_CREATED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="checklist_item",
                target_id=item.id,
                target_label=item.test_name,
                project_id=item.project_id,
                changed={
                    "feature": (None, item.feature),
                    "testName": (None, item.test_name),
                },
                context={"origin": "manual"},
            )
        )
        return ChecklistItemResponse.model_validate(item)

    async def update(
        self,
        item_id: uuid.UUID,
        payload: ChecklistItemUpdateRequest,
        *,
        actor: AuthenticatedUser,
    ) -> ChecklistItemResponse:
        """Change what a test expects. Gated on `item.edit`."""
        item = await self._require_readable(item_id, actor)
        access.require_permission(actor, item.project_id, Permission.ITEM_EDIT)
        # Captured before any field is written, so the diff below compares against
        # what the row actually held rather than the just-applied payload.
        old_feature = item.feature
        old_test_name = item.test_name
        old_expected_result = item.expected_result
        if payload.feature is not None:
            item.feature = payload.feature.strip()
        if payload.test_name is not None:
            item.test_name = payload.test_name.strip()
        if payload.expected_result is not None:
            item.expected_result = payload.expected_result.strip()
        if payload.kind is not None:
            item.kind = payload.kind.value
        if payload.notes is not None:
            item.notes = payload.notes
        item.updated_at = datetime.now(UTC)
        await self.session.commit()

        # `expectedResult` never appears here: it is model-authored prose derived
        # from a private repository, and the content ban forbids storing it in a
        # table with no project-deletion sweep. `expectedResultChanged` records that
        # the expectation moved -- who changed it, and when -- without a second copy
        # of the text (`.claude/rules/audit-trail.md`).
        changed: dict[str, tuple[ChangedValue, ChangedValue]] = {}
        if item.feature != old_feature:
            changed["feature"] = (old_feature, item.feature)
        if item.test_name != old_test_name:
            changed["testName"] = (old_test_name, item.test_name)
        if item.expected_result != old_expected_result:
            changed["expectedResultChanged"] = (False, True)
        if changed:
            await self._recorder.record(
                AuditEntry(
                    event_type=AuditEventType.CHECKLIST_ITEM_UPDATED,
                    actor_user_id=actor.id,
                    actor_email=actor.email,
                    target_type="checklist_item",
                    target_id=item.id,
                    target_label=item.test_name,
                    project_id=item.project_id,
                    changed=changed,
                )
            )
        return ChecklistItemResponse.model_validate(item)

    async def set_result(
        self,
        item_id: uuid.UUID,
        payload: ChecklistItemResultRequest,
        *,
        actor: AuthenticatedUser,
    ) -> ChecklistItemResponse:
        """Record what a tester observed. Gated on `result.record`, which every role
        on the project holds.

        The check is deliberately written out even though no role can fail it: it
        records the `docs/PRD.md` §4.3 decision -- editing an expectation is gated,
        recording an observation is not -- at the call site, so the absence of a gate
        here cannot later be read as an oversight.

        Both fields together -- which is why the route is `PUT`. `untested` clears the
        reviewer: it means nobody has looked, and leaving a name on it would say
        somebody did.
        """
        item = await self._require_readable(item_id, actor)
        access.require_permission(actor, item.project_id, Permission.RESULT_RECORD)
        old_status = item.status
        old_current_result = item.current_result
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

        # Deliberately its own event, never merged into `checklist_item.updated`:
        # `status` and `current_result` are the two columns the change-set apply path
        # may not write, because they claim a human observation, and keeping the event
        # that legitimately writes them distinct is what makes "who recorded this
        # pass?" answerable without reading the payload of every update.
        # `currentResult` is never stored: it is what a tester typed describing
        # generated test content, and the content ban applies to it exactly like
        # `expectedResult` above. `currentResultChanged` records that an observation
        # was written without a second copy of the text.
        changed: dict[str, tuple[ChangedValue, ChangedValue]] = {}
        if item.status != old_status:
            changed["status"] = (old_status, item.status)
        if item.current_result != old_current_result:
            changed["currentResultChanged"] = (False, True)
        if changed:
            await self._recorder.record(
                AuditEntry(
                    event_type=AuditEventType.CHECKLIST_ITEM_RESULT_RECORDED,
                    actor_user_id=actor.id,
                    actor_email=actor.email,
                    target_type="checklist_item",
                    target_id=item.id,
                    target_label=item.test_name,
                    project_id=item.project_id,
                    changed=changed,
                )
            )
        return ChecklistItemResponse.model_validate(item)

    async def delete(self, item_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete one test case. Gated on `item.edit`."""
        item = await self._require_readable(item_id, actor)
        access.require_permission(actor, item.project_id, Permission.ITEM_EDIT)
        # Captured before the delete, so the flag reflects what the row held rather
        # than a soft-deleted item's now-frozen state.
        had_recorded_result = item.status != ChecklistItemStatus.UNTESTED.value
        item_id_value = item.id
        item_feature = item.feature
        item_test_name = item.test_name
        project_id = item.project_id
        await self.items.soft_delete(item)
        await self.session.commit()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.CHECKLIST_ITEM_DELETED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="checklist_item",
                target_id=item_id_value,
                target_label=item_test_name,
                project_id=project_id,
                changed={
                    "feature": (item_feature, None),
                    "testName": (item_test_name, None),
                },
                context={"hadRecordedResult": had_recorded_result},
            )
        )

    async def export(self, query: ChecklistItemListQuery, *, actor: AuthenticatedUser) -> bytes:
        """The same filters as the list route, with pagination ignored (spec 7)."""
        scope = access.resolve_project_scope(actor)
        cap = self.settings.checklist_export_max_rows
        rows = await self.items.list_all(
            scope=scope,
            cap=cap,
            project_id=query.project_id,
            module_id=query.module_id,
            feature=query.feature,
            status=query.status.value if query.status else None,
            source=query.source.value if query.source else None,
            kind=query.kind.value if query.kind else None,
            search=query.search,
        )
        if len(rows) > cap:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EXPORT_TOO_LARGE,
                f"That filter matches more than {cap} rows. Narrow it and try again.",
            )
        workbook = build_workbook(
            rows,
            names=await self._display_names(rows),
            module_names=await self._module_names(rows),
        )
        # An export changes nothing, and is audited anyway: it is the one action
        # that takes a private repository's derived content out of the instance.
        # `filter` carries the query's filters, matching `clear_results` -- never
        # the rows themselves, which would put generated test content in the trail.
        # `feature` is picked from generated content in the UI, so -- like
        # `expectedResult` -- it stays out; `featureFilterApplied` says a feature
        # filter narrowed the export without naming which one. `search` stays: it is
        # the caller's own query intent, not a fact about the repository.
        filter_details: dict[str, str] = {}
        if query.project_id is not None:
            filter_details["projectId"] = str(query.project_id)
        if query.module_id is not None:
            filter_details["moduleId"] = str(query.module_id)
        if query.feature is not None:
            filter_details["featureFilterApplied"] = "true"
        if query.status is not None:
            filter_details["status"] = query.status.value
        if query.source is not None:
            filter_details["source"] = query.source.value
        if query.kind is not None:
            filter_details["kind"] = query.kind.value
        if query.search is not None:
            filter_details["search"] = query.search

        # The filter may narrow by module rather than project directly, so fall back
        # to what the matched rows actually belong to -- but only when every matched
        # row agrees. An unfiltered export can span every project in scope, and
        # stamping whichever project sorts first on `rows[0]` would misattribute the
        # row to one project out of many. `projectCount` keeps the row honest about
        # what happened even when `project_id` is `None`.
        distinct_project_ids = {row.project_id for row in rows}
        if query.project_id is not None:
            project_id: uuid.UUID | None = query.project_id
        elif len(distinct_project_ids) == 1:
            project_id = next(iter(distinct_project_ids))
        else:
            project_id = None

        # A bulk export has no single target unless the query narrowed to exactly
        # one module -- then the module's name is what makes the row legible, rather
        # than the bare `checklist_item` type with nothing to point at.
        target_type: str | None = None
        target_id: uuid.UUID | None = None
        target_label: str | None = None
        if query.module_id is not None:
            module = await self.modules.get_in_scope(query.module_id, scope=scope)
            if module is not None:
                target_type = "checklist_module"
                target_id = module.id
                target_label = module.name

        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.CHECKLIST_EXPORTED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type=target_type,
                target_id=target_id,
                target_label=target_label,
                project_id=project_id,
                context={
                    "format": "xlsx",
                    "rowCount": len(rows),
                    "filter": filter_details,
                    "projectCount": len(distinct_project_ids),
                },
            )
        )
        return workbook

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

    async def clear_results(
        self, payload: ChecklistResultsClearRequest, *, actor: AuthenticatedUser
    ) -> ChecklistResultsClearResponse:
        """Reset the recorded results the filter selects.

        Gated on `result.record`, exactly like recording one (spec 2.5) -- clearing a
        result is un-recording it, so it needs the same permission `set_result` does,
        not a `created_by` check that would mean a tester could write an observation
        and then not be allowed to take it back.

        The check is deliberately written out even though no role can fail it today
        (every system role holds `result.record`): it records the intent at the call
        site, so the absence of a gate here cannot later be read as an oversight, and
        the module's own membership scope still bounds which rows are reachable.
        """
        module = await self._require_readable_module(payload.module_id, actor)
        access.require_permission(actor, module.project_id, Permission.RESULT_RECORD)
        cleared = await self.items.clear_results(
            scope=access.resolve_project_scope(actor),
            module_id=payload.module_id,
            feature=payload.feature,
            status=payload.status.value if payload.status else None,
            source=payload.source.value if payload.source else None,
            kind=payload.kind.value if payload.kind else None,
            search=payload.search,
        )
        await self.session.commit()
        # The highest-value row in the table: a filter can erase a week of recorded
        # observations without deleting a single row. `filter` carries the query's
        # filters -- what was asked for -- never the rows it matched, since copying
        # those in would put generated test content in the trail (content ban).
        # `feature` is picked from generated content in the UI, so it is dropped to a
        # boolean like `export`'s filter; `search` stays because it is the caller's
        # own query intent.
        filter_details: dict[str, str] = {"moduleId": str(payload.module_id)}
        if payload.feature is not None:
            filter_details["featureFilterApplied"] = "true"
        if payload.status is not None:
            filter_details["status"] = payload.status.value
        if payload.source is not None:
            filter_details["source"] = payload.source.value
        if payload.kind is not None:
            filter_details["kind"] = payload.kind.value
        if payload.search is not None:
            filter_details["search"] = payload.search
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.CHECKLIST_ITEM_RESULTS_CLEARED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="checklist_module",
                target_id=module.id,
                target_label=module.name,
                project_id=module.project_id,
                context={"clearedCount": cleared, "filter": filter_details},
            )
        )
        return ChecklistResultsClearResponse(cleared_count=cleared)

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
