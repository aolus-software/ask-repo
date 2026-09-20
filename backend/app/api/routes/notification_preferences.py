"""One caller's own notification preferences.

Split from `app/api/routes/notifications.py` even though both come from the same
brief: `.claude/rules/router.md` requires one router per resource, and
`/notifications` and `/notification-preferences` are two resources with two prefixes.

None of these writes records an audit event — exemption 5 in
`.claude/rules/audit-trail.md`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, SessionDep
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.notification import (
    NotificationPreferencesResponse,
    NotificationPreferencesUpdate,
)
from app.services.notification import NotificationService

router = APIRouter(prefix="/notification-preferences", tags=["Notification Preferences"])


def get_notification_service(session: SessionDep) -> NotificationService:
    """Provide the service with a request-scoped session."""
    return NotificationService(session)


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


@router.get(
    "",
    response_model=NotificationPreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="My notification preferences",
    responses={code: ERROR_RESPONSES[code] for code in (401,)},
)
async def get_preferences(
    current_user: CurrentUser, service: NotificationServiceDep
) -> NotificationPreferencesResponse:
    return await service.preferences(current_user)


@router.put(
    "",
    response_model=NotificationPreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace my notification preferences",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 422)},
)
async def put_preferences(
    payload: NotificationPreferencesUpdate,
    current_user: CurrentUser,
    service: NotificationServiceDep,
) -> NotificationPreferencesResponse:
    return await service.update_preferences(current_user, payload)
