"""Wire shapes for `/feedback`. All `ApiModel`, so the wire is camelCase."""

import uuid
from datetime import date, datetime

from pydantic import Field, ValidationInfo, field_validator

from app.core.feedback import (
    NOTE_MAX_LENGTH,
    FeedbackFeature,
    FeedbackRating,
    FeedbackTarget,
    ReasonCode,
)
from app.schemas.base import ApiModel
from app.schemas.pagination import ListQuery


class FeedbackWrite(ApiModel):
    """The caller's vote. `feature` and `projectId` are derived, never accepted."""

    rating: FeedbackRating
    reason_codes: list[ReasonCode] = Field(default_factory=list, validate_default=True)
    note: str | None = Field(default=None, max_length=NOTE_MAX_LENGTH)

    @field_validator("reason_codes")
    @classmethod
    def _down_needs_a_reason(
        cls, value: list[ReasonCode], info: ValidationInfo
    ) -> list[ReasonCode]:
        if info.data.get("rating") is FeedbackRating.DOWN and not value:
            raise ValueError("A thumbs-down needs at least one reason.")
        return value


class MyFeedback(ApiModel):
    """The caller's own vote, embedded on the lists that show the judged output."""

    rating: FeedbackRating
    reason_codes: list[ReasonCode]
    note: str | None


class FeedbackRead(MyFeedback):
    target_type: FeedbackTarget
    target_id: uuid.UUID
    updated_at: datetime


class FeedbackFilterFields(ApiModel):
    """The admin filters. On a model, never beside one: a query model stops flattening
    the moment a scalar query parameter joins it (`.claude/rules/rag.md`)."""

    project_id: uuid.UUID | None = None
    feature: FeedbackFeature | None = None
    rating: FeedbackRating | None = None
    reason_code: ReasonCode | None = None
    prompt_version: str | None = Field(default=None, max_length=16)
    created_from: datetime | None = None
    created_to: datetime | None = None


class FeedbackListQuery(ListQuery, FeedbackFilterFields):
    """`ListQuery` plus the filters. `created_at` descending is the only order."""


class FeedbackSummaryQuery(FeedbackFilterFields):
    """The same filters, no pagination."""


class FeedbackAdminRead(ApiModel):
    """One vote as an administrator sees it. **No user field of any kind** — a note
    with a name attached is most of the way to reading a private conversation.

    Carries the vote's **day only**, never a time. `conversation.created` in the
    audit trail (`.claude/rules/audit-trail.md`) records a second-precision
    timestamp for the same actor and project, so a second-precision `created_at`
    here would let an admin match an `answer` vote to whoever opened that
    conversation seconds earlier. `updated_at` is dropped entirely for the same
    reason — a revision time is exactly as identifying as a creation time. This is
    an accepted, narrower leak than it prevents: on a one-member project the voter
    is identifiable regardless, day-only or not.
    """

    id: uuid.UUID
    project_id: uuid.UUID
    project_name: str
    target_type: FeedbackTarget
    feature: FeedbackFeature
    rating: FeedbackRating
    reason_codes: list[ReasonCode]
    note: str | None
    prompt_version: str
    created_on: date
    # Stage 2 (Langfuse) fills this; until then, and whenever Langfuse is off, null.
    trace_url: str | None = None


class FeatureVotes(ApiModel):
    feature: FeedbackFeature
    up: int
    down: int


class ReasonCount(ApiModel):
    feature: FeedbackFeature
    reason_code: ReasonCode
    count: int


class PromptVersionVotes(ApiModel):
    prompt_version: str
    up: int
    down: int


class FeedbackSummary(ApiModel):
    by_feature: list[FeatureVotes]
    by_reason: list[ReasonCount]
    by_prompt_version: list[PromptVersionVotes]
