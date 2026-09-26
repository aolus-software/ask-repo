"""Login, session rotation, and password change.

No route here is behind the forced-password-change gate: the whole `/auth` prefix is
exempt, so a user with a temporary password can see who they are, keep a live token
while typing, and log out (`docs/PRD.md` §4.0).

Cookie mechanics live here rather than in the service, so the service stays testable
without a request or response object.
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, Request, Response, status

from app.api.deps import AuditRecorderDep, ClientIpDep, CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.core.rate_limit import (
    LoginAttemptLimiterDep,
    RateLimiterDep,
    enforce_login_ip_limit,
    enforce_password_change_ip_limit,
    enforce_password_reset_email_limit,
    enforce_password_reset_ip_limit,
)
from app.db.session import get_sessionmaker
from app.mail.sender import MailSenderDep
from app.schemas.auth import (
    AccessTokenResponse,
    ChangePasswordRequest,
    LoginRequest,
    PasswordPolicyResponse,
)
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.password_reset import (
    PasswordResetAvailability,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from app.schemas.user import UserResponse
from app.services.auth import AuthService
from app.services.password_reset import PasswordResetService, deliver_password_reset

router = APIRouter(prefix="/auth", tags=["Auth"])

SettingsDep = Annotated[Settings, Depends(get_settings)]


def _read_refresh_cookie(request: Request, settings: Settings) -> str | None:
    """Read the refresh cookie under its *configured* name.

    Not a typed FastAPI `Cookie(...)` parameter: that alias is fixed at import time,
    so it cannot honour an operator's `REFRESH_COOKIE_NAME` override. Reading from
    `request.cookies` at call time can. The trade-off is that the cookie no longer
    appears as a typed parameter in the OpenAPI schema — see each route's summary.
    """
    return request.cookies.get(settings.refresh_cookie_name)


def get_auth_service(
    session: SessionDep,
    settings: SettingsDep,
    attempts: LoginAttemptLimiterDep,
    recorder: AuditRecorderDep,
    client_ip: ClientIpDep,
    user_agent: Annotated[str | None, Header()] = None,
) -> AuthService:
    """Provide the service with a request-scoped session.

    `attempts` is only exercised by `login`, but wiring it here rather than per-route
    keeps every handler down to one service call — see `.claude/rules/router.md`.
    Building a `LoginAttemptLimiter` does no I/O, so the routes that never touch it pay
    nothing for carrying it. The recorder and the client IP arrive the same way and for
    the same reason. The user agent arrives the same way, and only `login` stores it.
    """
    return AuthService(
        session, settings, attempts, recorder=recorder, client_ip=client_ip, user_agent=user_agent
    )


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


def _refresh_cookie_clear_headers(settings: Settings) -> dict[str, str]:
    """The `Set-Cookie` header that clears the refresh cookie, as a plain header dict.

    Needed on the exception path, not just the success path: once `AppError` (an
    `HTTPException`) propagates out of a route, FastAPI's own handler builds a fresh
    `JSONResponse` and never looks at the `response: Response` dependency the route
    was mutating — so clearing the cookie there has no effect on what the client
    receives. Attaching the header to the exception itself is what survives.
    """
    scratch = Response()
    _clear_refresh_cookie(scratch, settings)
    return {"set-cookie": scratch.headers["set-cookie"]}


@router.get(
    "/password-policy",
    response_model=PasswordPolicyResponse,
    status_code=status.HTTP_200_OK,
    summary="The rules a new password must satisfy",
)
async def password_policy(settings: SettingsDep) -> PasswordPolicyResponse:
    """Publish the length bounds so a client can render them instead of guessing.

    Unauthenticated on purpose: the forced-password-change screen needs it while the
    caller is still gated, and the values leak nothing — a single rejected password
    reveals the minimum anyway.
    """
    return PasswordPolicyResponse(
        min_length=settings.password_min_length,
        max_bytes=settings.password_max_bytes,
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
    description=(
        "Reads the refresh token from the cookie named by `REFRESH_COOKIE_NAME` "
        "(not a typed OpenAPI parameter)."
    ),
    responses={401: ERROR_RESPONSES[401]},
)
async def refresh(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> AccessTokenResponse:
    refresh_token = _read_refresh_cookie(request, settings)
    try:
        token_response, raw_refresh = await service.refresh(refresh_token)
    except AppError as error:
        # Replay detection revokes the family server-side, but the browser will keep
        # re-sending a dead cookie forever unless this response also clears it. The
        # header goes on the re-raised error itself, not the `response` dependency —
        # FastAPI's own HTTPException handler builds a fresh JSONResponse once this
        # propagates, so anything mutated on `response` here would be discarded.
        if error.code == ErrorCode.REFRESH_TOKEN_REUSED:
            raise AppError(
                error.status_code,
                error.code,
                error.message,
                headers=_refresh_cookie_clear_headers(settings),
            ) from error
        raise
    _set_refresh_cookie(response, raw_refresh, settings)
    return token_response


@router.post(
    "/change-password",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Change your own password",
    description=(
        "Revokes every other session. The caller's own session — the one its access "
        "token names — stays signed in."
    ),
    dependencies=[Depends(enforce_password_change_ip_limit)],
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 422, 429)},
)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    service: AuthServiceDep,
) -> UserResponse:
    return await service.change_password(current_user.id, payload, current_user.session_id)


def get_password_reset_service(
    session: SessionDep,
    settings: SettingsDep,
    recorder: AuditRecorderDep,
    client_ip: ClientIpDep,
) -> PasswordResetService:
    return PasswordResetService(session, settings, recorder=recorder, client_ip=client_ip)


PasswordResetServiceDep = Annotated[PasswordResetService, Depends(get_password_reset_service)]


@router.get(
    "/password-reset/availability",
    response_model=PasswordResetAvailability,
    summary="Whether self-service password reset is available",
    description="`MAIL_ENABLED`, as a boolean the login screen reads to show its link.",
)
async def password_reset_availability(settings: SettingsDep) -> PasswordResetAvailability:
    return PasswordResetAvailability(enabled=settings.mail_enabled)


@router.post(
    "/password-reset/request",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Email a password-reset link",
    description=(
        "Answers `202` with an empty body for every address — live, unknown or "
        "deactivated — so the route cannot be used to learn which accounts exist. The "
        "email is sent after the response, once, and never retried."
    ),
    dependencies=[Depends(enforce_password_reset_ip_limit)],
    responses={code: ERROR_RESPONSES[code] for code in (409, 422, 429)},
)
async def request_password_reset(
    payload: PasswordResetRequest,
    background: BackgroundTasks,
    service: PasswordResetServiceDep,
    sender: MailSenderDep,
    limiter: RateLimiterDep,
    settings: SettingsDep,
) -> Response:
    if settings.mail_enabled:
        await enforce_password_reset_email_limit(payload.email, limiter, settings)
    pending = await service.request(payload)
    if pending is not None:
        background.add_task(
            deliver_password_reset,
            pending,
            sender=sender,
            settings=settings,
            sessionmaker=get_sessionmaker(),
        )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password with a reset token",
    description=(
        "Every unusable token — unknown, expired, used or revoked — is the same "
        "`400 PASSWORD_RESET_TOKEN_INVALID`. Success ends every session."
    ),
    responses={code: ERROR_RESPONSES[code] for code in (400, 422)},
)
async def confirm_password_reset(
    payload: PasswordResetConfirm, service: PasswordResetServiceDep
) -> None:
    await service.confirm(payload)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out of this device",
    description=(
        "Reads the refresh token from the cookie named by `REFRESH_COOKIE_NAME` "
        "(not a typed OpenAPI parameter)."
    ),
    responses={},
)
async def logout(
    request: Request,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
) -> None:
    refresh_token = _read_refresh_cookie(request, settings)
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
