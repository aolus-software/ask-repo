"""Queries over `project_memberships`.

`count_live_owners` is the one worth reading carefully: "live" means the membership
is not soft-deleted **and the user row is not either**, because deactivating someone
deliberately leaves their memberships intact so reactivation restores exact access.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import Permission
from app.models.membership import ProjectMembership, Role
from app.models.user import User
from app.repositories.membership import MembershipRepository
from tests.factories import create_project, create_user


async def _deactivated_user(session: AsyncSession) -> User:
    """An account whose memberships survive its deactivation, as the real flow leaves them."""
    user = await create_user(session)
    user.deleted_at = datetime.now(UTC)
    await session.flush()
    return user


async def _role(session: AsyncSession, name: str) -> Role:
    return (await session.execute(select(Role).where(Role.name == name))).scalar_one()


async def test_load_grants_returns_role_name_and_expanded_permissions(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id, grant_owner=False)
    viewer = await _role(db_session, "viewer")
    db_session.add(
        ProjectMembership(
            id=uuid.uuid4(), user_id=user.id, project_id=project.id, role_id=viewer.id
        )
    )
    await db_session.commit()

    grants = await MembershipRepository(db_session).load_grants(user.id)

    role_name, permissions = grants[project.id]
    assert role_name == "viewer"
    assert Permission.QUESTION_ASK.value in permissions
    assert Permission.PROJECT_DELETE.value not in permissions


async def test_load_grants_is_empty_for_a_user_with_no_membership(
    db_session: AsyncSession,
) -> None:
    user = await create_user(db_session)
    await db_session.commit()

    assert await MembershipRepository(db_session).load_grants(user.id) == {}


async def test_load_grants_ignores_a_revoked_membership(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    project = await create_project(db_session, created_by=user.id, grant_owner=False)
    viewer = await _role(db_session, "viewer")
    db_session.add(
        ProjectMembership(
            id=uuid.uuid4(),
            user_id=user.id,
            project_id=project.id,
            role_id=viewer.id,
            deleted_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    assert await MembershipRepository(db_session).load_grants(user.id) == {}


async def test_count_live_owners_ignores_a_deactivated_user(db_session: AsyncSession) -> None:
    """Deactivation leaves memberships intact, so the count must read through to the
    user row. Counting the row alone would report an owner who cannot log in."""
    creator = await create_user(db_session)
    project = await create_project(db_session, created_by=creator.id, grant_owner=False)
    departed = await _deactivated_user(db_session)
    owner = await _role(db_session, "owner")
    db_session.add_all(
        [
            ProjectMembership(
                id=uuid.uuid4(), user_id=creator.id, project_id=project.id, role_id=owner.id
            ),
            ProjectMembership(
                id=uuid.uuid4(), user_id=departed.id, project_id=project.id, role_id=owner.id
            ),
        ]
    )
    await db_session.commit()

    count = await MembershipRepository(db_session).count_live_owners(project.id)

    assert count == 1


async def test_count_live_owners_can_exclude_one_user(db_session: AsyncSession) -> None:
    """The 'would this operation leave none?' question, same shape as
    UserRepository.count_active_admins."""
    creator = await create_user(db_session)
    project = await create_project(db_session, created_by=creator.id, grant_owner=False)
    owner = await _role(db_session, "owner")
    db_session.add(
        ProjectMembership(
            id=uuid.uuid4(), user_id=creator.id, project_id=project.id, role_id=owner.id
        )
    )
    await db_session.commit()

    count = await MembershipRepository(db_session).count_live_owners(
        project.id, excluding_user=creator.id
    )

    assert count == 0


async def test_projects_solely_owned_by_lists_what_deactivation_would_strand(
    db_session: AsyncSession,
) -> None:
    creator = await create_user(db_session)
    stranded = await create_project(db_session, created_by=creator.id, grant_owner=False)
    shared = await create_project(db_session, created_by=creator.id, grant_owner=False)
    second_owner = await create_user(db_session)
    owner = await _role(db_session, "owner")
    db_session.add_all(
        [
            ProjectMembership(
                id=uuid.uuid4(), user_id=creator.id, project_id=stranded.id, role_id=owner.id
            ),
            ProjectMembership(
                id=uuid.uuid4(), user_id=creator.id, project_id=shared.id, role_id=owner.id
            ),
            ProjectMembership(
                id=uuid.uuid4(), user_id=second_owner.id, project_id=shared.id, role_id=owner.id
            ),
        ]
    )
    await db_session.commit()

    at_risk = await MembershipRepository(db_session).projects_solely_owned_by(creator.id)

    assert list(at_risk) == [stranded.id]
