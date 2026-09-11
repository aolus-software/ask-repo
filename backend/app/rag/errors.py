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
    {
        # Raised by the `openai` and `anthropic` SDKs themselves.
        "RateLimitError",
        "APIConnectionError",
        "APITimeoutError",
        "InternalServerError",
        "OverloadedError",
        # LangChain's provider-agnostic bases. Listed as well as the SDK names above
        # so this keeps classifying if a wrapper ever stops subclassing the SDK error
        # it wraps -- the MRO walk below would then have only these to match on.
        "ModelRateLimitError",
        "ModelConnectionError",
        "ModelTimeoutError",
        "ModelAPIError",
    }
)
_TERMINAL_EXCEPTION_NAMES = frozenset(
    {
        "AuthenticationError",
        "NotFoundError",
        "BadRequestError",
        "PermissionDeniedError",
        "ModelAuthenticationError",
        "ModelNotFoundError",
        "ModelInvalidRequestError",
        "ContextOverflowError",
    }
)


def classify_chat_error(error: Exception) -> ChatError | None:
    """What `error` means for retrying, judged by the class names in its MRO.

    By name rather than `isinstance`: `openai` and `anthropic`'s SDKs were generated
    by the same tooling and raise identically-named exceptions from different
    modules, and matching by name means this function needs no import from either
    package. Deliberately not exhaustive: an unmapped name returns `None` and the
    caller falls through to its own unclassified-failure safety net
    (`.claude/rules/ingestion.md`) rather than this function guessing.

    **The whole MRO, not just `type(error).__name__`**, and that is the part with a
    scar on it. LangChain wraps every provider failure in a subclass of its own before
    it reaches us -- `openai.APITimeoutError` arrives as `OpenAITimeoutError`, and its
    Anthropic twin as `AnthropicTimeoutError`. Matching the leaf name alone therefore
    classified **nothing** from either provider: every chat failure fell through to the
    unclassified path, which retries once and then dead-letters. A rate limit got one
    attempt instead of three, and a rejected key got a pointless retry, with nothing
    reporting that the classifier had stopped matching.
    """
    names = {klass.__name__ for klass in type(error).__mro__}
    # Retryable wins a tie deliberately: spending one more attempt on something
    # terminal costs a retry, while refusing to retry something transient loses work.
    if names & _RETRYABLE_EXCEPTION_NAMES:
        return RetryableChatError(str(error))
    if names & _TERMINAL_EXCEPTION_NAMES:
        return TerminalChatError(str(error))
    return None
