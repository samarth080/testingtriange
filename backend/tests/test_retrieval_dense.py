"""Dense search tests — mock the Qdrant client."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.indexing.qdrant_store import QdrantStore
from app.retrieval.dense import dense_search


def _make_qdrant_store(search_return_value):
    """Build a QdrantStore with a mocked _client.search."""
    store = object.__new__(QdrantStore)
    store._dim = 1024
    store._client = MagicMock()
    store._client.search = AsyncMock(return_value=search_return_value)
    return store


def _make_hit(point_id: str, score: float, payload: dict):
    hit = MagicMock()
    hit.id = point_id
    hit.score = score
    hit.payload = payload
    return hit


@pytest.mark.asyncio
async def test_dense_search_returns_ranked_list():
    payload = {
        "repo_id": 1, "source_type": "file", "source_id": 10,
        "chunk_index": 0, "text": "def foo(): pass",
    }
    store = _make_qdrant_store([_make_hit("uuid-1", 0.95, payload)])

    results = await dense_search(store, "code_chunks", [0.1] * 1024, repo_id=1, k=10)

    assert len(results) == 1
    pid, score, returned_payload = results[0]
    assert pid == "uuid-1"
    assert score == 0.95
    assert returned_payload == payload
    assert returned_payload["text"] == "def foo(): pass"  # pin payload is not corrupted


@pytest.mark.asyncio
async def test_dense_search_passes_repo_filter_to_qdrant():
    store = _make_qdrant_store([])
    await dense_search(store, "code_chunks", [0.0] * 1024, repo_id=42, k=5)

    call_kwargs = store._client.search.call_args.kwargs
    filter_conditions = call_kwargs["query_filter"].must
    repo_condition = next(
        (c for c in filter_conditions if getattr(c, "key", None) == "repo_id"), None
    )
    assert repo_condition is not None, "No repo_id filter condition found"
    assert repo_condition.match.value == 42, f"Expected repo_id=42, got {repo_condition.match.value}"


@pytest.mark.asyncio
async def test_dense_search_empty_results():
    store = _make_qdrant_store([])
    results = await dense_search(store, "code_chunks", [0.1] * 1024, repo_id=1, k=10)
    assert results == []
