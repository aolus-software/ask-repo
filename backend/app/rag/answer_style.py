"""A user's answer style: three dials, each mapped to one fixed sentence.

A leaf module on purpose — it imports nothing from the rest of `app.rag`, so the
model, the schemas, the graph state and the prompts can all depend on it without a
cycle. Each enum holds only the *non-default* values: the middle position of a dial
("standard", "familiar") is `None`, because two spellings of "add no sentence" is how
a dial ends up rendering differently from what the UI shows.

The sentences themselves live in `app/rag/prompts.py`, as upper-case constants, so
`PROMPT_VERSION` changes when one is edited. No user text is ever stored or rendered:
see `.claude/rules/rag.md`, "The reader-preference slot".
"""

from dataclasses import dataclass
from enum import StrEnum


class AnswerDetail(StrEnum):
    """How long and how deep the answer goes."""

    BRIEF = "brief"
    THOROUGH = "thorough"


class AnswerFamiliarity(StrEnum):
    """What the reader can be assumed to know about this repository."""

    NEW = "new"
    EXPERT = "expert"


class AnswerFormat(StrEnum):
    """How the answer is laid out."""

    PROSE = "prose"
    BULLETS = "bullets"


@dataclass(frozen=True)
class AnswerStyle:
    """The three dials. `None` on a dial means no preference, and adds no sentence."""

    detail: AnswerDetail | None = None
    familiarity: AnswerFamiliarity | None = None
    format: AnswerFormat | None = None

    @property
    def is_empty(self) -> bool:
        """Whether no dial is set — the prompt is then exactly the default one."""
        return self.detail is None and self.familiarity is None and self.format is None

    @classmethod
    def from_columns(
        cls, detail: str | None, familiarity: str | None, format: str | None
    ) -> "AnswerStyle":
        """Build from the stored strings. An unknown value raises `ValueError`."""
        return cls(
            detail=AnswerDetail(detail) if detail is not None else None,
            familiarity=AnswerFamiliarity(familiarity) if familiarity is not None else None,
            format=AnswerFormat(format) if format is not None else None,
        )
