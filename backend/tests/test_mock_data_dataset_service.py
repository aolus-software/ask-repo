"""Dataset reads, generation trigger, and the refinement chat."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.conversation import MessageRole
from app.models.mock_data import MockDataChangeSet, MockDataDatasetStatus, MockDataMessage
from app.models.project import ProjectStatus
from app.queue.protocol import InMemoryIngestionQueue
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.schemas.mock_data import MockDataGenerationRequest, MockDataMessageCreateRequest
from app.services.mock_data_dataset import MockDataDatasetService
from tests.factories import (
    create_checklist_module,
    create_mock_data_message,
    create_mock_data_record,
    create_project,
    create_user,
)
from tests.helpers import authenticated


async def test_get_returns_empty_summary_before_any_generation(
    db_session: AsyncSession,
) -> None:
    """Before the first generation, no dataset row exists and that is not a 404."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())

    detail = await service.get(module.id, actor=authenticated(await create_user(db_session)))

    assert detail.status == MockDataDatasetStatus.EMPTY
    assert detail.record_count == 0
    assert detail.records == []


async def test_request_generation_refuses_when_already_generating(
    db_session: AsyncSession,
) -> None:
    """Cannot request generation while one is in progress."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    queue = InMemoryIngestionQueue()
    user = await create_user(db_session)
    await service.request_generation(
        module.id, MockDataGenerationRequest(), actor=authenticated(user), queue=queue
    )

    with pytest.raises(AppError) as excinfo:
        await service.request_generation(
            module.id, MockDataGenerationRequest(), actor=authenticated(user), queue=queue
        )
    assert excinfo.value.status_code == status.HTTP_409_CONFLICT
    assert excinfo.value.code == ErrorCode.MOCK_DATA_GENERATION_IN_PROGRESS


async def test_request_generation_refuses_a_pending_change_set(
    db_session: AsyncSession,
) -> None:
    """Cannot request generation while changes are pending."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)
    await service.datasets.get_or_create_for_module(module.id)
    await db_session.commit()
    await MockDataChangeSetRepository(db_session).add(
        MockDataChangeSet(
            id=uuid.uuid4(),
            checklist_module_id=module.id,
            origin=ChangeSetOrigin.GENERATION.value,
            summary="s",
            operations=[],
            status=ChangeSetStatus.PENDING.value,
            created_by=user.id,
        )
    )
    await db_session.commit()

    with pytest.raises(AppError) as excinfo:
        await service.request_generation(
            module.id,
            MockDataGenerationRequest(),
            actor=authenticated(user),
            queue=InMemoryIngestionQueue(),
        )
    assert excinfo.value.code == ErrorCode.MOCK_DATA_CHANGE_SET_PENDING


async def test_get_accessible_by_any_authenticated_user(db_session: AsyncSession) -> None:
    """Phase 1: all projects are shared, so any authenticated user can read any module.
    The structure correctly goes through the access resolver (resolved_project_scope)."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    stranger = await create_user(db_session)

    # A stranger can read any module in phase 1
    detail = await service.get(module.id, actor=authenticated(stranger))

    assert detail.status == MockDataDatasetStatus.EMPTY


async def test_get_with_records_and_pending_change_set(db_session: AsyncSession) -> None:
    """When dataset has records and pending change set, get returns populated summary."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    # Create a dataset
    await service.datasets.get_or_create_for_module(module.id)
    await db_session.commit()

    # Add records
    await create_mock_data_record(db_session, module_id=module.id, fields={"name": "Record1"})
    await create_mock_data_record(db_session, module_id=module.id, fields={"name": "Record2"})
    await db_session.commit()

    # Add a pending change set
    change_set = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="Proposed changes",
        operations=[],
        status=ChangeSetStatus.PENDING.value,
        created_by=user.id,
    )
    await MockDataChangeSetRepository(db_session).add(change_set)
    await db_session.commit()

    detail = await service.get(module.id, actor=authenticated(user))

    assert detail.status == MockDataDatasetStatus.EMPTY  # default status on creation
    assert detail.record_count == 2
    assert detail.pending_change_set_id == change_set.id
    assert len(detail.records) == 2


async def test_get_stale_when_project_reindexed(db_session: AsyncSession) -> None:
    """When dataset.indexed_generation < project.active_generation, stale=True."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.active_generation = 3
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())

    dataset = await service.datasets.get_or_create_for_module(module.id)
    dataset.indexed_generation = 2
    await db_session.commit()

    detail = await service.get(module.id, actor=authenticated(await create_user(db_session)))

    assert detail.stale is True


async def test_change_sets_for_returns_newest_first(db_session: AsyncSession) -> None:
    """Change sets ordered by created_at descending, newest first."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    # Create change sets with explicit timestamps to control ordering
    started = datetime.now(UTC)
    older = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        origin=ChangeSetOrigin.GENERATION.value,
        summary="older",
        operations=[],
        status=ChangeSetStatus.APPLIED.value,
        created_by=user.id,
        created_at=started,
    )
    newer = MockDataChangeSet(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        origin=ChangeSetOrigin.CHAT.value,
        summary="newer",
        operations=[],
        status=ChangeSetStatus.PENDING.value,
        created_by=user.id,
        created_at=started + timedelta(seconds=1),
    )
    db_session.add_all([older, newer])
    await db_session.commit()

    change_sets = await service.change_sets_for(module.id, actor=authenticated(user))

    assert len(change_sets) == 2
    assert change_sets[0].id == newer.id
    assert change_sets[1].id == older.id


async def test_messages_are_readable_by_any_authenticated_user(
    db_session: AsyncSession,
) -> None:
    """Messages are shared; any authenticated user can read them. Ordering is
    deterministic (newest first) with explicit timestamps."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    creator = await create_user(db_session)
    stranger = await create_user(db_session)

    # Create messages with explicit timestamps to control ordering
    started = datetime.now(UTC)
    msg1 = MockDataMessage(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        role=MessageRole.USER.value,
        content="First message",
        created_by=creator.id,
        created_at=started,
    )
    msg2 = MockDataMessage(
        id=uuid.uuid4(),
        checklist_module_id=module.id,
        role=MessageRole.ASSISTANT.value,
        content="Second message",
        created_by=creator.id,
        created_at=started + timedelta(seconds=1),
    )
    db_session.add_all([msg1, msg2])
    await db_session.commit()

    messages = await service.messages(module.id, actor=authenticated(stranger))

    assert len(messages) == 2
    # Messages are returned oldest-first (see MockDataMessageRepository._latest)
    assert messages[0].id == msg1.id
    assert messages[0].content == "First message"
    assert messages[1].id == msg2.id
    assert messages[1].content == "Second message"


async def test_prepare_turn_creates_dataset_lazily(db_session: AsyncSession) -> None:
    """Dataset row is created on first turn if it doesn't exist."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    # Verify no dataset exists yet
    assert await service.datasets.get_by_module(module.id) is None

    context = await service.prepare_turn(
        module.id,
        MockDataMessageCreateRequest(question="What should we test?"),
        actor=authenticated(user),
    )

    # Dataset now exists
    dataset = await service.datasets.get_by_module(module.id)
    assert dataset is not None
    assert context.dataset_id == dataset.id


async def test_prepare_turn_creates_user_message(db_session: AsyncSession) -> None:
    """prepare_turn writes the user message to the database."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    context = await service.prepare_turn(
        module.id,
        MockDataMessageCreateRequest(question="What are the edge cases?"),
        actor=authenticated(user),
    )

    messages = await service.messages_repository.list_for_module(module.id, limit=50)
    assert len(messages) == 1
    assert messages[0].id == context.user_message_id
    assert messages[0].role == MessageRole.USER.value
    assert messages[0].content == "What are the edge cases?"
    assert messages[0].created_by == user.id


async def test_prepare_turn_mints_ids(db_session: AsyncSession) -> None:
    """prepare_turn mints change_set_id and assistant_message_id before any byte is sent."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    context = await service.prepare_turn(
        module.id,
        MockDataMessageCreateRequest(question="Test question"),
        actor=authenticated(user),
    )

    assert isinstance(context.assistant_message_id, uuid.UUID)
    assert isinstance(context.change_set_id, uuid.UUID)
    # IDs should be different
    assert context.assistant_message_id != context.change_set_id


async def test_prepare_turn_includes_existing_records(db_session: AsyncSession) -> None:
    """prepare_turn maps existing records from the database into the context."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    # Create existing records
    record1 = await create_mock_data_record(
        db_session, module_id=module.id, fields={"id": "r1", "name": "Test1"}
    )
    record2 = await create_mock_data_record(
        db_session, module_id=module.id, fields={"id": "r2", "name": "Test2"}
    )

    context = await service.prepare_turn(
        module.id,
        MockDataMessageCreateRequest(question="Test"),
        actor=authenticated(user),
    )

    assert len(context.existing_records) == 2
    record_ids = [rec.id for rec in context.existing_records]
    assert str(record1.id) in record_ids
    assert str(record2.id) in record_ids


async def test_prepare_turn_refuses_when_project_not_ready(db_session: AsyncSession) -> None:
    """prepare_turn requires project to be indexed and ready."""
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.prepare_turn(
            module.id,
            MockDataMessageCreateRequest(question="Test"),
            actor=authenticated(user),
        )
    assert excinfo.value.code == ErrorCode.PROJECT_NOT_READY


async def test_prepare_turn_refuses_when_embedding_model_changed(
    db_session: AsyncSession,
) -> None:
    """prepare_turn refuses when project was indexed with a different embedding model."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.embedding_model = "some-other-model"
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.prepare_turn(
            module.id,
            MockDataMessageCreateRequest(question="Test"),
            actor=authenticated(user),
        )
    assert excinfo.value.code == ErrorCode.EMBEDDING_MODEL_CHANGED


async def test_prepare_turn_refuses_while_generating(db_session: AsyncSession) -> None:
    """A refinement turn is refused while a generation holds the dataset's lease.

    `status == "generating"` is the only signal the reconcile sweep has that a worker
    still holds this dataset's lease (it is set before the claim and never changes
    during the run). Writing `review` over it here -- what a chat turn that proposes
    something would otherwise do -- would blind that sweep, and would leave a second
    pending change set behind if the worker finished normally instead.
    """
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    await service.request_generation(
        module.id,
        MockDataGenerationRequest(),
        actor=authenticated(user),
        queue=InMemoryIngestionQueue(),
    )

    with pytest.raises(AppError) as excinfo:
        await service.prepare_turn(
            module.id,
            MockDataMessageCreateRequest(question="Refine while generating"),
            actor=authenticated(user),
        )
    assert excinfo.value.status_code == status.HTTP_409_CONFLICT
    assert excinfo.value.code == ErrorCode.MOCK_DATA_GENERATION_IN_PROGRESS


async def test_request_generation_refuses_when_project_not_ready(
    db_session: AsyncSession,
) -> None:
    """request_generation requires project to be indexed."""
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.request_generation(
            module.id,
            MockDataGenerationRequest(),
            actor=authenticated(user),
            queue=InMemoryIngestionQueue(),
        )
    assert excinfo.value.code == ErrorCode.PROJECT_NOT_READY


async def test_prepare_turn_maps_history_from_prior_messages(
    db_session: AsyncSession,
) -> None:
    """prepare_turn builds history from recent prior messages with role and content."""
    project = await create_project(db_session)
    project.embedding_collection = "col"
    project.embedding_model = Settings().embedding_model
    module = await create_checklist_module(db_session, project_id=project.id)
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    # Create prior messages
    await create_mock_data_message(
        db_session,
        module_id=module.id,
        created_by=user.id,
        role=MessageRole.USER,
        content="Previous question",
    )
    await create_mock_data_message(
        db_session,
        module_id=module.id,
        created_by=user.id,
        role=MessageRole.ASSISTANT,
        content="Previous answer",
    )

    context = await service.prepare_turn(
        module.id,
        MockDataMessageCreateRequest(question="New question"),
        actor=authenticated(user),
    )

    # History should include the prior messages
    assert len(context.history) >= 2
    # Find the prior messages in history
    history_contents = [turn.content for turn in context.history]
    assert "Previous question" in history_contents
    assert "Previous answer" in history_contents


async def test_get_404s_on_nonexistent_module(db_session: AsyncSession) -> None:
    """get raises 404 for a nonexistent module id."""
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.get(uuid.uuid4(), actor=authenticated(user))

    assert excinfo.value.status_code == status.HTTP_404_NOT_FOUND


async def test_request_generation_404s_on_nonexistent_module(db_session: AsyncSession) -> None:
    """request_generation raises 404 for a nonexistent module id."""
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.request_generation(
            uuid.uuid4(),
            MockDataGenerationRequest(),
            actor=authenticated(user),
            queue=InMemoryIngestionQueue(),
        )

    assert excinfo.value.status_code == status.HTTP_404_NOT_FOUND


async def test_messages_404s_on_nonexistent_module(db_session: AsyncSession) -> None:
    """messages raises 404 for a nonexistent module id."""
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.messages(uuid.uuid4(), actor=authenticated(user))

    assert excinfo.value.status_code == status.HTTP_404_NOT_FOUND


async def test_change_sets_for_404s_on_nonexistent_module(db_session: AsyncSession) -> None:
    """change_sets_for raises 404 for a nonexistent module id."""
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.change_sets_for(uuid.uuid4(), actor=authenticated(user))

    assert excinfo.value.status_code == status.HTTP_404_NOT_FOUND


async def test_prepare_turn_404s_on_nonexistent_module(db_session: AsyncSession) -> None:
    """prepare_turn raises 404 for a nonexistent module id."""
    service = MockDataDatasetService(db_session, Settings())
    user = await create_user(db_session)

    with pytest.raises(AppError) as excinfo:
        await service.prepare_turn(
            uuid.uuid4(),
            MockDataMessageCreateRequest(question="Test"),
            actor=authenticated(user),
        )

    assert excinfo.value.status_code == status.HTTP_404_NOT_FOUND
