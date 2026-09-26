"""Wire shapes for `/me` — the caller's own account surface.

Each model inherits `ApiModel`, so every key ships camelCase.
"""

import uuid
from datetime import datetime

from app.schemas.base import ApiModel


class MembershipSummary(ApiModel):
    """One project the caller is a member of, and their role on it."""

    project_id: uuid.UUID
    project_name: str
    role: str


class SessionResponse(ApiModel):
    """One of the caller's live sign-ins. `id` is the refresh-token family."""

    id: uuid.UUID
    user_agent: str | None
    ip_address: str | None
    started_at: datetime
    last_active_at: datetime
    expires_at: datetime
    current: bool


class ActivityEntry(ApiModel):
    """One audit row the caller is the actor of.

    Slimmer than the admin models on purpose: no `details`, no actor (always the
    caller), and none of `AuditEventResponse`'s live lookups, which cost a query a row.
    """

    id: uuid.UUID
    created_at: datetime
    event_type: str
    outcome: str
    target_label: str | None
    project_id: uuid.UUID | None
    ip_address: str | None
