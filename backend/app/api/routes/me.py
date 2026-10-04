"""The caller's own account surface.

Deliberately **not** under `/auth`: that prefix is exempt from the forced-password-change
gate, and nothing here should be readable before a temporary password is replaced. No
route takes a user id — there is no `/me/{id}`, and an administrator's view of other
people stays on `/users`.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AuditRecorderDep, ClientIpDep, CurrentUser, SessionDep
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.me import (
    ActivityEntry,
    AnswerStyleRead,
    AnswerStyleUpdate,
    MembershipSummary,
    SessionResponse,
)
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.services.me import MeService

router = APIRouter(prefix="/me", tags=["Me"])


def get_me_service(
    session: SessionDep, recorder: AuditRecorderDep, client_ip: ClientIpDep
) -> MeService:
    """Provide the service with a request-scoped session, the recorder and the caller's
    address — only `revoke_session` uses the last two."""
    return MeService(session, recorder=recorder, client_ip=client_ip)


MeServiceDep = Annotated[MeService, Depends(get_me_service)]


@router.get(
    "/memberships",
    response_model=list[MembershipSummary],
    status_code=status.HTTP_200_OK,
    summary="The projects you are a member of",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_memberships(
    current_user: CurrentUser, service: MeServiceDep
) -> list[MembershipSummary]:
    return await service.memberships(current_user)


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    status_code=status.HTTP_200_OK,
    summary="Your signed-in sessions",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_sessions(current_user: CurrentUser, service: MeServiceDep) -> list[SessionResponse]:
    return await service.sessions(current_user)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Sign one of your sessions out",
    description=(
        "Its refresh token stops working at once; an access token it already holds "
        "keeps working until it expires, at most the access-token lifetime."
    ),
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def revoke_session(
    session_id: uuid.UUID, current_user: CurrentUser, service: MeServiceDep
) -> None:
    await service.revoke_session(current_user, session_id)


@router.get(
    "/activity",
    response_model=PaginatedResponse[ActivityEntry],
    status_code=status.HTTP_200_OK,
    summary="What you have done, from the audit trail",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 422)},
)
async def list_activity(
    current_user: CurrentUser,
    service: MeServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[ActivityEntry]:
    return await service.activity(current_user, query)


@router.get(
    "/answer-style",
    response_model=AnswerStyleRead,
    status_code=status.HTTP_200_OK,
    summary="How your Ask answers are shaped",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def get_answer_style(current_user: CurrentUser, service: MeServiceDep) -> AnswerStyleRead:
    return await service.answer_style(current_user)


@router.put(
    "/answer-style",
    response_model=AnswerStyleRead,
    status_code=status.HTTP_200_OK,
    summary="Set how your Ask answers are shaped",
    description=(
        "Replaces all three dials; `null` is no preference. Applies to your own Ask "
        "answers only — never to the QA Checklist or Mock Data, which a project shares."
    ),
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 422)},
)
async def update_answer_style(
    payload: AnswerStyleUpdate, current_user: CurrentUser, service: MeServiceDep
) -> AnswerStyleRead:
    return await service.update_answer_style(current_user, payload)
