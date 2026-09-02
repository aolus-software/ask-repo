"""Applying a change set: the one path that writes `checklist_items`."""

import uuid

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.checklist import (
    ChangeSetStatus,
    ChecklistItemSource,
    ChecklistItemStatus,
    ChecklistModuleStatus,
)
from app.repositories.checklist_item import ChecklistItemRepository
from app.schemas.checklist import ChangeSetApplyRequest
from app.services.checklist_change_set import ChecklistChangeSetService
from tests.factories import (
    create_checklist_change_set,
    create_checklist_item,
    create_checklist_module,
    create_user,
)
from tests.helpers import authenticated


def _add(
    operation_id: uuid.UUID, *, test_name: str = "Rejects a wrong password"
) -> dict[str, object]:
    return {
        "op": "add",
        "id": str(operation_id),
        "feature": "Login",
        "testName": test_name,
        "expectedResult": "401 INVALID_CREDENTIALS",
        "citations": None,
        "rationale": "The handler raises on a bcrypt mismatch.",
    }


async def test_apply_adds_items_marked_generated(db_session: AsyncSession) -> None:
    """`generated` means a model proposed it AND a human reviewed it. This path is
    the only place that combination can be produced."""
    module = await create_checklist_module(db_session)
    operation_id = uuid.uuid4()
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, operations=[_add(operation_id)]
    )
    reviewer = await create_user(db_session)
    service = ChecklistChangeSetService(db_session, Settings())

    result = await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=authenticated(reviewer)
    )

    assert len(result.items) == 1
    item = result.items[0]
    assert item.source is ChecklistItemSource.GENERATED
    assert item.status is ChecklistItemStatus.UNTESTED
    # Spec 2.3: no observation, ever, from this path either.
    assert item.current_result is None
    assert result.change_set.status is ChangeSetStatus.APPLIED
    assert result.change_set.resolved_by == reviewer.id


async def test_apply_is_selective_when_operation_ids_are_given(
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    keep, drop = uuid.uuid4(), uuid.uuid4()
    change_set = await create_checklist_change_set(
        db_session,
        module_id=module.id,
        operations=[_add(keep, test_name="kept"), _add(drop, test_name="dropped")],
    )
    service = ChecklistChangeSetService(db_session, Settings())

    result = await service.apply(
        change_set.id,
        ChangeSetApplyRequest(operation_ids=[keep]),
        actor=authenticated(await create_user(db_session)),
    )

    assert [item.test_name for item in result.items] == ["kept"]


async def test_an_update_preserves_a_recorded_result(db_session: AsyncSession) -> None:
    """The whole reason change sets exist. A regeneration that destroyed a tester's
    day of recorded results would make the feature unusable (spec 2.1)."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
        current_result="Observed 400",
        status=ChecklistItemStatus.FAIL,
    )
    change_set = await create_checklist_change_set(
        db_session,
        module_id=module.id,
        operations=[
            {
                "op": "update",
                "id": str(uuid.uuid4()),
                "itemId": str(item.id),
                "changes": {"expectedResult": "401 INVALID_CREDENTIALS"},
                "rationale": "The handler now raises 401.",
            }
        ],
    )
    service = ChecklistChangeSetService(db_session, Settings())

    result = await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=authenticated(await create_user(db_session))
    )

    updated = result.items[0]
    assert updated.expected_result == "401 INVALID_CREDENTIALS"
    assert updated.current_result == "Observed 400"
    assert updated.status is ChecklistItemStatus.FAIL


async def test_an_operation_naming_a_vanished_item_is_skipped_not_failed(
    db_session: AsyncSession,
) -> None:
    """The item was deleted between proposal and apply. Failing the whole set for
    that would let one stale row block three good ones (spec 3.3)."""
    module = await create_checklist_module(db_session)
    stale_operation = uuid.uuid4()
    good_operation = uuid.uuid4()
    change_set = await create_checklist_change_set(
        db_session,
        module_id=module.id,
        operations=[
            {
                "op": "remove",
                "id": str(stale_operation),
                "itemId": str(uuid.uuid4()),
                "rationale": "Gone.",
            },
            _add(good_operation),
        ],
    )
    service = ChecklistChangeSetService(db_session, Settings())

    result = await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=authenticated(await create_user(db_session))
    )

    assert result.skipped_operation_ids == [stale_operation]
    assert len(result.items) == 1
    assert result.change_set.status is ChangeSetStatus.APPLIED


async def test_an_operation_with_an_unparseable_item_id_is_skipped_not_failed(
    db_session: AsyncSession,
) -> None:
    """A model can emit an `itemId` that is not a UUID at all --
    `ProposedOperation.item_id` is typed `str` for exactly this reason, so a
    hallucinated id must fail *here*, costing one operation, rather than at
    generation time where it would cost the whole change set (controller amendment).

    `ChangeOperationPayload.model_validate` raises `ValidationError` on a raw
    `itemId` that is not a UUID; that must not propagate out of `apply` and take
    every good operation in the set down with it.
    """
    module = await create_checklist_module(db_session)
    bad_operation = uuid.uuid4()
    good_operation = uuid.uuid4()
    change_set = await create_checklist_change_set(
        db_session,
        module_id=module.id,
        operations=[
            {
                "op": "remove",
                "id": str(bad_operation),
                "itemId": "not-a-uuid",
                "rationale": "Hallucinated id.",
            },
            _add(good_operation),
        ],
    )
    service = ChecklistChangeSetService(db_session, Settings())

    result = await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=authenticated(await create_user(db_session))
    )

    assert result.skipped_operation_ids == [bad_operation]
    assert len(result.items) == 1
    assert result.change_set.status is ChangeSetStatus.APPLIED


async def test_applying_an_already_resolved_set_is_409(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, status=ChangeSetStatus.APPLIED
    )
    service = ChecklistChangeSetService(db_session, Settings())

    with pytest.raises(AppError) as caught:
        await service.apply(
            change_set.id,
            ChangeSetApplyRequest(),
            actor=authenticated(await create_user(db_session)),
        )

    assert caught.value.status_code == status.HTTP_409_CONFLICT
    assert caught.value.code is ErrorCode.CHANGE_SET_ALREADY_RESOLVED


async def test_anyone_may_apply_because_reviewing_is_a_shared_act(
    db_session: AsyncSession,
) -> None:
    """Gating on `created_by` would mean only the person who ran the generation could
    act on it, which is not review (spec 5.4)."""
    module = await create_checklist_module(db_session)
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, operations=[_add(uuid.uuid4())]
    )
    stranger = await create_user(db_session)
    service = ChecklistChangeSetService(db_session, Settings())

    result = await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=authenticated(stranger)
    )

    assert result.change_set.resolved_by == stranger.id


async def test_discard_writes_nothing_and_frees_the_module(
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.REVIEW)
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, operations=[_add(uuid.uuid4())]
    )
    service = ChecklistChangeSetService(db_session, Settings())

    resolved = await service.discard(
        change_set.id, actor=authenticated(await create_user(db_session))
    )

    assert resolved.status is ChangeSetStatus.DISCARDED
    assert await ChecklistItemRepository(db_session).list_for_module(module.id) == []
    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.EMPTY.value


async def test_applying_moves_the_module_to_ready(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session, status=ChecklistModuleStatus.REVIEW)
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, operations=[_add(uuid.uuid4())]
    )
    service = ChecklistChangeSetService(db_session, Settings())

    await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=authenticated(await create_user(db_session))
    )

    await db_session.refresh(module)
    assert module.status == ChecklistModuleStatus.READY.value
