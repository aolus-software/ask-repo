"""Row builders shared by the project tests."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistChangeSet,
    ChecklistItem,
    ChecklistItemSource,
    ChecklistItemStatus,
    ChecklistMessage,
    ChecklistModule,
    ChecklistModuleStatus,
)
from app.models.conversation import Conversation, MessageRole
from app.models.project import Project, ProjectStatus
from app.models.user import User


async def create_user(
    session: AsyncSession,
    *,
    email: str | None = None,
    is_admin: bool = False,
    name: str = "Test User",
) -> User:
    """A live account that has already changed its password."""
    user = User(
        id=uuid.uuid4(),
        name=name,
        email=email or f"user-{uuid.uuid4().hex[:8]}@example.com",
        # Cost 4 comes from the suite's BCRYPT_COST override; cost is not under test.
        password_hash=hash_password("correct-horse-battery", cost=4),
        is_admin=is_admin,
        must_change_password=False,
    )
    session.add(user)
    await session.flush()
    return user


async def create_project(
    session: AsyncSession,
    *,
    created_by: uuid.UUID | None = None,
    status: ProjectStatus = ProjectStatus.READY,
    repo_url: str = "https://github.com/acme/repo.git",
) -> Project:
    """A project owned by `created_by`, or by a freshly created user."""
    if created_by is None:
        created_by = (await create_user(session)).id
    project = Project(
        id=uuid.uuid4(),
        created_by=created_by,
        name="repo",
        repo_url=repo_url,
        branch="main",
        status=status.value,
    )
    session.add(project)
    await session.flush()
    return project


async def create_conversation(
    session: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    title: str | None = None,
) -> Conversation:
    """A conversation owned by `user_id`, against `project_id`."""
    if user_id is None:
        user_id = (await create_user(session)).id
    if project_id is None:
        project_id = (await create_project(session)).id
    conversation = Conversation(
        id=uuid.uuid4(), user_id=user_id, project_id=project_id, title=title
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def create_checklist_module(
    session: AsyncSession,
    *,
    project_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    name: str = "Authentication",
    source_path: str = "backend/app/api/routes",
    status: ChecklistModuleStatus = ChecklistModuleStatus.EMPTY,
    indexed_generation: int | None = None,
) -> ChecklistModule:
    """A module against `project_id`, or against a freshly created project."""
    if created_by is None:
        created_by = (await create_user(session)).id
    if project_id is None:
        project_id = (await create_project(session, created_by=created_by)).id
    module = ChecklistModule(
        id=uuid.uuid4(),
        project_id=project_id,
        created_by=created_by,
        name=name,
        source_path=source_path,
        status=status.value,
        indexed_generation=indexed_generation,
    )
    session.add(module)
    await session.flush()
    return module


async def create_checklist_item(
    session: AsyncSession,
    *,
    module_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    feature: str = "Login",
    test_name: str = "Rejects a wrong password",
    expected_result: str = "401 with code INVALID_CREDENTIALS",
    current_result: str | None = None,
    status: ChecklistItemStatus = ChecklistItemStatus.UNTESTED,
    source: ChecklistItemSource = ChecklistItemSource.GENERATED,
    position: int = 0,
) -> ChecklistItem:
    """One test case. `project_id` defaults to the module's, as a real insert does."""
    if module_id is None:
        module = await create_checklist_module(session, created_by=created_by)
        module_id, project_id, created_by = module.id, module.project_id, module.created_by
    if project_id is None or created_by is None:
        raise ValueError("pass project_id and created_by when passing module_id")
    item = ChecklistItem(
        id=uuid.uuid4(),
        module_id=module_id,
        project_id=project_id,
        feature=feature,
        test_name=test_name,
        expected_result=expected_result,
        current_result=current_result,
        status=status.value,
        source=source.value,
        position=position,
        created_by=created_by,
    )
    session.add(item)
    await session.flush()
    return item


async def create_checklist_change_set(
    session: AsyncSession,
    *,
    module_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
    origin: ChangeSetOrigin = ChangeSetOrigin.GENERATION,
    status: ChangeSetStatus = ChangeSetStatus.PENDING,
    summary: str = "1 added",
    operations: list[dict[str, object]] | None = None,
) -> ChecklistChangeSet:
    """A change set awaiting a decision."""
    if module_id is None:
        module = await create_checklist_module(session, created_by=created_by)
        module_id, created_by = module.id, module.created_by
    if created_by is None:
        created_by = (await create_user(session)).id
    change_set = ChecklistChangeSet(
        id=uuid.uuid4(),
        module_id=module_id,
        origin=origin.value,
        summary=summary,
        operations=operations if operations is not None else [],
        status=status.value,
        created_by=created_by,
    )
    session.add(change_set)
    await session.flush()
    return change_set


async def create_checklist_message(
    session: AsyncSession,
    *,
    module_id: uuid.UUID,
    created_by: uuid.UUID,
    role: MessageRole = MessageRole.USER,
    content: str = "Add a test for an empty password.",
) -> ChecklistMessage:
    """One chat turn against a module."""
    message = ChecklistMessage(
        id=uuid.uuid4(),
        module_id=module_id,
        role=role.value,
        content=content,
        created_by=created_by,
    )
    session.add(message)
    await session.flush()
    return message
