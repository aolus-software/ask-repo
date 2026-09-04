"""The four checklist tables, and the invariants their columns encode."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import SoftDeleteMixin
from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistItemSource,
    ChecklistItemStatus,
    ChecklistMessage,
    ChecklistModuleStatus,
)
from tests.factories import (
    create_checklist_change_set,
    create_checklist_item,
    create_checklist_module,
    create_project,
    create_user,
)


@pytest.mark.asyncio
async def test_module_starts_empty_with_no_lease(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    assert module.status == ChecklistModuleStatus.EMPTY.value
    assert module.lease_expires_at is None
    assert module.last_job_id is None
    assert module.indexed_generation is None
    assert module.deleted_at is None


@pytest.mark.asyncio
async def test_item_denormalises_project_and_defaults_to_untested(
    db_session: AsyncSession,
) -> None:
    project = await create_project(db_session)
    module = await create_checklist_module(db_session, project_id=project.id)
    item = await create_checklist_item(db_session, module_id=module.id)

    assert item.project_id == project.id
    assert item.status == ChecklistItemStatus.UNTESTED.value
    # Spec 2.3: the generator never writes an observation.
    assert item.current_result is None
    assert item.source == ChecklistItemSource.GENERATED.value
    assert item.reviewed_by is None


@pytest.mark.asyncio
async def test_change_set_stores_operations_as_json(db_session: AsyncSession) -> None:
    operation_id = str(uuid.uuid4())
    change_set = await create_checklist_change_set(
        db_session,
        operations=[
            {
                "op": "add",
                "id": operation_id,
                "feature": "Login",
                "testName": "Rejects a wrong password",
                "expectedResult": "401 with code INVALID_CREDENTIALS",
                "citations": [],
                "rationale": "The handler raises on a bcrypt mismatch.",
            }
        ],
    )
    await db_session.refresh(change_set)

    assert change_set.origin == ChangeSetOrigin.GENERATION.value
    assert change_set.status == ChangeSetStatus.PENDING.value
    assert change_set.operations[0]["id"] == operation_id


@pytest.mark.asyncio
async def test_message_is_soft_deletable(db_session: AsyncSession) -> None:
    """Unlike `messages`. Spec 3.4: a shared, auditable record does not get that
    exception, because it is not deleted wholesale with a private parent."""
    assert issubclass(ChecklistMessage, SoftDeleteMixin)
    user = await create_user(db_session)
    assert user.id is not None
