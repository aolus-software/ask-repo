"""Wire shapes for `/feedback`. All `ApiModel`, so the wire is camelCase."""

import uuid
from datetime import datetime

from pydantic import Field, ValidationInfo, field_validator

from app.core.feedback import (
    NOTE_MAX_LENGTH,
    FeedbackRating,
    FeedbackTarget,
    ReasonCode,
)
from app.schemas.base import ApiModel


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
