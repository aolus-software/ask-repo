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
from app.repositories.project import ProjectRepository
from app.schemas.checklist import (
    ChecklistModuleCreateRequest,
    ChecklistModuleListQuery,
    ChecklistModuleUpdateRequest,
)
from tests.factories import (
    create_checklist_change_set,
    create_checklist_item,
    create_checklist_message,
    create_checklist_module,
    create_project,
    create_user,
)
from tests.helpers import (  # `authenticated`: `AuthenticatedUser` from a `User` row
    authenticated,
    checklist_module_service,
)


async def test_list_shows_modules_other_people_created(db_session: AsyncSession) -> None:
    """Phase 1 sharing is intended (docs/PRD.md 4.1). `created_by` gates destruction."""
    mine = await create_checklist_module(db_session)
    other = await create_user(db_session)
    await create_checklist_module(db_session, created_by=other.id)
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

    detail = await service.get(module.id, actor=authenticated(await create_user(db_session)))

    assert detail.stale is True


async def test_editing_someone_elses_module_is_403_not_404(
    db_session: AsyncSession,
) -> None:
    """Module existence is deliberately public, so hiding it would only confuse
    (.claude/rules/response-api.md)."""
    module = await create_checklist_module(db_session)
    stranger = await create_user(db_session)
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

    await service.delete(
        module.id, actor=authenticated(await create_user(db_session, is_admin=True))
    )

    assert await ChecklistItemRepository(db_session).list_for_module(module.id) == []
    assert await ChecklistChangeSetRepository(db_session).pending_for_module(module.id) is None
    assert await ChecklistMessageRepository(db_session).list_for_module(module.id, limit=50) == []


async def test_deleting_a_module_cascades_to_its_mock_dataset(
    db_session: AsyncSession,
) -> None:
    """A module's mock dataset shares its lifecycle even though it generates
    independently -- deleting the module must not orphan mock-data rows."""
    from app.models.mock_data import MockDataChangeSet
    from app.repositories.mock_data_change_set import MockDataChangeSetRepository
    from app.repositories.mock_data_dataset import MockDataDatasetRepository
    from app.repositories.mock_data_message import MockDataMessageRepository
    from app.repositories.mock_data_record import MockDataRecordRepository
    from tests.factories import create_mock_data_message, create_mock_data_record

    module = await create_checklist_module(db_session)
    await create_mock_data_record(db_session, module_id=module.id, created_by=module.created_by)
    await create_mock_data_message(db_session, module_id=module.id, created_by=module.created_by)
    db_session.add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="1 added",
            operations=[],
            status=ChangeSetStatus.PENDING.value,
            created_by=module.created_by,
        )
    )
    await MockDataDatasetRepository(db_session).get_or_create_for_module(module.id)
    await db_session.flush()
    service = checklist_module_service(db_session)

    await service.delete(
        module.id, actor=authenticated(await create_user(db_session, is_admin=True))
    )

    assert await MockDataRecordRepository(db_session).list_for_module(module.id) == []
    assert await MockDataChangeSetRepository(db_session).pending_for_module(module.id) is None
    assert await MockDataMessageRepository(db_session).list_for_module(module.id, limit=50) == []
    assert await MockDataDatasetRepository(db_session).get_by_module(module.id) is None


async def test_create_refuses_a_project_that_is_not_ready(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

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


async def test_create_refuses_a_path_that_matches_nothing_in_the_index(
    db_session: AsyncSession,
) -> None:
    """Phase 1.1 (docs/PRD.md 2.1). Without this the module is created, returns `201`,
    and the mistake only surfaces later and silently when generation cannot match
    anything under it."""
    project = await create_project(db_session)
    project.embedding_collection = "c"
    service = checklist_module_service(db_session, "backend/app/config.py")

    with pytest.raises(AppError) as caught:
        await service.create(
            ChecklistModuleCreateRequest(
                project_id=project.id, name="Auth", source_path="backend/app/authz"
            ),
            actor=authenticated(await create_user(db_session)),
        )

    # 400, not 422: the string is well-formed and passed schema validation, so this is
    # semantically invalid input (`.claude/rules/response-api.md`).
    assert caught.value.status_code == status.HTTP_400_BAD_REQUEST
    assert caught.value.code is ErrorCode.MODULE_PATH_NOT_INDEXED


async def test_repointing_a_module_at_an_unindexed_path_is_refused(
    db_session: AsyncSession,
) -> None:
    """The same check on `update`, so the picker cannot be bypassed by editing."""
    project = await create_project(db_session)
    project.embedding_collection = "c"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = checklist_module_service(db_session, "backend/app/api/routes/auth.py")

    with pytest.raises(AppError) as caught:
        await service.update(
            module.id,
            ChecklistModuleUpdateRequest(source_path="nowhere/at/all"),
            actor=authenticated(await create_user(db_session, is_admin=True)),
        )

    assert caught.value.code is ErrorCode.MODULE_PATH_NOT_INDEXED


async def test_renaming_a_module_needs_no_index_at_all(db_session: AsyncSession) -> None:
    """Only a re-point is validated. A rename has to keep working whatever state the
    project is in, and there is nothing to validate a name against."""
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    module = await create_checklist_module(db_session, project_id=project.id)
    service = checklist_module_service(db_session)

    renamed = await service.update(
        module.id,
        ChecklistModuleUpdateRequest(name="Renamed"),
        actor=authenticated(await create_user(db_session, is_admin=True)),
    )

    assert renamed.name == "Renamed"


async def test_generation_publishes_a_job_and_returns_generating(
    db_session: AsyncSession,
) -> None:
    """`202` and it does not wait -- the shape `POST /projects` already uses (spec 4.1)."""
    project = await create_project(db_session)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    queue = InMemoryIngestionQueue()
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

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
    service = checklist_module_service(db_session)

    messages = await service.messages(module.id, actor=authenticated(stranger))

    assert len(messages) == 1
    assert messages[0].content == "Why does this test expect 401?"


async def test_summaries_carry_the_project_name(db_session: AsyncSession) -> None:
    """The list renders the project a module belongs to, so the row carries its name.

    An id alone would make the screen resolve twenty-five names client-side, which is
    the N+1 `_summaries` exists to avoid moved into the browser.
    """
    project = await create_project(db_session, name="checkout-service")
    module = await create_checklist_module(db_session, project_id=project.id)
    service = checklist_module_service(db_session)
    actor = authenticated(await create_user(db_session))

    page = await service.list(ChecklistModuleListQuery(), actor=actor)
    detail = await service.get(module.id, actor=actor)

    assert page.items[0].project_name == "checkout-service"
    assert detail.project_name == "checkout-service"


async def test_generation_is_refused_while_a_reindex_is_in_flight(
    db_session: AsyncSession,
) -> None:
    """`docs/PRD.md` §7's third known bug. A reindex keeps `status` at `ready`, so
    `_require_indexed` passes throughout one. A generation that slips through scrolls
    the current generation, stamps `indexed_generation` with it, and then the reindex
    flips the pointer and deletes those points -- the module reports `stale` the
    moment it finishes, built from an index that no longer exists.
    """
    module = await create_checklist_module(db_session)
    project = await ProjectRepository(db_session).get(module.project_id)
    assert project is not None
    project.status = ProjectStatus.READY.value
    project.embedding_collection = "code_chunks__x"
    project.reindex_in_progress = True
    await db_session.commit()
    service = checklist_module_service(db_session)
    queue = InMemoryIngestionQueue()

    with pytest.raises(AppError) as raised:
        await service.request_generation(
            module.id, actor=authenticated(await create_user(db_session)), queue=queue
        )

    assert raised.value.status_code == 409
    assert raised.value.code is ErrorCode.PROJECT_NOT_READY
    assert queue.messages == []
    await db_session.refresh(module)
    assert module.status != ChecklistModuleStatus.GENERATING.value


async def test_the_refinement_chat_is_not_refused_during_a_reindex(
    db_session: AsyncSession,
) -> None:
    """The asymmetry is deliberate. A chat turn reads the live generation and stamps
    nothing, and a reindex can run for twenty minutes -- silencing it for that long
    would cost far more than the guard saves. Only the generation paths take it.
    """
    module = await create_checklist_module(db_session)
    project = await ProjectRepository(db_session).get(module.project_id)
    assert project is not None
    project.status = ProjectStatus.READY.value
    project.embedding_collection = "code_chunks__x"
    project.embedding_model = Settings().embedding_model
    project.reindex_in_progress = True
    await db_session.commit()

    checklist_module_service(db_session)._require_answerable(project)
