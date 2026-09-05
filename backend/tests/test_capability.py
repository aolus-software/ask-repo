"""The boot-time structured-output probe, with no served model."""

from typing import cast

import pytest
from langchain_core.language_models import BaseChatModel

from app.rag.capability import TrivialProbeSchema, probe_structured_output
from app.rag.errors import RetryableChatError, TerminalChatError


class _RespondingBound:
    def __init__(self, result: object) -> None:
        self._result = result

    async def ainvoke(self, prompt: str) -> object:
        return self._result


class _RespondingChatModel:
    """`with_structured_output(...).ainvoke` always returns the given object."""

    def __init__(self, result: object) -> None:
        self._result = result

    def with_structured_output(self, schema: type) -> _RespondingBound:
        return _RespondingBound(self._result)


class _RaisingBound:
    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    async def ainvoke(self, prompt: str) -> object:
        raise self._exception


class _RaisingChatModel:
    """`with_structured_output(...).ainvoke` always raises the given exception."""

    def __init__(self, exception: Exception) -> None:
        self._exception = exception

    def with_structured_output(self, schema: type) -> _RaisingBound:
        return _RaisingBound(self._exception)


async def test_a_valid_structured_response_passes() -> None:
    model = _RespondingChatModel(TrivialProbeSchema(answer="ok"))

    await probe_structured_output(cast(BaseChatModel, model))


async def test_a_classifiable_failure_is_reraised_classified() -> None:
    """A rate limit at boot is retryable in principle, but the probe itself never
    retries (M4.5 spec 3.3) -- it is the caller's job to decide what "retry" means
    for a process that has not finished starting."""
    model = _RaisingChatModel(type("RateLimitError", (Exception,), {})("slow down"))

    with pytest.raises(RetryableChatError):
        await probe_structured_output(cast(BaseChatModel, model))


async def test_an_unclassifiable_failure_is_wrapped_as_terminal() -> None:
    model = _RaisingChatModel(RuntimeError("connection refused"))

    with pytest.raises(TerminalChatError, match="RuntimeError"):
        await probe_structured_output(cast(BaseChatModel, model))


async def test_a_wrong_shaped_response_is_terminal() -> None:
    """No tool-calling or JSON mode support: the model answered, but not with the
    schema it was asked for."""
    model = _RespondingChatModel("just a plain string")

    with pytest.raises(TerminalChatError, match="structured response"):
        await probe_structured_output(cast(BaseChatModel, model))
