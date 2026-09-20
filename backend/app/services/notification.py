"""The notification read path.

Ownership comes from `app.core.access.resolve_notification_owner` — there is no
`user_id ==` filter constructed here, for the same reason no route filters projects on
its own.
"""

import uuid

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import resolve_notification_owner
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.core.notifications import NotificationType
from app.repositories.notification import NotificationRepository
from app.repositories.notification_preference import NotificationPreferenceRepository
from app.schemas.notification import (
    NotificationListQuery,
    NotificationPreferenceItem,
    NotificationPreferencesResponse,
    NotificationPreferencesUpdate,
    NotificationSummary,
)
from app.schemas.pagination import PaginatedResponse

# Phase 2.4 flips this when a mail provider exists. Until then the preference screen
# renders the email column disabled rather than offering a switch that does nothing.
EMAIL_TRANSPORT_ENABLED = False


class NotificationService:
    """Reads and read-state writes for one caller's notifications."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._notifications = NotificationRepository(session)
        self._preferences = NotificationPreferenceRepository(session)

    async def list(
        self, user: AuthenticatedUser, query: NotificationListQuery
    ) -> PaginatedResponse[NotificationSummary]:
        """One page of this caller's own notifications, newest first."""
        owner = resolve_notification_owner(user)
        rows, total = await self._notifications.page(
            owner,
            page=query.page,
            limit=query.limit,
            unread_only=query.unread_only,
            project_id=query.project_id,
            event_type=query.event_type,
        )
        items = [
            NotificationSummary(
                id=notification.id,
                created_at=notification.created_at,
                read_at=notification.read_at,
                event_type=event.event_type,
                project_id=event.project_id,
                target_type=event.target_type,
                target_id=event.target_id,
                actor_user_id=event.actor_user_id,
                details=event.details,
            )
            for notification, event in rows
        ]
        return PaginatedResponse.build(items, page=query.page, limit=query.limit, total_count=total)

    async def unread_count(self, user: AuthenticatedUser) -> int:
        """What the bell polls."""
        return await self._notifications.unread_count(resolve_notification_owner(user))

    async def mark_read(self, user: AuthenticatedUser, notification_id: uuid.UUID) -> None:
        """Mark one read.

        A row belonging to someone else is `404`, not `403`: a `403` would confirm it
        exists, which is `response-api.md`'s distinction running backwards.
        """
        owner = resolve_notification_owner(user)
        if not await self._notifications.mark_read(owner, notification_id):
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.NOTIFICATION_NOT_FOUND,
                "Notification not found.",
            )
        await self.session.commit()

    async def mark_all_read(self, user: AuthenticatedUser) -> int:
        """Mark every visible unread notification read. Returns how many."""
        marked = await self._notifications.mark_all_read(resolve_notification_owner(user))
        await self.session.commit()
        return marked

    async def preferences(self, user: AuthenticatedUser) -> NotificationPreferencesResponse:
        """Every event type, with the sparse rows' gaps filled in as on."""
        stored = await self._preferences.map_for(resolve_notification_owner(user))
        items = [
            NotificationPreferenceItem(
                event_type=event.value,
                in_app=stored.get(event.value, (True, True))[0],
                email=stored.get(event.value, (True, True))[1],
            )
            for event in NotificationType
        ]
        return NotificationPreferencesResponse(items=items, email_enabled=EMAIL_TRANSPORT_ENABLED)

    async def update_preferences(
        self, user: AuthenticatedUser, payload: NotificationPreferencesUpdate
    ) -> NotificationPreferencesResponse:
        """Replace the whole preference set. Refuses an event type the catalogue
        does not name.

        `400`, not `422`: the string is well-formed and passed schema validation, so
        this is "semantically invalid input" per `.claude/rules/response-api.md` —
        the same reasoning as `MODULE_PATH_NOT_INDEXED`
        (`app/services/checklist_module.py`). `422` is reserved for FastAPI's own
        `RequestValidationError`.
        """
        known = {event.value for event in NotificationType}
        unknown = sorted({item.event_type for item in payload.items} - known)
        if unknown:
            raise AppError(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.UNKNOWN_EVENT_TYPE,
                f"Unknown event type: {', '.join(unknown)}",
            )
        await self._preferences.upsert_many(
            resolve_notification_owner(user),
            {item.event_type: (item.in_app, item.email) for item in payload.items},
        )
        await self.session.commit()
        return await self.preferences(user)
