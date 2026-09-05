"""Chat-model failure classification, by exception class name alone."""

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
