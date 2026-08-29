"""Provider selection for the answering model."""

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


def test_the_configured_temperature_reaches_the_model() -> None:
    """Answers about code should be reproducible. A default that silently failed to
    apply would show up as flaky answers, not as an error."""
    settings = Settings(chat_provider="ollama", chat_temperature=0.0)

    assert build_chat_model(settings).temperature == 0.0
