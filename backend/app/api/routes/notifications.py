"""One caller's own notifications: the list, the unread count, and read state.

`is_admin` gates nothing here and there is no administrative view: conversations are
private for a stated reason, and notifications are private for the simpler one that
nothing needs to read someone else's. The *actions* behind these rows are already
visible to an administrator through `/audit-events` wherever they were audited.

None of these writes records an audit event — exemption 5 in
`.claude/rules/audit-trail.md`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, SessionDep, SettingsDep
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.notification import (
    MarkAllReadResponse,
    NotificationListQuery,
    NotificationSummary,
    UnreadCountResponse,
)
from app.schemas.pagination import PaginatedResponse
from app.services.notification import NotificationService

router = APIRouter(prefix="/notifications", tags=["Notifications"])


def get_notification_service(session: SessionDep, settings: SettingsDep) -> NotificationService:
    """Provide the service with a request-scoped session."""
    return NotificationService(session, settings)


NotificationServiceDep = Annotated[NotificationService, Depends(get_notification_service)]


@router.get(
    "",
    response_model=PaginatedResponse[NotificationSummary],
    status_code=status.HTTP_200_OK,
    summary="List my notifications",
    responses={code: ERROR_RESPONSES[code] for code in (401, 422)},
)
async def list_notifications(
    current_user: CurrentUser,
    service: NotificationServiceDep,
    query: Annotated[NotificationListQuery, Query()],
) -> PaginatedResponse[NotificationSummary]:
    return await service.list(current_user, query)


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    status_code=status.HTTP_200_OK,
    summary="How many unread notifications I have",
    responses={code: ERROR_RESPONSES[code] for code in (401,)},
)
async def unread_count(
    current_user: CurrentUser, service: NotificationServiceDep
) -> UnreadCountResponse:
    return UnreadCountResponse(count=await service.unread_count(current_user))


# Declared **before** `/{notification_id}/read`, or FastAPI matches `mark-all-read`
# as a `notification_id` and every call to either route 422s on UUID parsing.
@router.post(
    "/mark-all-read",
    response_model=MarkAllReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark every notification read",
    responses={code: ERROR_RESPONSES[code] for code in (401,)},
)
async def mark_all_read(
    current_user: CurrentUser, service: NotificationServiceDep
) -> MarkAllReadResponse:
    return MarkAllReadResponse(marked=await service.mark_all_read(current_user))


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Mark one notification read",
    responses={code: ERROR_RESPONSES[code] for code in (401, 404, 422)},
)
async def mark_read(
    notification_id: uuid.UUID, current_user: CurrentUser, service: NotificationServiceDep
) -> None:
    await service.mark_read(current_user, notification_id)
