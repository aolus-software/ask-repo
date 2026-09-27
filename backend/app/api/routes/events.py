"""`GET /events` — the per-user live-update stream (issue #48).

Behind the forced-password-change gate like every route outside `/auth`. Everything that
needs a status code is decided before the first byte (`.claude/rules/rag.md`'s pre-flight
split); after that the status is fixed at 200.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser
from app.api.routes.conversations import SSE_HEADERS
from app.config import Settings, get_settings
from app.core.errors import AppError, ErrorCode
from app.db.session import get_sessionmaker
from app.live.bus import LiveEventHub
from app.live.stream import live_event_stream
from app.schemas.errors import ERROR_RESPONSES

router = APIRouter(prefix="/events", tags=["Live events"])


def get_live_hub(request: Request) -> LiveEventHub:
    """The process's hub, set by the lifespan."""
    hub: LiveEventHub = request.app.state.live_hub
    return hub


LiveHubDep = Annotated[LiveEventHub, Depends(get_live_hub)]


@router.get(
    "",
    response_class=StreamingResponse,
    status_code=status.HTTP_200_OK,
    summary="Stream live-update signals for the caller",
    description=(
        "Server-sent events: `ready`, then `invalidate` ({kind, id, projectId}) for each "
        "visible change, and `resync` when events were dropped. Ids only — refetch through "
        "the REST routes. 503 means poll instead."
    ),
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 503)},
)
async def stream_events(
    current_user: CurrentUser,
    hub: LiveHubDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    if not settings.live_events_enabled or not hub.available:
        raise AppError(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            ErrorCode.LIVE_EVENTS_UNAVAILABLE,
            "Live updates are unavailable; poll instead.",
        )
    return StreamingResponse(
        live_event_stream(
            user=current_user,
            hub=hub,
            sessionmaker=get_sessionmaker(),
            heartbeat_seconds=settings.live_events_heartbeat_seconds,
            max_seconds=settings.live_events_max_stream_minutes * 60,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
