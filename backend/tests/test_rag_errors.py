"""Chat-model failure classification, by the class names in an exception's MRO."""

import pytest

from app.rag.errors import RetryableChatError, TerminalChatError, classify_chat_error


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("RateLimitError", RetryableChatError),
        ("APIConnectionError", RetryableChatError),
        ("APITimeoutError", RetryableChatError),
        ("InternalServerError", RetryableChatError),
        ("AuthenticationError", TerminalChatError),
        ("NotFoundError", TerminalChatError),
        ("BadRequestError", TerminalChatError),
    ],
)
def test_known_exception_names_are_classified(name: str, expected: type[Exception]) -> None:
    """Built locally rather than imported from `openai`/`anthropic`: classification is
    by class name alone, so a fake with the right name must classify identically to
    the real SDK exception it stands in for (M4.5 spec 2.1)."""
    fake_exception_class = type(name, (Exception,), {})
    error = fake_exception_class("boom")

    result = classify_chat_error(error)

    assert isinstance(result, expected)


def test_an_unmapped_exception_is_not_classified() -> None:
    """Falls through to the caller's unclassified-failure safety net rather than this
    function guessing (`.claude/rules/ingestion.md`)."""
    assert classify_chat_error(ValueError("weird")) is None


def test_langchains_provider_wrappers_are_classified() -> None:
    """The regression: LangChain wraps every provider failure in its own subclass.

    `openai.APITimeoutError` reaches this code as `OpenAITimeoutError`, so matching on
    `type(error).__name__` alone classified nothing at all from either provider --
    every chat failure fell through to the unclassified path, which retries once and
    then dead-letters. A rate limit got one attempt instead of three, a rejected key
    got a pointless retry, and nothing reported that the classifier had gone blind.

    Imported from LangChain rather than restated as fakes on purpose: a hand-rolled
    stub with the same name would pass whatever the real class hierarchy did next.
    Built with `__new__` because these constructors want a live provider response, and
    the classifier reads only the class -- never the instance.
    """
    from langchain_anthropic.chat_models import (
        AnthropicRateLimitError,
        AnthropicTimeoutError,
    )
    from langchain_openai.chat_models.base import (
        OpenAIAuthenticationError,
        OpenAIModelNotFoundError,
        OpenAIRateLimitError,
        OpenAITimeoutError,
    )

    retryable: tuple[type[Exception], ...] = (
        OpenAITimeoutError,
        OpenAIRateLimitError,
        AnthropicTimeoutError,
        AnthropicRateLimitError,
    )
    for wrapper in retryable:
        verdict = classify_chat_error(wrapper.__new__(wrapper))
        assert isinstance(verdict, RetryableChatError), wrapper.__name__

    terminal: tuple[type[Exception], ...] = (
        OpenAIAuthenticationError,
        OpenAIModelNotFoundError,
    )
    for wrapper in terminal:
        verdict = classify_chat_error(wrapper.__new__(wrapper))
        assert isinstance(verdict, TerminalChatError), wrapper.__name__
