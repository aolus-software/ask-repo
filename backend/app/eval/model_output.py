"""What the eval generator and judge return, as structured output.

The `Field(description=...)` strings are sent to the model as part of its instructions,
yet they sit outside every prompt version's hash (`app/rag/prompt_version.py` covers
`app/rag/prompts.py` constants only). Editing one changes behaviour without changing the version.
"""

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


class TranslatedQuestion(BaseModel):
    """One eval question, translated."""

    question: str = Field(default="", description="the question in the target language")
