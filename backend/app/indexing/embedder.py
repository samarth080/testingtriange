"""
Provider-agnostic text embedder.

Supported providers:
- VOYAGE: voyage-code-3 (1024-dim), best for code
- OPENAI: text-embedding-3-large (1536-dim), general purpose

Provider is selected at construction time. Call embed_batch() to get vectors.
Large inputs are automatically split into batches to stay within API limits.
"""
import logging
from enum import Enum

import voyageai
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 100


class EmbeddingProvider(str, Enum):
    VOYAGE = "voyage"
    OPENAI = "openai"


_PROVIDER_CONFIG = {
    EmbeddingProvider.VOYAGE: {
        "model": "voyage-code-3",
        "dimension": 1024,
    },
    EmbeddingProvider.OPENAI: {
        "model": "text-embedding-3-large",
        "dimension": 1536,
    },
}


class Embedder:
    """
    Async embedder that calls the configured provider API.

    Usage:
        embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="...")
        vectors = await embedder.embed_batch(["text one", "text two"])
    """

    def __init__(self, provider: EmbeddingProvider, api_key: str) -> None:
        self._provider = provider
        self._config = _PROVIDER_CONFIG[provider]

        if provider == EmbeddingProvider.VOYAGE:
            self._voyage_client = voyageai.AsyncClient(api_key=api_key)
        elif provider == EmbeddingProvider.OPENAI:
            self._openai_client = AsyncOpenAI(api_key=api_key)

    @property
    def dimension(self) -> int:
        """Output vector dimension for this provider."""
        return self._config["dimension"]

    @property
    def model(self) -> str:
        """Model name used for embedding (stored in Postgres chunks.embedding_model)."""
        return self._config["model"]

    async def embed_batch(
        self, texts: list[str], batch_size: int = _DEFAULT_BATCH_SIZE
    ) -> list[list[float]]:
        """
        Embed a list of texts, batching API calls to stay within provider limits.

        Args:
            texts:      List of strings to embed. Empty list returns [].
            batch_size: Max texts per API call.

        Returns:
            List of float vectors, same length and order as input texts.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await self._embed_one_batch(batch)
            all_embeddings.extend(embeddings)
        return all_embeddings

    async def _embed_one_batch(self, texts: list[str]) -> list[list[float]]:
        if self._provider == EmbeddingProvider.VOYAGE:
            result = await self._voyage_client.embed(
                texts,
                model=self._config["model"],
                input_type="document",
            )
            return result.embeddings

        if self._provider == EmbeddingProvider.OPENAI:
            response = await self._openai_client.embeddings.create(
                input=texts,
                model=self._config["model"],
            )
            return [item.embedding for item in response.data]

        raise ValueError(f"Unknown provider: {self._provider}")


def embedder_from_settings() -> "Embedder":
    """
    Construct an Embedder from app settings.

    Priority: voyage_api_key → openai_api_key → raises RuntimeError.
    """
    from app.core.config import settings

    if settings.voyage_api_key:
        return Embedder(provider=EmbeddingProvider.VOYAGE, api_key=settings.voyage_api_key)
    if settings.openai_api_key:
        return Embedder(provider=EmbeddingProvider.OPENAI, api_key=settings.openai_api_key)
    raise RuntimeError(
        "No embedding API key configured. Set VOYAGE_API_KEY or OPENAI_API_KEY in .env"
    )
