"""Conversation bodies, and the Server-Sent Events contract.

Both live here on purpose. The SSE payloads are as much a wire contract as any
response model, but they never pass through FastAPI's `response_model`, so nothing
in the framework enforces `ApiModel` on them. Putting them beside the ordinary
schemas — and enumerating them in `SSE_EVENT_MODELS` — is what lets
`tests/test_api_model.py` hold them to the same rule.
"""

import uuid
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.core.errors import ErrorCode
from app.models.conversation import FinishReason, MessageRole
from app.schemas.base import ApiModel
from app.schemas.pagination import ListQuery

# Sent during any gap. Caddy sits in front of the API (docs/PRD.md §5), and an idle
# SSE connection is exactly what a reverse proxy reaps.
KEEP_ALIVE = b": keep-alive\n\n"


class CitationPayload(ApiModel):
    """One retrieved span, as the API presents it.

    `cited` is `None` in the `citations` **event**, which is emitted before
    generation and so cannot know what the model will use, and `True`/`False` on the
    **stored** message, which is written afterwards.
    """

    index: int
    file_path: str
    start_line: int
    end_line: int
    language: str
    symbol: str | None
    commit_sha: str
    score: float
    cited: bool | None = None


class ConversationListQuery(ListQuery):
    """`ListQuery` plus the project filter.

    A field on the model rather than a sibling `Query(...)` parameter, and that is
    load-bearing: FastAPI flattens a Pydantic model used as `Annotated[Model,
    Query()]` into individual query parameters only while it is the **sole** query
    parameter of the route. Put a scalar beside it and the flattening stops — the
    model starts demanding a literal `?query=` — and every request to the route
    fails validation with `{"request": "Field required"}`, which names nothing that
    appears in the signature.

    `ApiModel` supplies the `projectId` alias, so nothing has to spell it out.
    """

    project_id: uuid.UUID | None = None


class ConversationCreateRequest(ApiModel):
    """Open a conversation against a project."""

    project_id: uuid.UUID


class MessageCreateRequest(ApiModel):
    """Ask one question."""

    question: str = Field(min_length=1, max_length=4000)


class ConversationResponse(ApiModel):
    """A conversation as the API presents it."""

    id: uuid.UUID
    project_id: uuid.UUID
    title: str | None
    created_at: datetime
    updated_at: datetime


class MessageResponse(ApiModel):
    """One stored turn."""

    id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[CitationPayload] | None
    model: str | None
    finish_reason: FinishReason | None
    created_at: datetime


class ConversationDetailResponse(ConversationResponse):
    """A conversation with its messages, oldest first."""

    messages: list[MessageResponse]


class StreamEvent(ApiModel):
    """Base for everything the answer stream emits.

    `event_name` is a `ClassVar`, so it names the SSE event without becoming a field
    that would then be duplicated inside every payload.
    """

    event_name: ClassVar[str]


class StatusEvent(StreamEvent):
    """Where the turn has got to. May be emitted any number of times, including none."""

    event_name: ClassVar[str] = "status"
    phase: Literal["queued", "rewriting", "retrieving", "generating"]


class CitationsEvent(StreamEvent):
    """The retrieved spans. Emitted exactly once, before the first token.

    Before, deliberately: a client renders its sources panel while the answer types,
    and a stream that breaks mid-answer has still delivered the citations for the
    partial it kept.
    """

    event_name: ClassVar[str] = "citations"
    citations: list[CitationPayload]


class TokenEvent(StreamEvent):
    """One fragment of the answer."""

    event_name: ClassVar[str] = "token"
    text: str


class DoneEvent(StreamEvent):
    """The answer completed."""

    event_name: ClassVar[str] = "done"
    message_id: uuid.UUID
    model: str
    finish_reason: FinishReason
    cited_indexes: list[int]
    # Machine-readable signals that the answer may not be grounded — see
    # `app/rag/grounding.py`. Empty is the normal case. Surfaced rather than
    # swallowed: a check whose result nothing can see is not a check.
    grounding_warnings: list[str] = Field(default_factory=list)


class ErrorEvent(StreamEvent):
    """The answer did not complete.

    Carries `finish_reason` for the same reason `DoneEvent` does: the service reads
    it off whichever terminator it saw in order to decide what to persist, and a
    client needs to tell "retry might work" (timeout) from "something broke".
    """

    event_name: ClassVar[str] = "error"
    message_id: uuid.UUID
    code: ErrorCode
    message: str
    finish_reason: FinishReason


SSE_EVENT_MODELS: tuple[type[StreamEvent], ...] = (
    StatusEvent,
    CitationsEvent,
    TokenEvent,
    DoneEvent,
    ErrorEvent,
)
"""Every event the stream can emit. `tests/test_api_model.py` walks this, which is
the only thing holding these payloads to the camelCase rule — a new event added to
the stream but not to this tuple ships unchecked."""


def encode_event(event: StreamEvent) -> bytes:
    """Frame one event as an SSE message."""
    return (f"event: {event.event_name}\ndata: {event.model_dump_json(by_alias=True)}\n\n").encode()
