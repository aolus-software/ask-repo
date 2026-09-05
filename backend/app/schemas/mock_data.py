"""Mock data request and response bodies, and the one new stream event.

Every model inherits `ApiModel` so `snake_case` attributes ship `camelCase`
(`tests/test_api_model.py`). Mirrors `app/schemas/checklist.py`'s shape for the
checklist's own change-set/apply/chat contract, adapted for a dynamic field-map record
instead of a fixed-shape test case.
"""

import uuid
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.checklist import ChangeSetOrigin, ChangeSetStatus
from app.models.conversation import FinishReason, MessageRole
from app.models.mock_data import MockDataDatasetStatus
from app.schemas.base import ApiModel
from app.schemas.checklist import MAX_PROSE_CHARS
from app.schemas.conversation import CitationPayload, StreamEvent

MIN_GENERATION_COUNT = 1
MAX_GENERATION_COUNT = 50
DEFAULT_GENERATION_COUNT = 10


class MockDataRecordResponse(ApiModel):
    """One generated sample record, as the table renders it."""

    id: uuid.UUID
    checklist_module_id: uuid.UUID
    fields: dict[str, str]
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


class MockDataDatasetResponse(ApiModel):
    """A module's mock-data dataset summary, as the tab's header renders it."""

    id: uuid.UUID
    checklist_module_id: uuid.UUID
    status: MockDataDatasetStatus
    error: str | None
    indexed_generation: int | None
    last_generated_at: datetime | None
    # Same staleness signal `ChecklistModuleResponse.stale` gives the checklist,
    # computed the same way: `indexed_generation` behind the project's current one.
    stale: bool
    record_count: int
    pending_change_set_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class MockDataDatasetDetailResponse(MockDataDatasetResponse):
    """A dataset with its records, in table order."""

    records: list[MockDataRecordResponse]


class MockDataGenerationRequest(ApiModel):
    """How many sample records to generate. Empty body means the default."""

    count: int = Field(
        default=DEFAULT_GENERATION_COUNT, ge=MIN_GENERATION_COUNT, le=MAX_GENERATION_COUNT
    )


class MockDataChangeOperationPayload(ApiModel):
    """One proposed operation against a module's mock data records.

    Simpler than the checklist's `ChangeOperationPayload`: a record has no fixed field
    set, so `add` carries the full field map and `update` carries only the changed
    keys, rather than a handful of named columns.
    """

    op: Literal["add", "update", "remove"]
    id: uuid.UUID
    rationale: str
    # Present on `update`/`remove`; absent on `add`.
    record_id: uuid.UUID | None = None
    # The full field map, for `add`.
    fields: dict[str, str] | None = None
    # Field name to new value, for `update`.
    changes: dict[str, str] | None = None


class MockDataChangeSetResponse(ApiModel):
    """A mock-data change set awaiting, or past, a human decision."""

    id: uuid.UUID
    checklist_module_id: uuid.UUID
    origin: ChangeSetOrigin
    message_id: uuid.UUID | None
    summary: str
    operations: list[MockDataChangeOperationPayload]
    status: ChangeSetStatus
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    created_by: uuid.UUID
    created_at: datetime


class MockDataChangeSetApplyRequest(ApiModel):
    """Which operations to apply. Omitted or null means all of them.

    Ids only, never content -- same reasoning as `ChangeSetApplyRequest`: a mock
    dataset is published to every user on the instance, so its rows must come from the
    server, never from whoever's tab happened to be open.
    """

    operation_ids: list[uuid.UUID] | None = None


class MockDataChangeSetApplyResponse(ApiModel):
    """What the apply did."""

    change_set: MockDataChangeSetResponse
    records: list[MockDataRecordResponse]
    skipped_operation_ids: list[uuid.UUID]


class MockDataMessageCreateRequest(ApiModel):
    """One refinement turn."""

    question: str = Field(min_length=1, max_length=MAX_PROSE_CHARS)


class MockDataMessageResponse(ApiModel):
    """One stored mock-data chat turn. Readable by every authenticated user."""

    id: uuid.UUID
    checklist_module_id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[CitationPayload] | None
    model: str | None
    finish_reason: FinishReason | None
    created_by: uuid.UUID
    created_at: datetime


class MockDataChangeSetEvent(StreamEvent):
    """The turn proposed mock-data changes. At most once, after the last token.

    Same contract as `ChangeSetEvent` (`.claude/rules/rag.md`): not a terminator, absent
    when the turn proposed nothing, and `change_set_id` is minted before the stream
    opens because the row itself is written under the shield in `finally`.
    """

    event_name: ClassVar[str] = "mockDataChangeSet"
    change_set_id: uuid.UUID
    summary: str
    operations: list[MockDataChangeOperationPayload]
