"""Turning text into vectors, from whichever provider the instance is configured for.

Two methods rather than one, deliberately: `nomic-embed-text` and `voyage-code-*`
require task prefixes (`search_document:` versus `search_query:`), and using the
wrong one degrades retrieval with no error at all. Encoding the distinction in the
interface means an implementation cannot forget it.
"""

from typing import Protocol

from app.config import Settings


class Embedder(Protocol):
    """A source of embeddings for one configured model."""

    model_id: str
    dimensions: int

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed indexed content. Uses the document task prefix where required."""
        ...

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query. Uses the query task prefix where required."""
        ...


class FakeEmbedder:
    """Deterministic test double. Vectors are meaningless but correctly shaped."""

    def __init__(self, *, dimensions: int = 8, model_id: str = "fake") -> None:
        self.dimensions = dimensions
        self.model_id = model_id

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """One vector per text, derived from its length so results are stable."""
        return [
            [float((len(text) + i) % 10) / 10 for i in range(self.dimensions)] for text in texts
        ]

    async def embed_query(self, text: str) -> list[float]:
        """A single vector, same derivation."""
        return (await self.embed_documents([text]))[0]


def build_embedder(settings: Settings) -> Embedder:
    """The embedder this instance is configured to use.

    Imports are local so an instance using a hosted provider does not import the
    others, and a broken optional dependency cannot break an unrelated deployment.
    """
    if settings.embedding_provider == "ollama":
        from app.ingestion.embedder.ollama import OllamaEmbedder

        return OllamaEmbedder(base_url=settings.embedding_base_url, model=settings.embedding_model)
    if settings.embedding_provider == "openai":
        from app.ingestion.embedder.openai import OpenAIEmbedder

        return OpenAIEmbedder(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            api_key=settings.embedding_api_key or "",
        )
    from app.ingestion.embedder.voyage import VoyageEmbedder

    return VoyageEmbedder(
        base_url=settings.embedding_base_url,
        model=settings.embedding_model,
        api_key=settings.embedding_api_key or "",
    )


async def probe_dimensions(embedder: Embedder) -> int:
    """Ask the model how wide its vectors are, by embedding one fixed string.

    Probed rather than configured: a declared dimension is a second source of truth
    that drifts the moment someone changes the model and forgets the number. The
    result names the Qdrant collection, so being wrong is not a small mistake.
    """
    vector = await embedder.embed_query("dimension probe")
    return len(vector)
