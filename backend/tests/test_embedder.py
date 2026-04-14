"""
Embedder unit tests — all API calls are mocked.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.indexing.embedder import Embedder, EmbeddingProvider


@pytest.mark.asyncio
async def test_embedder_voyage_calls_api():
    fake_result = MagicMock()
    fake_result.embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    with patch("app.indexing.embedder.voyageai.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.embed = AsyncMock(return_value=fake_result)

        embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="test-key")
        result = await embedder.embed_batch(["hello", "world"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    instance.embed.assert_called_once()


@pytest.mark.asyncio
async def test_embedder_openai_calls_api():
    fake_item_1 = MagicMock()
    fake_item_1.embedding = [0.7, 0.8, 0.9]
    fake_item_2 = MagicMock()
    fake_item_2.embedding = [0.1, 0.2, 0.3]

    fake_response = MagicMock()
    fake_response.data = [fake_item_1, fake_item_2]

    with patch("app.indexing.embedder.AsyncOpenAI") as MockOpenAI:
        instance = MockOpenAI.return_value
        instance.embeddings = MagicMock()
        instance.embeddings.create = AsyncMock(return_value=fake_response)

        embedder = Embedder(provider=EmbeddingProvider.OPENAI, api_key="test-key")
        result = await embedder.embed_batch(["hello", "world"])

    assert result == [[0.7, 0.8, 0.9], [0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_embedder_batches_large_input():
    """embed_batch should split texts into batches of batch_size."""
    fake_result = MagicMock()
    fake_result.embeddings = [[float(i)] for i in range(10)]

    with patch("app.indexing.embedder.voyageai.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.embed = AsyncMock(return_value=fake_result)

        embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="test-key")
        # 25 texts with batch_size=10 → 3 API calls
        texts = [f"text {i}" for i in range(25)]
        await embedder.embed_batch(texts, batch_size=10)

    assert instance.embed.call_count == 3


@pytest.mark.asyncio
async def test_embedder_empty_input_returns_empty():
    embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="key")
    result = await embedder.embed_batch([])
    assert result == []


def test_embedder_dimension_voyage():
    embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="key")
    assert embedder.dimension == 1024


def test_embedder_dimension_openai():
    embedder = Embedder(provider=EmbeddingProvider.OPENAI, api_key="key")
    assert embedder.dimension == 1536
