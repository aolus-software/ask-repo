"""Checklist request and response bodies, and the one new stream event.

Every model here inherits `ApiModel`, so `snake_case` attributes ship as `camelCase`
keys. A schema on plain `BaseModel` silently ships `snake_case`; `tests/test_api_model.py`
is what catches that -- and for `ChangeSetEvent` it is the *only* thing that does,
because SSE payloads never pass through a `response_model` (spec 5.2).
"""

import uuid
from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.models.checklist import (
    MAX_MODULE_NAME_CHARS,
    MAX_SOURCE_PATH_CHARS,
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistItemKind,
    ChecklistItemSource,
    ChecklistItemStatus,
    ChecklistModuleStatus,
)
from app.models.conversation import FinishReason, MessageRole
from app.schemas.base import ApiModel
from app.schemas.conversation import CitationPayload, StreamEvent
from app.schemas.pagination import ListQuery

MAX_TEST_NAME_CHARS = 500
MAX_PROSE_CHARS = 4000


class ChecklistModuleListQuery(ListQuery):
    """`ListQuery` plus the module filters.

    Fields on the model rather than sibling `Query(...)` parameters, and that is
    load-bearing rather than stylistic -- see `ConversationListQuery`.
    """

    project_id: uuid.UUID | None = None
    status: ChecklistModuleStatus | None = None


class ChecklistItemListQuery(ListQuery):
    """`ListQuery` plus every grid filter. Same rule as above (spec 6.2)."""

    project_id: uuid.UUID | None = None
    module_id: uuid.UUID | None = None
    feature: str | None = None
    status: ChecklistItemStatus | None = None
    source: ChecklistItemSource | None = None
    kind: ChecklistItemKind | None = None


class ChecklistModuleCreateRequest(ApiModel):
    """Name a module and point it at a path in the indexed repository."""

    project_id: uuid.UUID
    name: str = Field(min_length=1, max_length=MAX_MODULE_NAME_CHARS)
    source_path: str = Field(min_length=1, max_length=MAX_SOURCE_PATH_CHARS)


class ChecklistModuleUpdateRequest(ApiModel):
    """Rename a module or re-point it. `status` is absent: it is the server's."""

    name: str | None = Field(default=None, min_length=1, max_length=MAX_MODULE_NAME_CHARS)
    source_path: str | None = Field(default=None, min_length=1, max_length=MAX_SOURCE_PATH_CHARS)


class ChecklistModuleResponse(ApiModel):
    """A module as the list presents it, with the counts a row renders."""

    id: uuid.UUID
    project_id: uuid.UUID
    # Denormalised onto the row so the list can render the project column without
    # the browser resolving twenty-five ids against `/projects`.
    project_name: str
    created_by: uuid.UUID
    name: str
    source_path: str
    status: ChecklistModuleStatus
    error: str | None
    indexed_generation: int | None
    last_generated_at: datetime | None
    item_count: int
    pass_count: int
    fail_count: int
    blocked_count: int
    untested_count: int
    # `indexed_generation` is behind the project's: the repository was reindexed since
    # this checklist was built. Surfaced as a prompt to regenerate; nothing enforces
    # it (spec 3.1).
    stale: bool
    # An id rather than the set itself: the list renders a badge, and shipping every
    # pending change set in a page of 25 would multiply the payload for nothing.
    pending_change_set_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ChecklistItemResponse(ApiModel):
    """One test case as the grid and the detail both present it."""

    id: uuid.UUID
    module_id: uuid.UUID
    project_id: uuid.UUID
    feature: str
    test_name: str
    expected_result: str
    current_result: str | None
    status: ChecklistItemStatus
    notes: str | None
    citations: list[CitationPayload] | None
    source: ChecklistItemSource
    kind: ChecklistItemKind
    position: int
    created_by: uuid.UUID
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ChecklistModuleDetailResponse(ChecklistModuleResponse):
    """A module with its items, in grid order."""

    items: list[ChecklistItemResponse]


class ChecklistItemCreateRequest(ApiModel):
    """Add a test case by hand. `source` is set to `manual` by the server."""

    module_id: uuid.UUID
    feature: str = Field(min_length=1, max_length=MAX_MODULE_NAME_CHARS)
    test_name: str = Field(min_length=1, max_length=MAX_TEST_NAME_CHARS)
    expected_result: str = Field(min_length=1, max_length=MAX_PROSE_CHARS)
    kind: ChecklistItemKind = ChecklistItemKind.POSITIVE
    notes: str | None = Field(default=None, max_length=MAX_PROSE_CHARS)


class ChecklistItemUpdateRequest(ApiModel):
    """Edit what a test expects. Gated on `created_by`/`is_admin` (spec 2.5).

    `current_result` and `status` are absent on purpose: they are the ungated write,
    and putting them here would let the gate on this route be bypassed by whoever
    could reach the other one.
    """

    feature: str | None = Field(default=None, min_length=1, max_length=MAX_MODULE_NAME_CHARS)
    test_name: str | None = Field(default=None, min_length=1, max_length=MAX_TEST_NAME_CHARS)
    expected_result: str | None = Field(default=None, min_length=1, max_length=MAX_PROSE_CHARS)
    kind: ChecklistItemKind | None = None
    notes: str | None = Field(default=None, max_length=MAX_PROSE_CHARS)


class ChecklistItemResultRequest(ApiModel):
    """Record what a tester observed. Open to every authenticated user.

    Both fields together, replacing the whole result -- which is why the route is
    `PUT` and not `PATCH`. A tester who did not author the checklist must be able to
    record what they saw without being able to rewrite what was expected; otherwise
    the cheapest way to make a failing test pass is to edit the expectation (spec 2.5).
    """

    current_result: str | None = Field(default=None, max_length=MAX_PROSE_CHARS)
    status: ChecklistItemStatus


class ChangeOperationPayload(ApiModel):
    """One proposed operation, as the diff UI receives it.

    Three shapes in one model, discriminated by `op`, rather than a tagged union: the
    union would buy stricter validation of data the *server* wrote and the client only
    reads, at the cost of a discriminator every consumer has to narrow. `item_id` is
    present on `update` and `remove`; the three content fields on `add`.

    `rationale` is carried so the diff can say why without the user having to read back
    through the chat (spec 3.3).
    """

    op: Literal["add", "update", "remove"]
    id: uuid.UUID
    rationale: str
    item_id: uuid.UUID | None = None
    feature: str | None = None
    test_name: str | None = None
    expected_result: str | None = None
    # Present on `add`; an `update` moves it through `changes` like any other field.
    kind: ChecklistItemKind | None = None
    citations: list[CitationPayload] | None = None
    # Field name to new value, for `update`. The keys are the camelCase field names
    # the client already knows from `ChecklistItemResponse`.
    changes: dict[str, str] | None = None


class ChecklistChangeSetResponse(ApiModel):
    """A change set awaiting, or past, a human decision."""

    id: uuid.UUID
    module_id: uuid.UUID
    origin: ChangeSetOrigin
    message_id: uuid.UUID | None
    summary: str
    operations: list[ChangeOperationPayload]
    status: ChangeSetStatus
    resolved_by: uuid.UUID | None
    resolved_at: datetime | None
    created_by: uuid.UUID
    created_at: datetime


class ChangeSetApplyRequest(ApiModel):
    """Which operations to apply. Omitted or null means all of them.

    Ids only, never content: the model's proposals reach Postgres from the server, and
    a checklist is published to every user on the instance, so its rows must not come
    from whoever's tab happened to be open (spec 2.7).
    """

    operation_ids: list[uuid.UUID] | None = None


class ChangeSetApplyResponse(ApiModel):
    """What the apply did.

    `skipped_operation_ids` names operations whose target item no longer exists. Those
    are skipped rather than failed: the item was deleted between proposal and apply, and
    failing the whole change set for that would let one stale row block three good ones
    (spec 3.3).
    """

    change_set: ChecklistChangeSetResponse
    items: list[ChecklistItemResponse]
    skipped_operation_ids: list[uuid.UUID]


class ChecklistMessageCreateRequest(ApiModel):
    """One refinement turn."""

    question: str = Field(min_length=1, max_length=MAX_PROSE_CHARS)


class ChecklistMessageResponse(ApiModel):
    """One stored chat turn. Readable by every authenticated user (spec 2.4)."""

    id: uuid.UUID
    module_id: uuid.UUID
    role: MessageRole
    content: str
    citations: list[CitationPayload] | None
    model: str | None
    finish_reason: FinishReason | None
    created_by: uuid.UUID
    created_at: datetime


class ChangeSetEvent(StreamEvent):
    """The turn proposed changes. At most once, after the last token.

    Absent when the turn proposed nothing -- "why does this test expect 410?" is a
    legitimate turn that changes nothing. Not a terminator: the terminator is built
    only by `Answerer._terminate`, which is what makes "exactly one per stream"
    structural rather than a rule six nodes must remember.

    `change_set_id` is minted before the stream opens and carried through the turn
    context, because the row itself is written under the shield in `finally` -- so the
    id cannot come from the insert.
    """

    event_name: ClassVar[str] = "changeSet"
    change_set_id: uuid.UUID
    summary: str
    operations: list[ChangeOperationPayload]
