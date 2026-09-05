"""OpenAI's embedding endpoint.

Unlike Ollama's `nomic-embed-text` and Voyage's `voyage-code-*`, OpenAI's embedding
models take no task prefix: a document and a query for the same text embed
identically. `embed_documents` and `embed_query` therefore send the text
unchanged — this is not a bug or an oversight to "fix" into matching Ollama, it is
how the model was trained.
"""

import httpx

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

TIMEOUT_SECONDS = 120.0


class OpenAIEmbedder:
    """Embeddings from OpenAI's hosted API."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.model_id = model
        self.dimensions = 0  # set by probe_dimensions at worker startup
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._transport = transport

    async def _post(self, texts: list[str]) -> list[list[float]]:
        """One batched call, with failures classified for the retry chain."""
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/v1/embeddings",
                    json={"model": self.model_id, "input": texts},
                    headers={"Authorization": f"Bearer {self._api_key}"},
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
        return [item["embedding"] for item in response.json()["data"]]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed indexed content. OpenAI has no document task prefix."""
        return await self._post(texts)

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query. OpenAI has no query task prefix."""
        return (await self._post([text]))[0]
