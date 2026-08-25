"""Account provisioning.

Reads are open to any authenticated user; mutations require an admin (D15). That is
why the dependencies are per-route rather than one router-level `require_admin` — from
M1 every project and QA pair shows `created_by`, and turning an id into a name should
not need an admin token.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.user import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)
from app.services.user import UserService

router = APIRouter(prefix="/users", tags=["Users"])


def get_user_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> UserService:
    """Provide the service with a request-scoped session."""
    return UserService(session, settings)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]


@router.get(
    "",
    response_model=PaginatedResponse[UserResponse],
    status_code=status.HTTP_200_OK,
    summary="List accounts",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 422)},
)
async def list_users(
    current_user: CurrentUser,
    service: UserServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[UserResponse]:
    return await service.list(query)


@router.get(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one account",
    responses={code: ERROR_RESPONSES[code] for code in (401, 404)},
)
async def get_user(
    user_id: uuid.UUID, current_user: CurrentUser, service: UserServiceDep
) -> UserResponse:
    return await service.get(user_id)


@router.post(
    "",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Provision an account",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 409, 422)},
)
async def create_user(
    payload: UserCreateRequest, current_user: AdminUser, service: UserServiceDep
) -> UserResponse:
    return await service.create(payload)


@router.patch(
    "/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an account's name or admin flag",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    current_user: AdminUser,
    service: UserServiceDep,
) -> UserResponse:
    return await service.update(user_id, payload)


@router.delete(
    "/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate an account",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409)},
)
async def delete_user(user_id: uuid.UUID, current_user: AdminUser, service: UserServiceDep) -> None:
    await service.soft_delete(user_id)


@router.post(
    "/{user_id}/reset-password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Set a temporary password for an account",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 404, 422)},
)
async def reset_user_password(
    user_id: uuid.UUID,
    payload: ResetPasswordRequest,
    current_user: AdminUser,
    service: UserServiceDep,
) -> UserResponse:
    return await service.reset_password(user_id, payload)
