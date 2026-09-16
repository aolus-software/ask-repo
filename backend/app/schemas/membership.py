"""Wire shapes for project membership. Every model inherits `ApiModel`, so the JSON
is camelCase while the attributes stay snake_case (`app/schemas/base.py`)."""

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.base import ApiModel


class MemberResponse(ApiModel):
    """One person's access to a project."""

    user_id: uuid.UUID
    name: str
    email: str
    role: str
    granted_by: uuid.UUID | None
    granted_at: datetime


class MemberCreateRequest(ApiModel):
    """Grant a role to a user on this project."""

    user_id: uuid.UUID
    role: str = Field(min_length=1, max_length=64)


class MemberUpdateRequest(ApiModel):
    """Change an existing member's role."""

    role: str = Field(min_length=1, max_length=64)
