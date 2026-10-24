"""The translation call and its mechanical faithfulness check (spec §3.4)."""

import uuid
from typing import Any

import pytest

from app.core.language import Language
from app.eval.model_output import TranslatedQuestion
from app.eval.translation import Translation, is_faithful, protected_tokens, translate_question
from app.observability.features import FEATURE_KEY, CallFeature
from app.rag.errors import TerminalChatError

SCOPE: dict[str, Any] = {"trace_seed": "s", "project_id": uuid.uuid4(), "attempt": 0}


class AuthenticationError(Exception):
    """Named so `classify_chat_error` maps it to terminal, as a provider's would be."""


class _Replay:
    """Returns or raises each step in turn, recording every config it was called with."""

    def __init__(self, steps: list[object]) -> None:
        self.steps = list(steps)
        self.configs: list[Any] = []

    async def ainvoke(self, messages: object, config: Any = None) -> object:
        self.configs.append(config)
        step = self.steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


def test_backticked_spans_and_paths_are_protected() -> None:
    question = "Where does `validate_repo_url` reject a host? See backend/app/core/repo_url.py."
    assert protected_tokens(question) == {"validate_repo_url", "backend/app/core/repo_url.py"}


def test_a_translation_keeping_every_token_is_faithful() -> None:
    source = "What does `claim` do in app/repositories/project.py?"
    assert is_faithful(source, "Apa yang dilakukan `claim` di app/repositories/project.py?")


def test_a_renamed_identifier_is_unfaithful() -> None:
    source = "What does `claim` do?"
    assert not is_faithful(source, "Apa yang dilakukan `klaim`?")


def test_a_dropped_path_is_unfaithful() -> None:
    assert not is_faithful("Explain app/core/access.py.", "Jelaskan berkas akses.")


def test_a_question_with_nothing_protected_is_faithful_when_non_empty() -> None:
    assert is_faithful("How is a login rate limited?", "ログインはどのように制限されますか?")
    assert not is_faithful("How is a login rate limited?", "   ")


async def test_a_faithful_first_attempt_makes_one_tagged_call() -> None:
    model = _Replay([TranslatedQuestion(question="Apa yang dilakukan `claim`?")])

    outcome = await translate_question(
        model, question="What does `claim` do?", language=Language.ID, scope=SCOPE
    )

    assert outcome == Translation(question="Apa yang dilakukan `claim`?", faithful=True)
    assert len(model.configs) == 1
    assert model.configs[0]["metadata"][FEATURE_KEY] == CallFeature.EVAL_TRANSLATE.value


async def test_an_unfaithful_attempt_is_retried_once_then_kept_as_unfaithful() -> None:
    model = _Replay(
        [
            TranslatedQuestion(question="Apa yang dilakukan `klaim`?"),
            TranslatedQuestion(question="Apa fungsi klaim?"),
        ]
    )

    outcome = await translate_question(
        model, question="What does `claim` do?", language=Language.ID, scope=SCOPE
    )

    assert outcome == Translation(question="Apa fungsi klaim?", faithful=False)
    assert len(model.configs) == 2


async def test_a_malformed_response_counts_as_a_failed_attempt() -> None:
    model = _Replay([ValueError("bad json"), ValueError("bad json")])

    outcome = await translate_question(
        model, question="What does `claim` do?", language=Language.KO, scope=SCOPE
    )

    assert outcome == Translation(question=None, faithful=False)


async def test_a_terminal_provider_error_propagates() -> None:
    model = _Replay([AuthenticationError("bad key")])

    with pytest.raises(TerminalChatError):
        await translate_question(model, question="q", language=Language.JA, scope=SCOPE)
