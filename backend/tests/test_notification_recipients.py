"""Who hears about a project-scoped event.

These are the tests that stop a notification naming a private repository to someone
who was never given it — `docs/PRD.md` §2.1 names that as the failure mode, not an
empty list.
"""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import resolve_notification_recipients
from app.core.permissions import Permission
from app.models.user import User
from app.repositories.membership import MembershipRepository
from tests.conftest import GrantMembership


@pytest.fixture
async def memberships(db_session: AsyncSession) -> MembershipRepository:
    return MembershipRepository(db_session)


async def test_a_viewer_hears_about_project_read_events(
    memberships: MembershipRepository,
    grant_membership: GrantMembership,
    user_a: User,
    project_id: uuid.UUID,
) -> None:
    await grant_membership(user_a.id, project_id, "viewer")
    recipients = await resolve_notification_recipients(
        memberships, project_id, Permission.PROJECT_READ, excluding=None
    )
    assert user_a.id in recipients


async def test_a_viewer_does_not_hear_about_changeset_apply_events(
    memberships: MembershipRepository,
    grant_membership: GrantMembership,
    user_a: User,
    project_id: uuid.UUID,
) -> None:
    await grant_membership(user_a.id, project_id, "viewer")
    recipients = await resolve_notification_recipients(
        memberships, project_id, Permission.CHANGESET_APPLY, excluding=None
    )
    assert user_a.id not in recipients


async def test_an_admin_with_no_membership_hears_nothing(
    memberships: MembershipRepository, admin_user: User, project_id: uuid.UUID
) -> None:
    """Permission to see a thing is not interest in hearing about it.

    `require_permission` lets an administrator pass every check. Mirroring that here
    would mail every admin about every project on the instance. Adding an `is_admin`
    branch for symmetry is the bug, not the fix.
    """
    recipients = await resolve_notification_recipients(
        memberships, project_id, Permission.PROJECT_READ, excluding=None
    )
    assert admin_user.id not in recipients


async def test_a_deactivated_member_hears_nothing(
    db_session: AsyncSession,
    memberships: MembershipRepository,
    grant_membership: GrantMembership,
    user_a: User,
    project_id: uuid.UUID,
) -> None:
    """Deactivation leaves memberships intact so reactivation restores exact access,
    which means a membership row can exist for someone who cannot log in. A row for
    them is an unread count nobody will ever clear."""
    await grant_membership(user_a.id, project_id, "owner")
    user_a.deleted_at = datetime.now(UTC)
    await db_session.flush()
    recipients = await resolve_notification_recipients(
        memberships, project_id, Permission.PROJECT_READ, excluding=None
    )
    assert user_a.id not in recipients


async def test_excluding_drops_the_actor(
    memberships: MembershipRepository,
    grant_membership: GrantMembership,
    user_a: User,
    user_b: User,
    project_id: uuid.UUID,
) -> None:
    await grant_membership(user_a.id, project_id, "editor")
    await grant_membership(user_b.id, project_id, "editor")
    recipients = await resolve_notification_recipients(
        memberships, project_id, Permission.CHECKLIST_READ, excluding=user_a.id
    )
    assert recipients == frozenset({user_b.id})


async def test_a_member_of_another_project_hears_nothing(
    memberships: MembershipRepository,
    grant_membership: GrantMembership,
    user_a: User,
    project_id: uuid.UUID,
    other_project_id: uuid.UUID,
) -> None:
    await grant_membership(user_a.id, other_project_id, "owner")
    recipients = await resolve_notification_recipients(
        memberships, project_id, Permission.PROJECT_READ, excluding=None
    )
    assert user_a.id not in recipients
