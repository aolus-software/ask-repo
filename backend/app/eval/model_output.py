"""What the eval generator and judge return, as structured output."""

from typing import Literal

from pydantic import BaseModel, Field


class GeneratedPair(BaseModel):
    """One question and the answer the excerpt supports."""

    question: str = Field(default="", description="the question a developer would ask")
    reference_answer: str = Field(
        default="", description="the answer, using only what the excerpt shows"
    )


class JudgeVerdict(BaseModel):
    """The judge's call on one answer."""

    verdict: Literal["correct", "partial", "wrong"] = Field(
        description="'correct', 'partial' or 'wrong', per the rubric"
    )
    reason: str = Field(default="", description="one sentence explaining the verdict")
