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


def build_chat_model(settings: Settings) -> BaseChatModel:
    """The chat model this instance is configured to use."""
    if settings.chat_provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.chat_model,
            base_url=settings.chat_base_url,
            temperature=settings.chat_temperature,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=settings.chat_model,
        base_url=settings.chat_base_url,
        api_key=settings.chat_api_key or "",  # type: ignore[arg-type]  # SecretStr coerces
        temperature=settings.chat_temperature,
    )
