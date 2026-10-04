"""Eval set request and response schemas. Every one is an `ApiModel`: camelCase on the wire."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.models.eval import EvalMix, EvalQuestionType, EvalRunStatus, EvalSetStatus
from app.schemas.base import ApiModel

NAME_MAX_LENGTH = 120


class EvalSetCreate(ApiModel):
    """Ask for a set of generated question/answer pairs.

    `count` is a literal rather than a range: three sizes are what the cost estimate
    and the one-job-at-a-time cap were reasoned about.
    """

    name: str = Field(min_length=1, max_length=NAME_MAX_LENGTH)
    source_path: str | None = Field(default=None, max_length=1024)
    count: Literal[10, 25, 50]
    mix: EvalMix


class EvalRunSummary(ApiModel):
    """One run's stamp and tally. Carries no question, answer or reference text."""

    id: uuid.UUID
    set_id: uuid.UUID
    status: EvalRunStatus
    error: str | None
    prompt_version: str | None
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
    status: EvalSetStatus
    error: str | None
    pair_count: int
    indexed_generation: int | None
    created_at: datetime
    latest_run: EvalRunSummary | None = None


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


class EvalSetDetail(EvalSetSummary):
    """A set with every pair, and the project's current generation so the screen can
    say the set was written against an older index."""

    pairs: list[EvalPairRead]
    project_generation: int


class EvalPairExclude(ApiModel):
    """Take a pair out of (or put it back into) future runs."""

    excluded: bool
