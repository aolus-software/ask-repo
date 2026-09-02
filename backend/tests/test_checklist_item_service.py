"""Item business rules. The two writes, and the split between them, are the point."""

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.checklist import ChecklistItemSource, ChecklistItemStatus
from app.schemas.checklist import (
    ChecklistItemCreateRequest,
    ChecklistItemListQuery,
    ChecklistItemResultRequest,
    ChecklistItemUpdateRequest,
)
from app.services.checklist_item import ChecklistItemService
from tests.factories import create_checklist_item, create_checklist_module, create_user
from tests.helpers import authenticated


async def test_any_user_may_record_a_result(db_session: AsyncSession) -> None:
    """A tester who did not author the checklist must be able to record what they
    observed. Ungated, deliberately (spec 2.5)."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
    )
    tester = await create_user(db_session)
    service = ChecklistItemService(db_session, Settings())

    result = await service.set_result(
        item.id,
        ChecklistItemResultRequest(current_result="Returned 500", status=ChecklistItemStatus.FAIL),
        actor=authenticated(tester),
    )

    assert result.current_result == "Returned 500"
    assert result.status is ChecklistItemStatus.FAIL
    # Who looked, and when. Without it a verdict is an anonymous claim.
    assert result.reviewed_by == tester.id
    assert result.reviewed_at is not None


async def test_a_tester_cannot_rewrite_the_expectation(db_session: AsyncSession) -> None:
    """Otherwise the cheapest way to make a failing test pass is to edit what was
    expected -- which is the whole reason the two writes are separate routes."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
    )
    tester = await create_user(db_session)
    service = ChecklistItemService(db_session, Settings())

    with pytest.raises(AppError) as caught:
        await service.update(
            item.id,
            ChecklistItemUpdateRequest(expected_result="Anything is fine"),
            actor=authenticated(tester),
        )

    assert caught.value.status_code == status.HTTP_403_FORBIDDEN
    assert caught.value.code is ErrorCode.NOT_CHECKLIST_OWNER


async def test_setting_a_result_back_to_untested_clears_the_reviewer(
    db_session: AsyncSession,
) -> None:
    """`untested` means nobody has looked. Leaving a reviewer on it would say someone
    did, and the pass rate would be computed against a verdict that was withdrawn."""
    module = await create_checklist_module(db_session)
    item = await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
        status=ChecklistItemStatus.PASS,
    )
    service = ChecklistItemService(db_session, Settings())
    tester = await create_user(db_session)
    await service.set_result(
        item.id,
        ChecklistItemResultRequest(current_result="ok", status=ChecklistItemStatus.PASS),
        actor=authenticated(tester),
    )

    result = await service.set_result(
        item.id,
        ChecklistItemResultRequest(current_result=None, status=ChecklistItemStatus.UNTESTED),
        actor=authenticated(tester),
    )

    assert result.reviewed_by is None
    assert result.reviewed_at is None
    assert result.current_result is None


async def test_a_manual_item_is_marked_manual_and_positioned_last(
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
        feature="Login",
        position=0,
    )
    service = ChecklistItemService(db_session, Settings())

    created = await service.create(
        ChecklistItemCreateRequest(
            module_id=module.id,
            feature="Login",
            test_name="Rejects an empty password",
            expected_result="422 VALIDATION_ERROR",
        ),
        actor=authenticated(await create_user(db_session)),
    )

    assert created.source is ChecklistItemSource.MANUAL
    assert created.position == 1
    # Denormalised at insert and never updated: a module cannot move projects.
    assert created.project_id == module.project_id
    assert created.status is ChecklistItemStatus.UNTESTED
    assert created.current_result is None


async def test_export_refuses_above_the_cap(db_session: AsyncSession) -> None:
    """`openpyxl` allocates the whole book in memory even write-only, so the cap is
    the only thing bounding it."""
    module = await create_checklist_module(db_session)
    for index in range(3):
        await create_checklist_item(
            db_session,
            module_id=module.id,
            project_id=module.project_id,
            created_by=module.created_by,
            position=index,
        )
    service = ChecklistItemService(db_session, Settings(checklist_export_max_rows=2))

    with pytest.raises(AppError) as caught:
        await service.export(
            ChecklistItemListQuery(), actor=authenticated(await create_user(db_session))
        )

    assert caught.value.status_code == status.HTTP_409_CONFLICT
    assert caught.value.code is ErrorCode.EXPORT_TOO_LARGE


async def test_export_applies_the_same_filters_and_ignores_pagination(
    db_session: AsyncSession,
) -> None:
    """The point is to get the whole filtered set into one file (spec 7)."""
    module = await create_checklist_module(db_session)
    for index in range(3):
        await create_checklist_item(
            db_session,
            module_id=module.id,
            project_id=module.project_id,
            created_by=module.created_by,
            position=index,
            status=ChecklistItemStatus.PASS if index else ChecklistItemStatus.FAIL,
        )
    service = ChecklistItemService(db_session, Settings())

    content = await service.export(
        ChecklistItemListQuery(limit=1, status=ChecklistItemStatus.PASS),
        actor=authenticated(await create_user(db_session)),
    )

    from io import BytesIO

    from openpyxl import load_workbook

    sheet = load_workbook(BytesIO(content)).worksheets[0]
    assert sheet.max_row == 3  # header plus the two PASS rows, `limit` ignored
