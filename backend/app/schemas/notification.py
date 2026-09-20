"""The notification wire shapes.

One response model, not two: unlike `audit_events`, `details` here is capped at 2 KB
and carries no diff, so there is nothing a detail view would show that the list cannot.
"""

import uuid
from datetime import datetime

from app.schemas.base import ApiModel
from app.schemas.pagination import ListQuery


class NotificationSummary(ApiModel):
    """One notification, as both the popover and the page render it."""

    id: uuid.UUID
    created_at: datetime
    read_at: datetime | None
    event_type: str
    project_id: uuid.UUID
    target_type: str | None
    target_id: uuid.UUID | None
    actor_user_id: uuid.UUID | None
    details: dict[str, object]


class NotificationListQuery(ListQuery):
    """Extra filters, **on the subclass**.

    Never beside `ListQuery` as a separate scalar: FastAPI flattens a Pydantic model
    used as `Annotated[Model, Query()]` into individual query parameters only while it
    is the sole query parameter of the route. Add a scalar next to it and every request
    fails with `{"request": "Field required"}`, naming nothing in the signature.

    `event_type`, not `type`: `frontend/lib/api/endpoints.ts`'s
    `notificationListQueryString` sends `eventType`, matching `AuditEventListQuery`'s
    naming for the same filter shape.
    """

    unread_only: bool = False
    project_id: uuid.UUID | None = None
    event_type: str | None = None
    # No `sort` field: `created_at` is the only ordering this list has a meaningful
    # answer for, so there is nothing for a field naming it to select between —
    # `sort_direction` (inherited from `ListQuery`) is the only ordering choice this
    # route offers, and it is honoured in `NotificationRepository.page`.


class UnreadCountResponse(ApiModel):
    """What the bell polls."""

    count: int


class MarkAllReadResponse(ApiModel):
    """How many rows the sweep marked."""

    marked: int


class NotificationPreferenceItem(ApiModel):
    """One event type's two switches."""

    event_type: str
    in_app: bool
    email: bool


class NotificationPreferencesResponse(ApiModel):
    """Every event type, with gaps filled in.

    Stored rows are sparse and absence means on, so this endpoint materialises the
    defaults rather than making the client know the rule. `email_enabled` is `False`
    until Phase 2.4 ships a sender, and is what greys the email column out.
    """

    items: list[NotificationPreferenceItem]
    email_enabled: bool


class NotificationPreferencesUpdate(ApiModel):
    """The whole set, saved as a unit."""

    items: list[NotificationPreferenceItem]
