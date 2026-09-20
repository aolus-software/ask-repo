"""Applying or discarding tells the other members, and never the person who clicked.

`docs/PRD.md` §2.1's wording is "a change set *someone else* applied". Actor exclusion
is per-event: telling you about your own click is noise, while telling you the reindex
you started twenty minutes ago has finished is the entire feature.

Reuses `tests/test_checklist_change_set_service.py` and
`tests/test_mock_data_change_set_service.py`'s harness (`tests.factories`,
`tests.helpers.authenticated`) rather than a fourth one, and
`tests/test_membership_routes.py`'s route-level style for the grant case.
"""

import uuid

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.audit import AuditRecorder
from app.core.notifications import NotificationType
from app.core.permissions import EDITOR_NAME
from app.db.session import get_sessionmaker
from app.models.notification import Notification, NotificationEvent
from app.models.user import User
from app.schemas.checklist import ChangeSetApplyRequest
from app.services.checklist_change_set import ChecklistChangeSetService
from tests.conftest import GrantMembership
from tests.factories import create_checklist_change_set, create_checklist_module
from tests.helpers import authenticated


async def _recipients(db_session: AsyncSession, event_type: NotificationType) -> set[uuid.UUID]:
    rows = await db_session.execute(
        select(Notification.user_id)
        .join(NotificationEvent, NotificationEvent.id == Notification.event_id)
        .where(NotificationEvent.event_type == event_type.value)
    )
    return set(rows.scalars().all())


def _add(operation_id: uuid.UUID) -> dict[str, object]:
    return {
        "op": "add",
        "id": str(operation_id),
        "feature": "Login",
        "testName": "Rejects a wrong password",
        "expectedResult": "401 INVALID_CREDENTIALS",
        "citations": None,
        "rationale": "The handler raises on a bcrypt mismatch.",
    }


async def test_apply_notifies_others_and_not_the_actor(
    db_session: AsyncSession, grant_membership: GrantMembership, user_a: User, user_b: User
) -> None:
    module = await create_checklist_module(db_session)
    await grant_membership(user_a.id, module.project_id, EDITOR_NAME)
    await grant_membership(user_b.id, module.project_id, EDITOR_NAME)
    change_set = await create_checklist_change_set(
        db_session, module_id=module.id, operations=[_add(uuid.uuid4())]
    )
    service = ChecklistChangeSetService(
        db_session, Settings(), recorder=AuditRecorder(get_sessionmaker())
    )

    await service.apply(
        change_set.id, ChangeSetApplyRequest(), actor=await authenticated(db_session, user_a)
    )

    recipients = await _recipients(db_session, NotificationType.CHECKLIST_CHANGE_SET_APPLIED)
    assert user_b.id in recipients
    assert user_a.id not in recipients


async def test_discard_notifies_others_and_not_the_actor(
    db_session: AsyncSession, grant_membership: GrantMembership, user_a: User, user_b: User
) -> None:
    module = await create_checklist_module(db_session)
    await grant_membership(user_a.id, module.project_id, EDITOR_NAME)
    await grant_membership(user_b.id, module.project_id, EDITOR_NAME)
    change_set = await create_checklist_change_set(db_session, module_id=module.id)
    service = ChecklistChangeSetService(
        db_session, Settings(), recorder=AuditRecorder(get_sessionmaker())
    )

    await service.discard(change_set.id, actor=await authenticated(db_session, user_a))

    recipients = await _recipients(db_session, NotificationType.CHECKLIST_CHANGE_SET_DISCARDED)
    assert user_b.id in recipients
    assert user_a.id not in recipients


async def _create_project(client: AsyncClient) -> str:
    response = await client.post(
        "/projects", json={"repoUrl": "https://github.com/o/r.git", "branch": "main"}
    )
    return str(response.json()["id"])


async def test_granting_membership_notifies_only_the_grantee(
    db_session: AsyncSession,
    client_for_user_a: AsyncClient,
    user_b: User,
) -> None:
    project_id = await _create_project(client_for_user_a)

    response = await client_for_user_a.post(
        f"/projects/{project_id}/members",
        json={"userId": str(user_b.id), "role": "viewer"},
    )
    assert response.status_code == 201

    recipients = await _recipients(db_session, NotificationType.MEMBERSHIP_GRANTED)
    assert list(recipients) == [user_b.id]
