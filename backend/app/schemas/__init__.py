"""Request and response schemas.

`SSE_EVENT_MODELS` lives here rather than beside the events in
`app.schemas.conversation` for one reason: `ChangeSetEvent` is a checklist type and
`app.schemas.checklist` already imports `StreamEvent` and `CitationPayload` from
`conversation`. Enumerating the tuple in either module would close an import cycle that
fails whichever module is imported second. This package is imported by nothing, so it can
see both.

The tuple stays an explicit, hand-maintained enumeration. That is the property
`.claude/rules/rag.md` depends on: SSE payloads never pass through a `response_model`, so
`tests/test_api_model.py` walking this tuple is the only thing holding them to the
camelCase rule, and an event added to the stream but not to this tuple ships unchecked.
"""

from app.schemas.checklist import ChangeSetEvent
from app.schemas.conversation import (
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    StatusEvent,
    StreamEvent,
    TokenEvent,
)
from app.schemas.mock_data import MockDataChangeSetEvent

SSE_EVENT_MODELS: tuple[type[StreamEvent], ...] = (
    StatusEvent,
    CitationsEvent,
    TokenEvent,
    DoneEvent,
    ErrorEvent,
    ChangeSetEvent,
    MockDataChangeSetEvent,
)

__all__ = ["SSE_EVENT_MODELS"]
