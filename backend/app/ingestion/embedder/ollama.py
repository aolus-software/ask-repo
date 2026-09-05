"""Ollama's embedding endpoint."""

import httpx

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

DOCUMENT_PREFIX = "search_document: "
QUERY_PREFIX = "search_query: "
TIMEOUT_SECONDS = 120.0


class OllamaEmbedder:
    """Embeddings from a local Ollama server."""

    def __init__(
        self, *, base_url: str, model: str, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.model_id = model
        self.dimensions = 0  # set by probe_dimensions at worker startup
        self._base_url = base_url.rstrip("/")
        self._transport = transport

    async def _post(self, texts: list[str]) -> list[list[float]]:
        """One batched call, with failures classified for the retry chain."""
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/api/embed", json={"model": self.model_id, "input": texts}
                )
            except httpx.HTTPError as error:
                raise RetryableIngestionError(f"Embedding request failed: {error}") from error

        if response.status_code in (401, 403):
            raise TerminalIngestionError("Embedding provider rejected the credentials.")
        if response.status_code in (400, 404, 422):
            raise TerminalIngestionError(
                f"Embedding provider rejected the request ({response.status_code})."
            )
        if response.status_code >= 400:
            raise RetryableIngestionError(f"Embedding provider returned {response.status_code}.")
        return response.json()["embeddings"]  # type: ignore[no-any-return]  # untyped JSON body

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed indexed content."""
        return await self._post([f"{DOCUMENT_PREFIX}{text}" for text in texts])

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""
        return (await self._post([f"{QUERY_PREFIX}{text}"]))[0]
