"""The answering model, from whichever provider the instance is configured for.

Shaped like `app/ingestion/embedder/__init__.py` on purpose — a `build_*(settings)`
factory with provider imports done locally, so an instance using a hosted provider
never imports the local one and a broken optional dependency cannot break an
unrelated deployment.

Returns LangChain's `BaseChatModel` rather than a hand-rolled protocol, which is the
one place this differs from the embedder it otherwise mirrors. `astream` and
`ainvoke` are the entire interface used, and LangChain ships streaming-capable test
doubles; a protocol wrapping two methods would buy indirection and cost those fakes.
"""

from langchain_core.language_models import BaseChatModel

from app.config import Settings

PROVIDER_RETRIES = 0
"""Retries the provider client performs on its own. Deliberately none.

LangChain's OpenAI and Anthropic clients default to `max_retries=2`, which is a second
retry mechanism stacked under the one this application already owns: the Kafka ladder in
`app/queue/`, whose rungs are chosen by `classify_chat_error`. Left at the default the
two multiply -- a hung call costs `CHAT_TIMEOUT_SECONDS` three times over before it even
raises, and the ladder then retries that whole thing `KAFKA_MAX_ATTEMPTS` times.

Retrying here would also bypass the classifier: a provider client retries on its own
rules, so a terminal failure it happens to consider retryable is attempted three times
before the code that knows it is terminal ever sees it.
"""


def build_chat_model(settings: Settings, *, timeout_seconds: int | None = None) -> BaseChatModel:
    """The chat model this instance is configured to use.

    **Every provider gets `chat_timeout_seconds`, and that is not decoration.** The
    setting used to be applied in exactly one place -- the graph's answer nodes
    (`app/rag/graph/build.py`) -- so a question was bounded while checklist generation,
    mock-data generation, and the classify and grade nodes were not. They fell back to
    the provider client's own default, which for the OpenAI client is ten minutes per
    request and three attempts.

    The symptom was not an error. A checklist generation whose reduce step stalled sat
    there for half an hour per attempt, and the run looked slow rather than broken.

    `timeout_seconds` overrides `chat_timeout_seconds` for callers whose calls are not
    interactive. The worker passes `generation_timeout_seconds`, because one number
    cannot serve both: a checklist reduce folds every file's findings into a single
    structured call and legitimately runs for minutes, while a question that has not
    started answering in that long has failed. Bounding both at the interactive figure
    cuts the reduce off mid-call -- which surfaces as `RetryableChatError` with no HTTP
    response logged, since the request never completed -- and the retry ladder then
    spends the whole budget re-running a call that was always going to take longer than
    it was given.

    `chat_reasoning` gets the same complete treatment (issue #26): "default" passes `None`,
    which every provider already treats as unset, leaving its own default behavior untouched; "off"
    explicitly disables reasoning on all three, in whatever vocabulary each one uses.
    `chat_extra_model_kwargs` is a separate, narrower escape hatch -- forwarded as
    `extra_body` on the `openai` branch only, for self-hosted OpenAI-compatible servers
    whose thinking toggle isn't `reasoning_effort`.
    """
    timeout = timeout_seconds if timeout_seconds is not None else settings.chat_timeout_seconds
    reasoning_off = settings.chat_reasoning == "off"

    if settings.chat_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.chat_model,
            base_url=settings.chat_base_url,
            temperature=settings.chat_temperature,
            # No first-class timeout field on this class; the underlying Ollama client
            # takes one and passes it to httpx.
            client_kwargs={"timeout": timeout},
            reasoning=False if reasoning_off else None,
        )

    if settings.chat_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            # `model_name` here, not `model`: the field's alias is what mypy's
            # pydantic plugin synthesizes into the constructor signature, and
            # `populate_by_name` isn't enough to make it accept the bare field name too.
            model_name=settings.chat_model,
            base_url=settings.chat_base_url,
            api_key=settings.chat_api_key or "",  # type: ignore[arg-type]  # SecretStr coerces
            temperature=settings.chat_temperature,
            timeout=timeout,
            max_retries=PROVIDER_RETRIES,
            stop=None,
            thinking={"type": "disabled"} if reasoning_off else None,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.chat_model,
        base_url=settings.chat_base_url,
        api_key=settings.chat_api_key or "",  # type: ignore[arg-type]  # SecretStr coerces
        temperature=settings.chat_temperature,
        timeout=timeout,
        max_retries=PROVIDER_RETRIES,
        reasoning_effort="none" if reasoning_off else None,
        extra_body=dict(settings.chat_extra_model_kwargs) or None,
    )
