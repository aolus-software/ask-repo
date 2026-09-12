"""Provider selection for the answering model."""

from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

from app.config import Settings
from app.rag.chat import build_chat_model


def settings_for(provider: str) -> Settings:
    return Settings(
        chat_provider=provider,  # type: ignore[arg-type]  # narrowed by the Literal at runtime
        chat_model="test-model",
        chat_base_url="http://chat.test",
        chat_api_key="key",
    )


def test_the_factory_selects_by_provider() -> None:
    assert isinstance(build_chat_model(settings_for("ollama")), ChatOllama)
    assert isinstance(build_chat_model(settings_for("openai")), ChatOpenAI)
    assert isinstance(build_chat_model(settings_for("anthropic")), ChatAnthropic)


def test_the_configured_temperature_reaches_the_model() -> None:
    """Answers about code should be reproducible. A default that silently failed to
    apply would show up as flaky answers, not as an error."""
    settings = Settings(chat_provider="ollama", chat_temperature=0.0)
    model = build_chat_model(settings)

    # Narrowed rather than cast: `temperature` lives on the concrete model, not on
    # the `BaseChatModel` the factory is declared to return.
    assert isinstance(model, ChatOllama)
    assert model.temperature == 0.0


def test_every_provider_gets_the_configured_timeout() -> None:
    """The regression that made checklist generation look slow rather than broken.

    `CHAT_TIMEOUT_SECONDS` used to be applied in exactly one place -- the graph's
    answer nodes -- so a question was bounded while checklist generation, mock-data
    generation, and the classify and grade nodes fell through to the provider client's
    own default. For the OpenAI client that is ten minutes per request, and a stalled
    reduce step therefore sat there for half an hour rather than failing.

    Each provider names the field differently, which is exactly why this is asserted
    per provider rather than trusted: `timeout` is an alias on all three, and passing
    it to a class that does not accept it would be silently ignored.
    """
    seconds = 42

    def built(provider: str) -> BaseChatModel:
        settings = settings_for(provider)
        return build_chat_model(settings.model_copy(update={"chat_timeout_seconds": seconds}))

    openai_model = built("openai")
    assert isinstance(openai_model, ChatOpenAI)
    assert openai_model.request_timeout == seconds

    anthropic_model = built("anthropic")
    assert isinstance(anthropic_model, ChatAnthropic)
    assert anthropic_model.default_request_timeout == seconds

    ollama_model = built("ollama")
    assert isinstance(ollama_model, ChatOllama)
    assert ollama_model.client_kwargs == {"timeout": seconds}


def test_the_provider_client_does_not_retry_on_its_own() -> None:
    """Two stacked retry mechanisms multiply the wait and hide the classifier.

    LangChain defaults to `max_retries=2`, so a hung call would cost the timeout three
    times over before raising -- and the Kafka ladder would then retry that whole thing
    `KAFKA_MAX_ATTEMPTS` times. Worse, the provider client retries on its own rules, so
    a failure `classify_chat_error` knows is terminal would be attempted three times
    before the code that knows better ever sees it.
    """
    openai_model = build_chat_model(settings_for("openai"))
    assert isinstance(openai_model, ChatOpenAI)
    assert openai_model.max_retries == 0

    anthropic_model = build_chat_model(settings_for("anthropic"))
    assert isinstance(anthropic_model, ChatAnthropic)
    assert anthropic_model.max_retries == 0


def test_an_explicit_timeout_overrides_the_interactive_one() -> None:
    """The worker's calls are not interactive, and one number cannot serve both.

    A checklist reduce folds every file's findings into a single structured call and
    legitimately runs for minutes; a question that has not started answering in that
    long has failed. Bounding both at the interactive figure cut the reduce off
    mid-call, which surfaces as `RetryableChatError` with **no HTTP response logged**
    -- the request never completed -- and the ladder then spent its whole budget
    re-running a call that was always going to need longer than it was given.
    """
    settings = settings_for("openai").model_copy(update={"chat_timeout_seconds": 180})

    model = build_chat_model(settings, timeout_seconds=600)
    assert isinstance(model, ChatOpenAI)
    assert model.request_timeout == 600

    # Omitting it still means "interactive", so no other caller changed behaviour.
    default = build_chat_model(settings)
    assert isinstance(default, ChatOpenAI)
    assert default.request_timeout == 180
