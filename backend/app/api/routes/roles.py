"""`/roles` and `/permissions` — instance-wide role definitions.

Admin-only, enforced by the router-level `AdminUser` dependency rather than per route,
so a route added later is gated with no action taken.
"""

import uuid
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import SessionDep, require_admin
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.role import (
    PermissionCatalogResponse,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
)
from app.services.role import RoleService

# Admin gating is router-level, not per route, so a route added to this file later is
# gated with no action taken — the same reasoning as the forced-password-change
# middleware. `users.py` gates per route with `AdminUser`; both spellings exist, and
# router-level is right here because every route in this file is admin-only.
router = APIRouter(tags=["roles"], dependencies=[Depends(require_admin)])


def _service(session: SessionDep) -> RoleService:
    return RoleService(session)


ServiceDep = Annotated[RoleService, Depends(_service)]


@router.get(
    "/permissions",
    response_model=PermissionCatalogResponse,
    summary="List every permission, grouped",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_permissions(service: ServiceDep) -> PermissionCatalogResponse:
    """The permission catalogue, grouped for the role-matrix editor."""
    return service.catalogue()


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    summary="List roles",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_roles(service: ServiceDep) -> Sequence[RoleResponse]:
    """Every role on the instance, system roles first."""
    return await service.list_roles()


@router.post(
    "/roles",
    response_model=RoleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom role",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 409, 422)},
)
async def create_role(payload: RoleCreateRequest, service: ServiceDep) -> RoleResponse:
    """Create a custom role."""
    return await service.create(payload)


@router.patch(
    "/roles/{role_id}",
    response_model=RoleResponse,
    summary="Rename a custom role or replace its permissions",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def update_role(
    role_id: uuid.UUID, payload: RoleUpdateRequest, service: ServiceDep
) -> RoleResponse:
    """Rename a custom role and/or replace its permissions."""
    return await service.update(role_id, payload)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a custom role",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def delete_role(role_id: uuid.UUID, service: ServiceDep) -> None:
    """Soft-delete a custom role that nobody holds."""
    await service.delete(role_id)
