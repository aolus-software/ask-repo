"""The worker startup's chat-model gate, isolated from the ordering it protects."""

from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel

from app.config import Settings
from app.rag.capability import TrivialProbeSchema
from app.rag.errors import TerminalChatError
from app.worker import _build_chat_model


class _RaisingBound:
    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    async def ainvoke(self, prompt: str) -> object:
        raise self._exception


class _RaisingChatModel:
    """`with_structured_output(...).ainvoke` always raises."""

    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    def with_structured_output(self, schema: type) -> _RaisingBound:
        return _RaisingBound(self._exception)


class _RespondingBound:
    async def ainvoke(self, prompt: str) -> object:
        return TrivialProbeSchema(answer="ok")


class _RespondingChatModel:
    """`with_structured_output(...).ainvoke` always returns a valid probe response."""

    def with_structured_output(self, schema: type) -> _RespondingBound:
        return _RespondingBound()


async def test_a_failing_probe_blocks_before_anything_else_is_built(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`main` builds the ingestion pipeline and both consumers only after this call
    returns, so a probe failure here is what stops the worker from ever constructing
    them -- there is no separate "don't build the pipeline" branch to test.
    """
    fake = _RaisingChatModel(RuntimeError("no route to host"))
    monkeypatch.setattr("app.worker.build_chat_model", lambda settings: cast(BaseChatModel, fake))

    with pytest.raises(TerminalChatError, match="RuntimeError"):
        await _build_chat_model(Settings())


async def test_a_working_model_passes_through_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _RespondingChatModel()
    monkeypatch.setattr("app.worker.build_chat_model", lambda settings: cast(BaseChatModel, fake))

    result = await _build_chat_model(Settings())

    assert result is fake
