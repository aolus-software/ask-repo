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
    monkeypatch.setattr(
        "app.worker.build_chat_model",
        lambda settings, **_: cast(BaseChatModel, fake),
    )

    with pytest.raises(TerminalChatError, match="RuntimeError"):
        await _build_chat_model(Settings())


async def test_a_working_model_passes_through_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = cast(BaseChatModel, _RespondingChatModel())
    monkeypatch.setattr("app.worker.build_chat_model", lambda settings, **_: fake)

    result = await _build_chat_model(Settings())

    assert result is fake


async def test_the_worker_bounds_its_calls_by_the_generation_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generation is not interactive, and the worker runs nothing else.

    A checklist reduce legitimately runs for minutes, so bounding it by the
    interactive `chat_timeout_seconds` cut it off mid-call -- surfacing as
    `RetryableChatError` with no HTTP response logged, because the request never
    completed, and then re-running under the retry ladder with the same budget.
    """
    seen: dict[str, object] = {}
    fake = cast(BaseChatModel, _RespondingChatModel())

    def record(settings: Settings, *, timeout_seconds: int | None = None) -> BaseChatModel:
        seen["timeout_seconds"] = timeout_seconds
        return fake

    monkeypatch.setattr("app.worker.build_chat_model", record)
    settings = Settings(chat_timeout_seconds=180, generation_timeout_seconds=600)

    await _build_chat_model(settings)

    assert seen["timeout_seconds"] == 600
