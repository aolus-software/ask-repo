"""Row builders shared by the project tests."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.conversation import Conversation
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
