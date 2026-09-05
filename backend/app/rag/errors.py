"""What kind of failure a chat-model call was, which decides whether it retries.

Shaped like `app/ingestion/errors.py`, and deliberately not unified with it: this is
the chat-model failure domain, not the ingestion one, and naming it separately is
what lets `app/queue/checklist.py` route on either without pretending they are the
same kind of thing.
"""


class ChatError(Exception):
    """Base for every failure a chat-model call raises deliberately."""


class TerminalChatError(ChatError):
    """Retrying will not help: rejected key, unknown model, context-length rejection."""


class RetryableChatError(ChatError):
    """A transient failure: rate limit, provider outage, connection blip."""


_RETRYABLE_EXCEPTION_NAMES = frozenset(
    {"RateLimitError", "APIConnectionError", "APITimeoutError", "InternalServerError"}
)
_TERMINAL_EXCEPTION_NAMES = frozenset(
    {"AuthenticationError", "NotFoundError", "BadRequestError"}
)


def classify_chat_error(error: Exception) -> ChatError | None:
    """What `error` means for retrying, judged by its class name alone.

    By name rather than `isinstance`: `openai` and `anthropic`'s SDKs were generated
    by the same tooling and raise identically-named exceptions from different
    modules, and matching by name means this function needs no import from either
    package. Deliberately not exhaustive: an unmapped name returns `None` and the
    caller falls through to its own unclassified-failure safety net
    (`.claude/rules/ingestion.md`) rather than this function guessing.
    """
    name = type(error).__name__
    if name in _RETRYABLE_EXCEPTION_NAMES:
        return RetryableChatError(str(error))
    if name in _TERMINAL_EXCEPTION_NAMES:
        return TerminalChatError(str(error))
    return None
