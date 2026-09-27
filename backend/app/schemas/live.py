"""The `/events` stream's payloads. Each is in `SSE_EVENT_MODELS`, the only enforcement an
SSE payload gets (`tests/test_api_model.py`)."""

import uuid
from typing import ClassVar

from app.live.kinds import LiveKind
from app.schemas.conversation import StreamEvent


class ReadyEvent(StreamEvent):
    """The stream is open. The client refetches everything live."""

    event_name: ClassVar[str] = "ready"


class InvalidateEvent(StreamEvent):
    """This row changed; refetch its queries. Ids only — never content."""

    event_name: ClassVar[str] = "invalidate"
    kind: LiveKind
    id: uuid.UUID
    project_id: uuid.UUID | None


class ResyncEvent(StreamEvent):
    """Events were dropped for this connection; refetch everything live."""

    event_name: ClassVar[str] = "resync"
