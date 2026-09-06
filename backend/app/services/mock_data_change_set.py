"""Applying and discarding a mock-data change set.

`apply` is the **only** path that mutates `mock_data_records` from a proposal, mirroring
`app/services/checklist_change_set.py` exactly. There is no per-column allowlist to
maintain here the way the checklist needs one: a record has exactly one content column
(`fields`, a JSONB map), so `update` always assigns a brand-new merged dict to that one
column -- there is no second column an operation's `changes` map could reach.
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
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.mock_data import MockDataChangeSet, MockDataDatasetStatus, MockDataRecord
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from app.repositories.mock_data_record import MockDataRecordRepository
from app.schemas.mock_data import (
    MockDataChangeOperationPayload,
    MockDataChangeSetApplyRequest,
    MockDataChangeSetApplyResponse,
    MockDataChangeSetResponse,
    MockDataRecordResponse,
)

logger = logging.getLogger(__name__)


def _operation_id(raw: dict[str, object]) -> uuid.UUID:
    """The operation's own id, if it parses; a fresh one otherwise."""
    raw_id = raw.get("id")
    if isinstance(raw_id, str):
        try:
            return uuid.UUID(raw_id)
        except ValueError:
            pass
    return uuid.uuid4()


def _change_set_response(change_set: MockDataChangeSet) -> MockDataChangeSetResponse:
    """Build the response, dropping any operation that does not parse."""
    operations: list[MockDataChangeOperationPayload] = []
    for raw in change_set.operations:
        try:
            operations.append(MockDataChangeOperationPayload.model_validate(raw))
        except ValidationError:
            continue
    return MockDataChangeSetResponse(
        id=change_set.id,
        checklist_module_id=change_set.checklist_module_id,
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


class MockDataChangeSetService:
    """Review decisions on a proposed mock-data change set."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.change_sets = MockDataChangeSetRepository(session)
        self.records = MockDataRecordRepository(session)
        self.datasets = MockDataDatasetRepository(session)
        self.modules = ChecklistModuleRepository(session)

    async def apply(
        self,
        change_set_id: uuid.UUID,
        payload: MockDataChangeSetApplyRequest,
        *,
        actor: AuthenticatedUser,
    ) -> MockDataChangeSetApplyResponse:
        """Apply the named operations, in one transaction. Open to any authenticated
        user, matching `ChecklistChangeSetService.apply`."""
        change_set, module_id = await self._require_pending(change_set_id, actor)
        wanted = set(payload.operation_ids) if payload.operation_ids is not None else None

        touched: list[MockDataRecord] = []
        skipped: list[uuid.UUID] = []
        for raw in change_set.operations:
            try:
                operation = MockDataChangeOperationPayload.model_validate(raw)
            except ValidationError:
                skipped.append(_operation_id(raw))
                continue
            if wanted is not None and operation.id not in wanted:
                continue
            applied = await self._apply_one(operation, module_id=module_id, actor=actor)
            if applied is None:
                skipped.append(operation.id)
            else:
                touched.append(applied)

        change_set.status = ChangeSetStatus.APPLIED.value
        change_set.resolved_by = actor.id
        change_set.resolved_at = datetime.now(UTC)
        change_set.updated_at = datetime.now(UTC)
        await self._settle_dataset(module_id)
        await self.session.commit()

        if skipped:
            logger.info(
                "mock-data change set %s applied with %d operation(s) skipped",
                change_set_id,
                len(skipped),
            )
        return MockDataChangeSetApplyResponse(
            change_set=_change_set_response(change_set),
            records=[MockDataRecordResponse.model_validate(record) for record in touched],
            skipped_operation_ids=skipped,
        )

    async def discard(
        self, change_set_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> MockDataChangeSetResponse:
        """Mark the change set discarded and write nothing else."""
        change_set, module_id = await self._require_pending(change_set_id, actor)
        change_set.status = ChangeSetStatus.DISCARDED.value
        change_set.resolved_by = actor.id
        change_set.resolved_at = datetime.now(UTC)
        change_set.updated_at = datetime.now(UTC)
        await self._settle_dataset(module_id)
        await self.session.commit()
        return _change_set_response(change_set)

    async def _apply_one(
        self,
        operation: MockDataChangeOperationPayload,
        *,
        module_id: uuid.UUID,
        actor: AuthenticatedUser,
    ) -> MockDataRecord | None:
        """One operation. `None` means it was skipped because its target is gone."""
        if operation.op == "add":
            return await self.records.add(
                MockDataRecord(
                    id=uuid.uuid4(),
                    checklist_module_id=module_id,
                    fields=operation.fields or {},
                    created_by=actor.id,
                )
            )

        if operation.record_id is None:
            return None
        record = await self.records.get(operation.record_id)
        if record is None or record.checklist_module_id != module_id:
            return None

        if operation.op == "remove":
            await self.records.soft_delete(record)
            return record

        # `update`: a brand-new dict assigned to the one content column, never a
        # mutation of the existing dict in place -- SQLAlchemy's change tracking
        # needs a new object reference to see the write.
        record.fields = {**record.fields, **(operation.changes or {})}
        record.updated_at = datetime.now(UTC)
        return record

    async def _settle_dataset(self, module_id: uuid.UUID) -> None:
        """Where the dataset lands once nothing is pending. `ready` when it has
        records, `empty` when it does not -- never `review`, which means "waiting"."""
        dataset = await self.datasets.get_by_module(module_id)
        if dataset is None:
            return
        remaining = await self.records.list_for_module(module_id)
        dataset.status = (
            MockDataDatasetStatus.READY.value if remaining else MockDataDatasetStatus.EMPTY.value
        )
        dataset.updated_at = datetime.now(UTC)

    async def _require_pending(
        self, change_set_id: uuid.UUID, actor: AuthenticatedUser
    ) -> tuple[MockDataChangeSet, uuid.UUID]:
        """The change set and its module id, if the caller may see the module and the
        change set is pending."""
        change_set = await self.change_sets.get(change_set_id)
        module = (
            None
            if change_set is None
            else await self.modules.get_in_scope(
                change_set.checklist_module_id, scope=access.resolve_project_scope(actor)
            )
        )
        if change_set is None or module is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.MOCK_DATA_CHANGE_SET_NOT_FOUND,
                "Mock data change set not found.",
            )
        if change_set.status != ChangeSetStatus.PENDING.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.MOCK_DATA_CHANGE_SET_ALREADY_RESOLVED,
                "That change set has already been applied or discarded.",
            )
        return change_set, module.id
