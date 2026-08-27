"""Voyage AI's embedding endpoint.

Voyage takes its task hint as an `input_type` request parameter rather than a text
prefix — unlike Ollama's `search_document:`/`search_query:` prefixes, the text
itself is sent unchanged and the distinction lives in the JSON body instead.
"""

import httpx

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError

TIMEOUT_SECONDS = 120.0


class VoyageEmbedder:
    """Embeddings from Voyage AI's hosted API."""

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

    async def _post(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        """One batched call, with failures classified for the retry chain."""
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS, transport=self._transport) as client:
            try:
                response = await client.post(
                    f"{self._base_url}/v1/embeddings",
                    json={"model": self.model_id, "input": texts, "input_type": input_type},
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
            except httpx.HTTPError as error:
                raise RetryableIngestionError(f"Embedding request failed: {error}") from error

        if response.status_code in (401, 403):
            raise TerminalIngestionError("Embedding provider rejected the credentials.")
        if response.status_code >= 400:
            raise RetryableIngestionError(f"Embedding provider returned {response.status_code}.")
        return [item["embedding"] for item in response.json()["data"]]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed indexed content, tagged with the document task hint."""
        return await self._post(texts, input_type="document")

    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query, tagged with the query task hint."""
        return (await self._post([text], input_type="query"))[0]
