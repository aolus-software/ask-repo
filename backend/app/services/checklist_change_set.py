"""Applying and discarding a change set.

`apply` is the **only** path that mutates `checklist_items` from a proposal. Generation
and chat both stop at a pending change set, so a regeneration is a diff against the
existing rows rather than a fresh list somebody has to reconcile -- and rows nobody
touched are not in the change set at all, so a tester's recorded results survive because
nothing rewrote them (spec 2.1).

The request carries operation **ids**, never content. A checklist is published to every
user on the instance, so its rows must come from a model through the server rather than
from whoever's tab happened to be open (spec 2.7).
"""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistChangeSet,
    ChecklistItem,
    ChecklistItemSource,
    ChecklistItemStatus,
    ChecklistModule,
    ChecklistModuleStatus,
)
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_item import ChecklistItemRepository
from app.repositories.checklist_module import ChecklistModuleRepository
from app.schemas.checklist import (
    ChangeOperationPayload,
    ChangeSetApplyRequest,
    ChangeSetApplyResponse,
    ChecklistChangeSetResponse,
    ChecklistItemResponse,
)

logger = logging.getLogger(__name__)

# Which `ChecklistItem` attribute each camelCase key in an `update` operation writes.
# An allowlist, not `setattr` on whatever the model returned: `changes` originates in a
# model's output, and an unchecked key would let it write `status`, `current_result`,
# or `created_by` -- the three columns this feature exists to keep it away from.
UPDATABLE_FIELDS = {
    "feature": "feature",
    "testName": "test_name",
    "expectedResult": "expected_result",
    "notes": "notes",
}


def _operation_id(raw: dict[str, object]) -> uuid.UUID:
    """The operation's own id, if it parses; a fresh one otherwise.

    A stored operation that fails validation may have an unparseable `id` too --
    a model's `id` field is no more trustworthy than its `itemId`. Something has to
    name the entry in `skipped_operation_ids`, so a fresh id stands in when the
    stored one is not a UUID: the response still reports one skipped operation for
    one bad operation, rather than dropping it silently.
    """
    raw_id = raw.get("id")
    if isinstance(raw_id, str):
        try:
            return uuid.UUID(raw_id)
        except ValueError:
            pass
    return uuid.uuid4()


def _change_set_response(change_set: ChecklistChangeSet) -> ChecklistChangeSetResponse:
    """Build the response, dropping any operation that does not parse.

    `ChecklistChangeSetResponse.operations` is `list[ChangeOperationPayload]`, which
    requires a real UUID `itemId` -- but a stored operation can carry the same
    hallucinated, non-UUID id `apply` already treats as unusable. Calling
    `ChecklistChangeSetResponse.model_validate(change_set)` directly re-validates
    every stored operation and raises on that one, turning it back into exactly the
    all-or-nothing failure the defensive parse in `apply` exists to avoid -- and
    `discard` builds this same response without ever touching the operations loop.
    An operation that cannot be represented is left out of the record rather than
    failing the whole response; `apply` has already reported it by id in
    `skipped_operation_ids` when this is called from there.
    """
    operations: list[ChangeOperationPayload] = []
    for raw in change_set.operations:
        try:
            operations.append(ChangeOperationPayload.model_validate(raw))
        except ValidationError:
            continue
    return ChecklistChangeSetResponse(
        id=change_set.id,
        module_id=change_set.module_id,
        origin=ChangeSetOrigin(change_set.origin),
        message_id=change_set.message_id,
        summary=change_set.summary,
        operations=operations,
        status=ChangeSetStatus(change_set.status),
        resolved_by=change_set.resolved_by,
        resolved_at=change_set.resolved_at,
        created_by=change_set.created_by,
        created_at=change_set.created_at,
    )


class ChecklistChangeSetService:
    """Review decisions on a proposed change set."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.change_sets = ChecklistChangeSetRepository(session)
        self.items = ChecklistItemRepository(session)
        self.modules = ChecklistModuleRepository(session)

    async def apply(
        self,
        change_set_id: uuid.UUID,
        payload: ChangeSetApplyRequest,
        *,
        actor: AuthenticatedUser,
    ) -> ChangeSetApplyResponse:
        """Apply the named operations, in one transaction.

        Open to any authenticated user: applying a change set is reviewing a shared
        document, and gating it on `created_by` would mean only the person who ran the
        generation could act on it (spec 5.4).

        Each stored operation is parsed defensively rather than let a `ValidationError`
        propagate: `ProposedOperation.item_id` is typed `str` at generation time so a
        hallucinated id fails here -- costing one operation -- rather than at
        generation, where it would cost the whole change set. An operation that does
        not parse is therefore skipped like any other one whose target is gone.
        """
        change_set, module = await self._require_pending(change_set_id, actor)
        wanted = set(payload.operation_ids) if payload.operation_ids is not None else None

        touched: list[ChecklistItem] = []
        skipped: list[uuid.UUID] = []
        for raw in change_set.operations:
            try:
                operation = ChangeOperationPayload.model_validate(raw)
            except ValidationError:
                skipped.append(_operation_id(raw))
                continue
            if wanted is not None and operation.id not in wanted:
                continue
            applied = await self._apply_one(operation, module=module, actor=actor)
            if applied is None:
                skipped.append(operation.id)
            else:
                touched.append(applied)

        change_set.status = ChangeSetStatus.APPLIED.value
        change_set.resolved_by = actor.id
        change_set.resolved_at = datetime.now(UTC)
        change_set.updated_at = datetime.now(UTC)
        await self._settle_module(module)
        await self.session.commit()

        if skipped:
            logger.info(
                "change set %s applied with %d operation(s) skipped: their items are"
                " gone or the operation was unparseable",
                change_set_id,
                len(skipped),
            )
        return ChangeSetApplyResponse(
            change_set=_change_set_response(change_set),
            items=[ChecklistItemResponse.model_validate(item) for item in touched],
            skipped_operation_ids=skipped,
        )

    async def discard(
        self, change_set_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> ChecklistChangeSetResponse:
        """Mark the change set discarded and write nothing else."""
        change_set, module = await self._require_pending(change_set_id, actor)
        change_set.status = ChangeSetStatus.DISCARDED.value
        change_set.resolved_by = actor.id
        change_set.resolved_at = datetime.now(UTC)
        change_set.updated_at = datetime.now(UTC)
        await self._settle_module(module)
        await self.session.commit()
        return _change_set_response(change_set)

    async def _apply_one(
        self,
        operation: ChangeOperationPayload,
        *,
        module: ChecklistModule,
        actor: AuthenticatedUser,
    ) -> ChecklistItem | None:
        """One operation. `None` means it was skipped because its target is gone."""
        if operation.op == "add":
            feature = (operation.feature or "General").strip()
            return await self.items.add(
                ChecklistItem(
                    id=uuid.uuid4(),
                    module_id=module.id,
                    project_id=module.project_id,
                    feature=feature,
                    test_name=(operation.test_name or "").strip(),
                    expected_result=(operation.expected_result or "").strip(),
                    # Never from a proposal, on any path (spec 2.3).
                    current_result=None,
                    status=ChecklistItemStatus.UNTESTED.value,
                    citations=(
                        [citation.model_dump() for citation in operation.citations]
                        if operation.citations
                        else None
                    ),
                    # `generated` means a model proposed it and a human reviewed it.
                    # This path is the only place that combination is produced.
                    source=ChecklistItemSource.GENERATED.value,
                    position=await self.items.next_position(module_id=module.id, feature=feature),
                    created_by=actor.id,
                )
            )

        if operation.item_id is None:
            return None
        item = await self.items.get(operation.item_id)
        if item is None or item.module_id != module.id:
            return None

        if operation.op == "remove":
            await self.items.soft_delete(item)
            return item

        for key, value in (operation.changes or {}).items():
            attribute = UPDATABLE_FIELDS.get(key)
            if attribute is None:
                logger.warning("ignoring unknown field %r in change set update", key)
                continue
            setattr(item, attribute, value)
        item.updated_at = datetime.now(UTC)
        return item

    async def _settle_module(self, module: ChecklistModule) -> None:
        """Where the module lands once nothing is pending.

        `ready` when it has items, `empty` when it does not. Not `review`: that state
        means "a change set is waiting", and leaving it there after a decision would
        make the badge permanent.
        """
        remaining = await self.items.list_for_module(module.id)
        module.status = (
            ChecklistModuleStatus.READY.value if remaining else ChecklistModuleStatus.EMPTY.value
        )
        module.updated_at = datetime.now(UTC)

    async def _require_pending(
        self, change_set_id: uuid.UUID, actor: AuthenticatedUser
    ) -> tuple[ChecklistChangeSet, ChecklistModule]:
        """The change set and its module, if the caller may see them and it is pending."""
        change_set = await self.change_sets.get(change_set_id)
        module = (
            None
            if change_set is None
            else await self.modules.get_in_scope(
                change_set.module_id, scope=access.resolve_project_scope(actor)
            )
        )
        if change_set is None or module is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.CHANGE_SET_NOT_FOUND,
                "Change set not found.",
            )
        if change_set.status != ChangeSetStatus.PENDING.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.CHANGE_SET_ALREADY_RESOLVED,
                "That change set has already been applied or discarded.",
            )
        return change_set, module
