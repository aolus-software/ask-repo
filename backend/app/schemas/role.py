"""Wire shapes for role definitions."""

import uuid

from pydantic import Field, field_validator

from app.core.permissions import Permission
from app.schemas.base import ApiModel


class RoleResponse(ApiModel):
    """A role and what it can do."""

    id: uuid.UUID
    name: str
    description: str | None
    is_system: bool
    permissions: list[str]
    member_count: int


class RoleCreateRequest(ApiModel):
    """Create a custom role. Permissions are set separately on the matrix page."""

    name: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)


class RoleUpdateRequest(ApiModel):
    """Rename a custom role and/or replace its permission set."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=255)
    permissions: list[str] | None = None

    @field_validator("permissions")
    @classmethod
    def _known_permissions(cls, value: list[str] | None) -> list[str] | None:
        """Refuse a permission that is not in the catalogue.

        Existence is anchored in `Permission`, never in the database
        (`app/core/permissions.py`), so an unknown string is a client bug and must
        not be stored — a row nothing asks for is silently dead weight.
        """
        if value is None:
            return None
        known = {p.value for p in Permission}
        unknown = sorted(set(value) - known)
        if unknown:
            raise ValueError(f"unknown permissions: {', '.join(unknown)}")
        return value


class PermissionGroupResponse(ApiModel):
    """One section of the role-matrix UI."""

    label: str
    permissions: list[str]


class PermissionCatalogResponse(ApiModel):
    """Every permission, grouped and labelled for the matrix editor."""

    groups: list[PermissionGroupResponse]
