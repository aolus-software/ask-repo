"""The audit trail's two admin-only reads.

Reads only, and a test asserts it: `app.routes` serving no method but `GET` under
this prefix is how append-only shows up on the wire, not only in the schema. Do not
add a `POST`, `PATCH`, `PUT`, `DELETE` or export route here — see
`.claude/rules/audit-trail.md` ("the router is reads only").
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AdminUser, SessionDep
from app.schemas.audit import AuditEventListQuery, AuditEventResponse, AuditEventSummary
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import PaginatedResponse
from app.services.audit import AuditService

router = APIRouter(prefix="/audit-events", tags=["Audit"])


def get_audit_service(session: SessionDep) -> AuditService:
    """Provide the service with a request-scoped session."""
    return AuditService(session)


AuditServiceDep = Annotated[AuditService, Depends(get_audit_service)]


@router.get(
    "",
    response_model=PaginatedResponse[AuditEventSummary],
    status_code=status.HTTP_200_OK,
    summary="List audit events",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def list_audit_events(
    current_user: AdminUser,
    service: AuditServiceDep,
    query: Annotated[AuditEventListQuery, Query()],
) -> PaginatedResponse[AuditEventSummary]:
    return await service.list(query)


@router.get(
    "/{event_id}",
    response_model=AuditEventResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one audit event",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def get_audit_event(
    event_id: uuid.UUID, current_user: AdminUser, service: AuditServiceDep
) -> AuditEventResponse:
    return await service.get(event_id)
