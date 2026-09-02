"""Module business rules: scoping, the destructive gate, and the generate pre-flight."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistChangeSet,
    ChecklistModuleStatus,
)
from app.models.project import ProjectStatus
from app.queue.protocol import InMemoryIngestionQueue
from app.schemas.checklist import (
    ChecklistModuleCreateRequest,
    ChecklistModuleListQuery,
    ChecklistModuleUpdateRequest,
)
from app.services.checklist_module import ChecklistModuleService
from tests.factories import (
    create_checklist_change_set,
    create_checklist_item,
    create_checklist_message,
    create_checklist_module,
    create_project,
    create_user,
)
from tests.helpers import authenticated  # `AuthenticatedUser` from a `User` row


async def test_list_shows_modules_other_people_created(db_session: AsyncSession) -> None:
    """Phase 1 sharing is intended (docs/PRD.md 4.1). `created_by` gates destruction."""
    mine = await create_checklist_module(db_session)
    other = await create_user(db_session)
    await create_checklist_module(db_session, created_by=other.id)
    service = ChecklistModuleService(db_session, Settings())

    page = await service.list(
        ChecklistModuleListQuery(), actor=authenticated(await create_user(db_session))
    )

    assert page.total_count == 2
    assert mine.id in {item.id for item in page.items}


async def test_list_carries_status_counts_and_the_pending_badge(
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
    )
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, status=ChangeSetStatus.PENDING
    )
    service = ChecklistModuleService(db_session, Settings())

    page = await service.list(
        ChecklistModuleListQuery(), actor=authenticated(await create_user(db_session))
    )

    row = page.items[0]
    assert (row.item_count, row.untested_count) == (1, 1)
    assert row.pending_change_set_id == change_set.id


async def test_stale_is_true_when_the_project_was_reindexed(
    db_session: AsyncSession,
) -> None:
    """`indexed_generation` behind the project's means the repository moved under the
    checklist. Surfaced as a prompt to regenerate; nothing enforces it (spec 3.1)."""
    project = await create_project(db_session)
    project.active_generation = 3
    module = await create_checklist_module(db_session, project_id=project.id, indexed_generation=2)
    service = ChecklistModuleService(db_session, Settings())

    detail = await service.get(module.id, actor=authenticated(await create_user(db_session)))

    assert detail.stale is True


async def test_editing_someone_elses_module_is_403_not_404(
    db_session: AsyncSession,
) -> None:
    """Module existence is deliberately public, so hiding it would only confuse
    (.claude/rules/response-api.md)."""
    module = await create_checklist_module(db_session)
    stranger = await create_user(db_session)
    service = ChecklistModuleService(db_session, Settings())

    with pytest.raises(AppError) as caught:
        await service.update(
            module.id, ChecklistModuleUpdateRequest(name="Renamed"), actor=authenticated(stranger)
        )

    assert caught.value.status_code == status.HTTP_403_FORBIDDEN
    assert caught.value.code is ErrorCode.NOT_CHECKLIST_OWNER


async def test_an_admin_may_edit_and_delete_a_module_they_did_not_create(
    db_session: AsyncSession,
) -> None:
    module = await create_checklist_module(db_session)
    admin = await create_user(db_session, is_admin=True)
    service = ChecklistModuleService(db_session, Settings())

    await service.update(
        module.id, ChecklistModuleUpdateRequest(name="Renamed"), actor=authenticated(admin)
    )
    await service.delete(module.id, actor=authenticated(admin))

    with pytest.raises(AppError) as caught:
        await service.get(module.id, actor=authenticated(admin))
    assert caught.value.status_code == status.HTTP_404_NOT_FOUND


async def test_deleting_a_module_cascades_to_items_change_sets_and_messages(
    db_session: AsyncSession,
) -> None:
    """Spec 3.7. Nothing here reaches Qdrant: the checklist owns no vector points."""
    from app.repositories.checklist_change_set import ChecklistChangeSetRepository
    from app.repositories.checklist_item import ChecklistItemRepository
    from app.repositories.checklist_message import ChecklistMessageRepository

    module = await create_checklist_module(db_session)
    await create_checklist_item(
        db_session,
        module_id=module.id,
        project_id=module.project_id,
        created_by=module.created_by,
    )
    await create_checklist_change_set(db_session, module_id=module.id)
    await create_checklist_message(db_session, module_id=module.id, created_by=module.created_by)
    service = ChecklistModuleService(db_session, Settings())

    await service.delete(
        module.id, actor=authenticated(await create_user(db_session, is_admin=True))
    )

    assert await ChecklistItemRepository(db_session).list_for_module(module.id) == []
    assert await ChecklistChangeSetRepository(db_session).pending_for_module(module.id) is None
    assert await ChecklistMessageRepository(db_session).list_for_module(module.id, limit=50) == []


async def test_create_refuses_a_project_that_is_not_ready(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    service = ChecklistModuleService(db_session, Settings())

    with pytest.raises(AppError) as caught:
        await service.create(
            ChecklistModuleCreateRequest(
                project_id=project.id, name="Auth", source_path="app/auth"
            ),
            actor=authenticated(await create_user(db_session)),
        )

    assert caught.value.code is ErrorCode.PROJECT_NOT_READY


async def test_create_normalises_the_path_and_starts_empty(db_session: AsyncSession) -> None:
    """`create`'s success path: the module starts `empty` with no generation behind it,
    and `source_path` is stored without leading or trailing slashes so it can be used as
    a scroll prefix directly."""
    project = await create_project(db_session)
    project.embedding_collection = "c"
    service = ChecklistModuleService(db_session, Settings())

    created = await service.create(
        ChecklistModuleCreateRequest(
            project_id=project.id, name="  Authentication  ", source_path="/app/auth/"
        ),
        actor=authenticated(await create_user(db_session)),
    )

    assert created.status is ChecklistModuleStatus.EMPTY
    assert created.source_path == "app/auth"
    assert created.name == "Authentication"
    assert created.item_count == 0
    assert created.pending_change_set_id is None
    assert created.stale is False


async def test_generation_publishes_a_job_and_returns_generating(
    db_session: AsyncSession,
) -> None:
    """`202` and it does not wait -- the shape `POST /projects` already uses (spec 4.1)."""
    project = await create_project(db_session)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    queue = InMemoryIngestionQueue()
    service = ChecklistModuleService(db_session, Settings())

    result = await service.request_generation(
        module.id, actor=authenticated(await create_user(db_session)), queue=queue
    )

    assert result.status is ChecklistModuleStatus.GENERATING
    assert len(queue.messages) == 1


async def test_generation_is_refused_while_one_is_running(
    db_session: AsyncSession,
) -> None:
    """A fast path for a nicer API response. It is NOT the guard -- the lease is
    (spec 4.5)."""
    project = await create_project(db_session)
    project.embedding_collection = "c"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(
        db_session, project_id=project.id, status=ChecklistModuleStatus.GENERATING
    )
    service = ChecklistModuleService(db_session, Settings())

    with pytest.raises(AppError) as caught:
        await service.request_generation(
            module.id,
            actor=authenticated(await create_user(db_session)),
            queue=InMemoryIngestionQueue(),
        )

    assert caught.value.status_code == status.HTTP_409_CONFLICT
    assert caught.value.code is ErrorCode.GENERATION_IN_PROGRESS


async def test_generation_is_refused_while_a_change_set_is_pending(
    db_session: AsyncSession,
) -> None:
    """Two overlapping diffs against the same items would have to be rebased against
    each other, and there is no sensible automatic answer (spec 3.3)."""
    project = await create_project(db_session)
    project.embedding_collection = "c"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    await create_checklist_change_set(
        db_session, module_id=module.id, status=ChangeSetStatus.PENDING
    )
    service = ChecklistModuleService(db_session, Settings())

    with pytest.raises(AppError) as caught:
        await service.request_generation(
            module.id,
            actor=authenticated(await create_user(db_session)),
            queue=InMemoryIngestionQueue(),
        )

    assert caught.value.code is ErrorCode.CHANGE_SET_PENDING


async def test_generation_does_not_apply_the_embedding_model_guard(
    db_session: AsyncSession,
) -> None:
    """That guard exists because a query embedded by a different model lands in a
    vector space the collection was never built in. Generation embeds nothing -- it
    filters and scrolls -- so there is no space to mismatch (spec 4.1)."""
    project = await create_project(db_session)
    project.embedding_collection = "c"
    project.embedding_model = "some-other-model"
    module = await create_checklist_module(db_session, project_id=project.id)
    queue = InMemoryIngestionQueue()
    service = ChecklistModuleService(db_session, Settings())

    result = await service.request_generation(
        module.id, actor=authenticated(await create_user(db_session)), queue=queue
    )

    assert result.status is ChecklistModuleStatus.GENERATING
    assert len(queue.messages) == 1


async def test_change_sets_for_returns_newest_first(db_session: AsyncSession) -> None:
    """The audit trail: newest first, so a reader sees the most recent proposal first.

    `created_at` is set explicitly rather than left to the column default: Postgres
    `now()` is transaction-scoped, so two rows inserted in this one transaction would
    otherwise share an identical timestamp, and `list_for_module`'s `id` tiebreaker is
    a random uuid4 that carries no ordering information -- see
    `test_pending_for_module_ignores_resolved_sets` in
    `tests/test_checklist_change_set_repository.py` for the same fix.
    """
    module = await create_checklist_module(db_session)
    started = datetime.now(UTC)
    older = ChecklistChangeSet(
        id=uuid.uuid4(),
        module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="older",
        operations=[],
        status=ChangeSetStatus.APPLIED.value,
        created_by=module.created_by,
        created_at=started,
    )
    newer = ChecklistChangeSet(
        id=uuid.uuid4(),
        module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="newer",
        operations=[],
        status=ChangeSetStatus.APPLIED.value,
        created_by=module.created_by,
        created_at=started + timedelta(seconds=1),
    )
    db_session.add_all([older, newer])
    await db_session.commit()
    service = ChecklistModuleService(db_session, Settings())

    change_sets = await service.change_sets_for(
        module.id, actor=authenticated(await create_user(db_session))
    )

    assert [row.id for row in change_sets] == [newer.id, older.id]


async def test_messages_are_readable_by_any_authenticated_user(
    db_session: AsyncSession,
) -> None:
    """The chat is shared, inverting the privacy rule that governs conversations,
    because it is the justification record for a document everyone can see (spec 2.4).
    A user who did not create the module -- not its creator, not an admin -- can still
    read its messages."""
    module = await create_checklist_module(db_session)
    await create_checklist_message(
        db_session,
        module_id=module.id,
        created_by=module.created_by,
        content="Why does this test expect 401?",
    )
    stranger = await create_user(db_session)
    service = ChecklistModuleService(db_session, Settings())

    messages = await service.messages(module.id, actor=authenticated(stranger))

    assert len(messages) == 1
    assert messages[0].content == "Why does this test expect 401?"
