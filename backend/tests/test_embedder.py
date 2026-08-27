"""Provider selection, task prefixes, and error classification."""

import httpx
import pytest

from app.config import Settings
from app.ingestion.embedder import FakeEmbedder, build_embedder, probe_dimensions
from app.ingestion.embedder.ollama import OllamaEmbedder
from app.ingestion.embedder.openai import OpenAIEmbedder
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError


def settings_for(provider: str) -> Settings:
    return Settings(
        embedding_provider=provider,  # type: ignore[arg-type]  # narrowed by the Literal at runtime
        embedding_model="test-model",
        embedding_base_url="http://embed.test",
        embedding_api_key="key",
    )


def test_the_factory_selects_by_provider() -> None:
    assert isinstance(build_embedder(settings_for("ollama")), OllamaEmbedder)
    assert isinstance(build_embedder(settings_for("openai")), OpenAIEmbedder)


async def test_documents_and_queries_use_different_prefixes() -> None:
    """nomic and voyage require a task prefix. Using the wrong one degrades
    retrieval silently — no error, just worse answers — so it is encoded in the
    interface rather than left to a caller."""
    seen: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.extend(request.read().decode().split('"input"')[1:])
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    transport = httpx.MockTransport(handler)
    embedder = OllamaEmbedder(
        base_url="http://embed.test", model="nomic-embed-text", transport=transport
    )

    await embedder.embed_documents(["some code"])
    await embedder.embed_query("some question")

    assert "search_document" in seen[0]
    assert "search_query" in seen[1]


async def test_a_server_error_is_retryable() -> None:
    transport = httpx.MockTransport(lambda request: httpx.Response(503, text="unavailable"))
    embedder = OllamaEmbedder(base_url="http://e.test", model="m", transport=transport)

    with pytest.raises(RetryableIngestionError):
        await embedder.embed_documents(["x"])


async def test_an_auth_failure_is_terminal() -> None:
    """A bad API key will still be bad in ten minutes."""
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text="unauthorized"))
    embedder = OpenAIEmbedder(
        base_url="http://e.test", model="m", api_key="bad", transport=transport
    )

    with pytest.raises(TerminalIngestionError):
        await embedder.embed_documents(["x"])


async def test_dimensions_are_probed_not_declared() -> None:
    """A number kept in sync by hand is a number that will eventually be wrong."""
    assert await probe_dimensions(FakeEmbedder(dimensions=768)) == 768
