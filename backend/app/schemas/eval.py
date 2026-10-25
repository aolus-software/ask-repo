"""Eval set request and response schemas. Every one is an `ApiModel`: camelCase on the wire."""

import uuid
from datetime import datetime
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from app.core.language import Language, language_or_default
from app.models.checklist import MAX_SOURCE_PATH_CHARS
from app.models.eval import (
    EvalExclusionReason,
    EvalMix,
    EvalQuestionType,
    EvalRunStatus,
    EvalSetStatus,
    EvalVerdict,
)
from app.schemas.base import ApiModel
from app.schemas.fields import ResourceName


class EvalSetCreate(ApiModel):
    """Ask for a set: generated natively in English, or translated from an English set.

    Generation sends `name`, `count`, `mix` and optionally `sourcePath`; translation sends
    `sourceSetId` and `language` and nothing else (spec §3.3). One model rather than a
    union: a union prefixes every `422` field key with the member's class name, which
    breaks the `fields`/`fieldTypes` keying the frontend translates by.

    `count` is a literal rather than a range: three sizes are what the cost estimate
    and the one-job-at-a-time cap were reasoned about.
    """

    name: ResourceName | None = None
    source_path: str | None = Field(default=None, max_length=MAX_SOURCE_PATH_CHARS)
    count: Literal[10, 25, 50] | None = None
    mix: EvalMix | None = None
    source_set_id: uuid.UUID | None = None
    language: Language | None = None

    @model_validator(mode="after")
    def _exactly_one_shape(self) -> Self:
        generation = (self.name, self.source_path, self.count, self.mix)
        if self.source_set_id is None:
            if self.language is not None:
                raise ValueError("language is only sent with sourceSetId")
            if self.name is None or self.count is None or self.mix is None:
                raise ValueError("name, count and mix are required")
            return self
        if any(value is not None for value in generation):
            raise ValueError("a translation sends only sourceSetId and language")
        if self.language is None:
            raise ValueError("language is required with sourceSetId")
        if self.language is Language.EN:
            raise ValueError("a translation's language must not be en")
        return self

    @property
    def is_translation(self) -> bool:
        """Whether this body asks for a translation rather than a generation."""
        return self.source_set_id is not None


class EvalRunSummary(ApiModel):
    """One run's stamp and tally. Carries no question, answer or reference text."""

    id: uuid.UUID
    set_id: uuid.UUID
    status: EvalRunStatus
    error: str | None
    prompt_version: str | None
    judge_prompt_version: str | None
    chat_provider: str | None
    chat_model: str | None
    judge_model: str | None
    embedding_model: str | None
    project_generation: int | None
    pairs_answered: int
    hits: int
    correct: int
    partial: int
    wrong: int
    errors: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class EvalSetSummary(ApiModel):
    """A set without its pairs, with its newest run."""

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    source_path: str | None
    requested_count: int
    mix: EvalMix
    language: Language
    source_set_id: uuid.UUID | None
    status: EvalSetStatus
    error: str | None
    pair_count: int
    indexed_generation: int | None
    created_at: datetime
    latest_run: EvalRunSummary | None = None

    @field_validator("language", mode="before")
    @classmethod
    def _unshipped_language_reads_as_english(cls, value: object) -> object:
        """A stored tag a later release no longer ships reads as English, not a 500."""
        if isinstance(value, str):
            return language_or_default(value)
        return value


class EvalPairRead(ApiModel):
    """One generated pair. `excluded` is derived from `excluded_at`."""

    id: uuid.UUID
    position: int
    question_type: EvalQuestionType
    question: str
    reference_answer: str
    source_file: str
    start_line: int
    end_line: int
    excluded: bool
    source_pair_id: uuid.UUID | None
    exclusion_reason: EvalExclusionReason | None


class EvalSetDetail(EvalSetSummary):
    """A set with every pair, and the project's current generation so the screen can
    say the set was written against an older index."""

    pairs: list[EvalPairRead]
    project_generation: int


class EvalPairExclude(ApiModel):
    """Take a pair out of (or put it back into) future runs."""

    excluded: bool


class EvalResultRead(ApiModel):
    """One pair's outcome in a run. The answer and judge reason are model output about a
    private repository: members read them here and nowhere else."""

    id: uuid.UUID
    pair_id: uuid.UUID
    retrieval_hit: bool
    verdict: EvalVerdict
    judge_reason: str | None
    answer: str
    grounding_warnings: list[str]
    retrieval_attempts: int


class EvalRunDetail(EvalRunSummary):
    """A run with every result it has recorded so far."""

    results: list[EvalResultRead]
