"""Provider selection, task prefixes, and error classification."""

import json

import httpx
import pytest

from app.config import Settings
from app.ingestion.embedder import Embedder, FakeEmbedder, build_embedder, probe_dimensions
from app.ingestion.embedder.ollama import OllamaEmbedder
from app.ingestion.embedder.openai import OpenAIEmbedder
from app.ingestion.embedder.voyage import VoyageEmbedder
from app.ingestion.errors import IngestionError, RetryableIngestionError, TerminalIngestionError


def _build(provider: str, transport: httpx.AsyncBaseTransport) -> Embedder:
    """One embedder of the given provider, wired to a stub transport."""
    if provider == "ollama":
        return OllamaEmbedder(base_url="http://e.test", model="m", transport=transport)
    if provider == "openai":
        return OpenAIEmbedder(
            base_url="http://e.test", model="m", api_key="key", transport=transport
        )
    return VoyageEmbedder(base_url="http://e.test", model="m", api_key="key", transport=transport)


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


async def test_voyage_documents_and_queries_use_different_input_types() -> None:
    """Voyage encodes the task distinction as an `input_type` request parameter
    rather than a text prefix. Swapping the two values degrades retrieval exactly
    like a swapped Ollama prefix would, with no error to catch it — so this test
    reads the actual request body sent for each call, not a return value."""
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": [{"embedding": [0.1, 0.2]}]})

    transport = httpx.MockTransport(handler)
    embedder = VoyageEmbedder(
        base_url="http://embed.test", model="voyage-code-2", api_key="key", transport=transport
    )

    await embedder.embed_documents(["some code"])
    await embedder.embed_query("some question")

    assert json.loads(seen[0].read())["input_type"] == "document"
    assert json.loads(seen[1].read())["input_type"] == "query"


@pytest.mark.parametrize("provider", ["ollama", "openai", "voyage"])
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, TerminalIngestionError),
        (403, TerminalIngestionError),
        (500, RetryableIngestionError),
        (503, RetryableIngestionError),
    ],
)
async def test_status_codes_are_classified_consistently_across_providers(
    provider: str, status: int, expected: type[IngestionError]
) -> None:
    """401/403 never retry — a bad key stays bad. Every other >= 400 does, because
    it might be a transient provider outage. This must hold identically for every
    provider: a classifier that only checks one status code, or that is wired to
    only one provider, would leave the other providers' failures misrouted with
    nothing to catch it."""
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text="error"))
    embedder = _build(provider, transport)

    with pytest.raises(expected):
        await embedder.embed_documents(["x"])


async def test_dimensions_are_probed_not_declared() -> None:
    """A number kept in sync by hand is a number that will eventually be wrong."""
    assert await probe_dimensions(FakeEmbedder(dimensions=768)) == 768
