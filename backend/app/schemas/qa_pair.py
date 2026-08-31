"""QA pair request and response bodies.

Every model here inherits `ApiModel`, so `snake_case` attributes ship as `camelCase`
keys (`docs/PRD.md` §5.1). A schema on plain `BaseModel` would silently ship
`snake_case`; `tests/test_api_model.py` is what catches that.
"""

import uuid
from datetime import datetime

from pydantic import Field

from app.models.qa_pair import MAX_MODULE_CHARS, QASource, QAStatus
from app.schemas.base import ApiModel
from app.schemas.conversation import CitationPayload
from app.schemas.pagination import ListQuery

MAX_TAGS = 10
MAX_TAG_CHARS = 40


class QAPairListQuery(ListQuery):
    """`ListQuery` plus every QA filter.

    Fields on the model rather than sibling `Query(...)` parameters, and that is
    load-bearing rather than stylistic — see `ConversationListQuery` for the same
    note, and `.claude/rules/rag.md` for the failure it prevents.
    """

    project_id: uuid.UUID | None = None
    module: str | None = None
    tag: str | None = None
    source: QASource | None = None
    status: QAStatus | None = None
    created_by: uuid.UUID | None = None


class QAPairCreateRequest(ApiModel):
    """Publish an answer to the QA List.

    A message id, never the answer text. The server copies the content out of the
    rows, which is the only place `finish_reason` can be checked — a truncated
    answer and a short one are the same string in a request body (spec §2.6).
    """

    message_id: uuid.UUID
    module: str | None = Field(default=None, max_length=MAX_MODULE_CHARS)
    tags: list[str] = Field(default_factory=list, max_length=MAX_TAGS)


class QAPairUpdateRequest(ApiModel):
    """Edit a pair. `answer` is absent on purpose: it only ever comes from a model."""

    module: str | None = Field(default=None, max_length=MAX_MODULE_CHARS)
    question: str | None = Field(default=None, min_length=1, max_length=4000)
    reference_answer: str | None = None
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)


class QAPairStatusRequest(ApiModel):
    """Set the verdict. Open to every authenticated user (`docs/PRD.md:338`)."""

    status: QAStatus


class PendingRunPayload(ApiModel):
    """A re-run waiting for a human decision.

    `finish_reason` is here so the client can disable Save for a run that never
    finished, mirroring the `409` the accept route would return.
    """

    answer: str
    citations: list[CitationPayload] | None
    model: str | None
    finish_reason: str
    run_at: datetime


class QAPairResponse(ApiModel):
    """A pair as the list presents it. No prose beyond what a row shows."""

    id: uuid.UUID
    project_id: uuid.UUID
    created_by: uuid.UUID
    module: str | None
    question: str
    answer: str | None
    reference_answer: str | None
    tags: list[str]
    source: QASource
    status: QAStatus
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    model: str | None
    eval_score: float | None
    last_run_at: datetime | None
    # A flag rather than the run itself: the list renders a badge, and shipping
    # every pending answer in a page of 25 would multiply the payload for nothing.
    has_pending_run: bool
    created_at: datetime
    updated_at: datetime


class QAPairDetailResponse(QAPairResponse):
    """A pair with its citations and its pending run, for the detail page."""

    citations: list[CitationPayload] | None
    pending_run: PendingRunPayload | None
