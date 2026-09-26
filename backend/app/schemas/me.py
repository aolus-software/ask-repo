"""Wire shapes for `/me` — the caller's own account surface.

Each model inherits `ApiModel`, so every key ships camelCase.
"""

import uuid

from app.schemas.base import ApiModel


class MembershipSummary(ApiModel):
    """One project the caller is a member of, and their role on it."""

    project_id: uuid.UUID
    project_name: str
    role: str
