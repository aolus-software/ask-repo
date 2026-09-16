"""The audit trail's wire shapes.

Two response models rather than one. `details` is capped at 8 KB and a
`role.updated` row carries two full permission lists, so shipping 25 of those to
render a scannable table is a lot of wire for content the table cannot show. The list
names the changed *fields*; the detail carries their values.
"""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.schemas.base import ApiModel
from app.schemas.pagination import ListQuery


class AuditEventSummary(ApiModel):
    """One row as the table renders it."""

    id: uuid.UUID
    created_at: datetime
    event_type: str
    outcome: str
    actor_user_id: uuid.UUID | None
    actor_email: str | None
    target_type: str | None
    target_id: uuid.UUID | None
    target_label: str | None
    project_id: uuid.UUID | None
    # Derived at read time from `details["changed"]`, never a stored column: a second
    # copy is derived state that can drift from the row it describes.
    changed_fields: list[str]


class AuditEventCurrent(ApiModel):
    """Live lookups, fenced off from the record.

    Under their own key precisely so a present-tense answer cannot be mistaken for
    part of the snapshot. Deliberately does **not** resolve a stored permission list
    against the role's current one — that would read as if the row knew something it
    does not.
    """

    actor_still_active: bool | None
    target_still_exists: bool | None


class AuditEventResponse(AuditEventSummary):
    """One row in full."""

    details: dict[str, object]
    ip_address: str | None
    current: AuditEventCurrent


class AuditEventListQuery(ListQuery):
    """`ListQuery` plus the audit filters.

    Fields on the model rather than sibling `Query(...)` parameters, and that is
    load-bearing: FastAPI flattens a Pydantic model used as `Annotated[Model,
    Query()]` into individual query parameters only while it is the **sole** query
    parameter of the route. Put a scalar beside it and the flattening stops, and every
    request fails with `{"request": "Field required"}` — naming nothing that appears
    in the signature.
    """

    event_type: str | None = None
    actor_user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    outcome: Literal["success", "failure"] | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None
    # Narrowed from `ListQuery`'s free string: `created_at` is the only ordering this
    # table has a meaningful answer for.
    sort: Literal["created_at"] | None = Field(default=None)
