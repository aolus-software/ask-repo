"""Translating one eval question, and checking mechanically that it kept its code.

A translated set exists to measure the language, so a translation that renames an
identifier or drops a path would measure the translator instead (spec §3.4). The check
is mechanical, not a second model call: every backticked span and every path-shaped
token in the English question must appear unchanged in the translation.

No question or translation text reaches a log line: a failed attempt is logged by the
error's class alone (`.claude/rules/call-log.md` rule 2).
"""

import logging
import re
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable

from app.core.language import Language
from app.eval.model_output import TranslatedQuestion
from app.observability.features import CallFeature, call_config
from app.rag.errors import classify_chat_error
from app.rag.grounding import path_tokens
from app.rag.prompts import build_eval_translate_prompt

logger = logging.getLogger(__name__)

# One retry after the first attempt: spec §3.4, "retried once".
ATTEMPTS = 2

_BACKTICKED = re.compile(r"`([^`\n]+)`")


@dataclass(frozen=True, slots=True)
class Translation:
    """The last attempt's text, or `None` if no attempt returned any, and whether it passed."""

    question: str | None
    faithful: bool


def protected_tokens(text: str) -> set[str]:
    """What a translation of `text` must keep verbatim: backticked spans and paths."""
    return set(_BACKTICKED.findall(text)) | set(path_tokens(text))


def is_faithful(source: str, translation: str) -> bool:
    """Whether `translation` is non-empty and contains every protected token of `source`."""
    if not translation.strip():
        return False
    return all(token in translation for token in protected_tokens(source))


async def translate_question(
    model: Runnable[list[BaseMessage], Any],
    *,
    question: str,
    language: Language,
    scope: dict[str, Any],
) -> Translation:
    """Translate one question, retrying once when the result is unusable or unfaithful.

    A classified provider error raises (terminal fails the job, retryable defers it),
    exactly as in `EvalSetGenerator._generate_one`; anything else counts as one failed
    attempt.
    """
    last: str | None = None
    for _ in range(ATTEMPTS):
        try:
            result = await model.ainvoke(
                build_eval_translate_prompt(question=question, language=language),
                config=call_config(CallFeature.EVAL_TRANSLATE, **scope),
            )
        except Exception as error:
            classified = classify_chat_error(error)
            if classified is not None:
                raise classified from error
            logger.warning("an eval question could not be translated: %s", type(error).__name__)
            continue
        if not isinstance(result, TranslatedQuestion):
            continue
        candidate = result.question.strip()
        if candidate:
            last = candidate
        if is_faithful(question, candidate):
            return Translation(question=candidate, faithful=True)
    return Translation(question=last, faithful=False)
