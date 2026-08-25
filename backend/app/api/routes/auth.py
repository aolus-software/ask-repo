"""Login, session rotation, and password change.

No route here is behind the forced-password-change gate: the whole `/auth` prefix is
exempt, so a user with a temporary password can see who they are, keep a live token
while typing, and log out (`docs/PRD.md` §4.0).

Cookie mechanics live here rather than in the service, so the service stays testable
without a request or response object.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.core.rate_limit import (
    LoginAttemptLimiterDep,
    enforce_login_ip_limit,
    enforce_password_change_ip_limit,
)
from app.schemas.auth import AccessTokenResponse, ChangePasswordRequest, LoginRequest
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.user import UserResponse
from app.services.auth import AuthService

router = APIRouter(prefix="/auth", tags=["Auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]
RefreshCookie = Annotated[str | None, Cookie(alias="askrepo_refresh")]


def get_auth_service(
    session: SessionDep, settings: SettingsDep, attempts: LoginAttemptLimiterDep
) -> AuthService:
    """Provide the service with a request-scoped session.

    `attempts` is only exercised by `login`, but wiring it here rather than per-route
    keeps every handler down to one service call — see `.claude/rules/router.md`.
    Building a `LoginAttemptLimiter` does no I/O, so the routes that never touch it pay
    nothing for carrying it.
    """
    return AuthService(session, settings, attempts)


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def _set_refresh_cookie(response: Response, raw_token: str, settings: Settings) -> None:
    """Attach the rotated refresh token. httpOnly, so no script can read it."""
    response.set_cookie(
        key=settings.refresh_cookie_name,
        value=raw_token,
        max_age=settings.refresh_token_ttl_days * 24 * 60 * 60,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        key=settings.refresh_cookie_name,
        path=settings.refresh_cookie_path,
        secure=settings.refresh_cookie_secure,
        httponly=True,
        samesite=settings.refresh_cookie_samesite,
    )


@router.post(
    "/login",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Log in with email and password",
    dependencies=[Depends(enforce_login_ip_limit)],
    responses={code: ERROR_RESPONSES[code] for code in (401, 422, 429)},
)
async def login(
    payload: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AccessTokenResponse:
    token_response, raw_refresh = await service.login(payload.email, payload.password)
    _set_refresh_cookie(response, raw_refresh, settings)
    return token_response


@router.post(
    "/refresh",
    response_model=AccessTokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Rotate the refresh token and issue a new access token",
    responses={401: ERROR_RESPONSES[401]},
)
async def refresh(
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> AccessTokenResponse:
    token_response, raw_refresh = await service.refresh(refresh_token)
    _set_refresh_cookie(response, raw_refresh, settings)
    return token_response


@router.post(
    "/change-password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Change your own password",
    dependencies=[Depends(enforce_password_change_ip_limit)],
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 422, 429)},
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    service: AuthServiceDep,
    refresh_token: RefreshCookie = None,
) -> UserResponse:
    return await service.change_password(current_user.id, payload, refresh_token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out of this device",
    responses={},
)
async def logout(
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    refresh_token: RefreshCookie = None,
) -> None:
    await service.logout(refresh_token)
    _clear_refresh_cookie(response, settings)


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out of every device",
    responses={401: ERROR_RESPONSES[401]},
)
async def logout_all(
    response: Response,
    current_user: CurrentUser,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> None:
    await service.logout_all(current_user.id)
    _clear_refresh_cookie(response, settings)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="The current account",
    responses={401: ERROR_RESPONSES[401]},
)
async def me(current_user: CurrentUser, service: AuthServiceDep) -> UserResponse:
    return await service.current(current_user.id)
