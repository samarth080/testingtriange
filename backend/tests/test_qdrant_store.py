"""
Qdrant store unit tests — AsyncQdrantClient is fully mocked.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.indexing.qdrant_store import QdrantStore, CODE_COLLECTION, DISCUSSION_COLLECTION


@pytest.fixture
def mock_qdrant_client():
    with patch("app.indexing.qdrant_store.AsyncQdrantClient") as MockClient:
        instance = MockClient.return_value
        instance.collection_exists = AsyncMock(return_value=False)
        instance.create_collection = AsyncMock()
        instance.upsert = AsyncMock()
        instance.delete = AsyncMock()
        yield instance


@pytest.mark.asyncio
async def test_ensure_collections_creates_if_missing(mock_qdrant_client):
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    await store.ensure_collections()

    assert mock_qdrant_client.create_collection.call_count == 2
    call_names = [
        call.kwargs["collection_name"]
        for call in mock_qdrant_client.create_collection.call_args_list
    ]
    assert CODE_COLLECTION in call_names
    assert DISCUSSION_COLLECTION in call_names


@pytest.mark.asyncio
async def test_ensure_collections_skips_existing(mock_qdrant_client):
    mock_qdrant_client.collection_exists = AsyncMock(return_value=True)
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    await store.ensure_collections()
    mock_qdrant_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_chunks_calls_qdrant(mock_qdrant_client):
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    points = [
        {"id": "uuid-1", "vector": [0.1] * 1024, "payload": {"text": "hello"}},
        {"id": "uuid-2", "vector": [0.2] * 1024, "payload": {"text": "world"}},
    ]
    await store.upsert_points(CODE_COLLECTION, points)
    mock_qdrant_client.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_delete_repo_points_calls_qdrant(mock_qdrant_client):
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    await store.delete_repo_points(repo_id=42)
    assert mock_qdrant_client.delete.call_count == 2  # once per collection
