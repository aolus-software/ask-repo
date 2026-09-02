"""Item persistence: scoping, grid ordering, positions, and the export read."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import ProjectScope
from app.models.checklist import ChecklistItemStatus
from app.repositories.checklist_item import ChecklistItemRepository
from tests.factories import create_checklist_item, create_checklist_module, create_project


async def test_list_page_filters_within_the_scope_by_module(
    db_session: AsyncSession,
) -> None:
    project = await create_project(db_session)
    auth = await create_checklist_module(db_session, project_id=project.id, name="Auth")
    billing = await create_checklist_module(db_session, project_id=project.id, name="Billing")
    await create_checklist_item(
        db_session, module_id=auth.id, project_id=project.id, created_by=auth.created_by
    )
    await create_checklist_item(
        db_session, module_id=billing.id, project_id=project.id, created_by=billing.created_by
    )
    repository = ChecklistItemRepository(db_session)

    rows, total = await repository.list_page(
        scope=ProjectScope.all(),
        page=1,
        limit=25,
        sort="position",
        descending=False,
        module_id=auth.id,
    )

    assert total == 1
    assert rows[0].module_id == auth.id


async def test_list_all_orders_by_feature_then_position(db_session: AsyncSession) -> None:
    """The sheet must read in the order a tester works (spec 7)."""
    module = await create_checklist_module(db_session)
    for feature, position in (("Login", 1), ("Login", 0), ("Register", 0)):
        await create_checklist_item(
            db_session,
            module_id=module.id,
            project_id=module.project_id,
            created_by=module.created_by,
            feature=feature,
            position=position,
            test_name=f"{feature}-{position}",
        )
    repository = ChecklistItemRepository(db_session)

    rows = await repository.list_all(scope=ProjectScope.all(), cap=100)

    assert [row.test_name for row in rows] == ["Login-0", "Login-1", "Register-0"]


async def test_list_all_fetches_one_row_past_the_cap(db_session: AsyncSession) -> None:
    """One extra row deliberately: the service compares the length against the cap to
    decide whether to refuse, so it never runs a second COUNT over the same filters."""
    module = await create_checklist_module(db_session)
    for index in range(4):
        await create_checklist_item(
            db_session,
            module_id=module.id,
            project_id=module.project_id,
            created_by=module.created_by,
            position=index,
        )
    repository = ChecklistItemRepository(db_session)

    assert len(await repository.list_all(scope=ProjectScope.all(), cap=2)) == 3


async def test_next_position_continues_within_a_feature(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
        feature="Login",
        position=4,
    )
    repository = ChecklistItemRepository(db_session)

    assert await repository.next_position(module_id=module.id, feature="Login") == 5
    assert await repository.next_position(module_id=module.id, feature="Register") == 0


async def test_status_counts_groups_by_module(db_session: AsyncSession) -> None:
    """The module list renders pass/fail/untested counts without N+1 queries."""
    module = await create_checklist_module(db_session)
    for status in (
        ChecklistItemStatus.PASS,
        ChecklistItemStatus.PASS,
        ChecklistItemStatus.BLOCKED,
    ):
        await create_checklist_item(
            db_session,
            module_id=module.id,
            project_id=module.project_id,
            created_by=module.created_by,
            status=status,
        )
    repository = ChecklistItemRepository(db_session)

    counts = await repository.status_counts(module_ids=[module.id])

    assert counts[module.id] == {"pass": 2, "blocked": 1}


async def test_status_counts_returns_empty_without_querying(db_session: AsyncSession) -> None:
    """The short-circuit matters because the module list calls this with whatever page it
    has; an empty page must not become a query with an empty `IN ()`."""
    repository = ChecklistItemRepository(db_session)

    assert await repository.status_counts(module_ids=[]) == {}


async def test_soft_delete_for_module_hides_the_items(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
    )
    repository = ChecklistItemRepository(db_session)

    assert await repository.soft_delete_for_module(module.id) == 1
    assert await repository.list_for_module(module.id) == []
