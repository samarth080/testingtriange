"""
Integration-style test for POST /search.
Mocks retrieve() so no real DB or Qdrant is needed.
"""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.retrieval import SearchResult


FAKE_RESULT = SearchResult(
    chunk_id=1,
    chunk_index=0,
    text="def foo(): pass",
    metadata={"language": "python", "symbol": "foo"},
    source_type="file",
    source_id=10,
    rrf_score=0.016,
    source_title="src/foo.py",
    github_number=None,
)


@pytest.mark.asyncio
async def test_search_returns_results():
    with patch("app.api.search.retrieve", new=AsyncMock(return_value=[FAKE_RESULT])), \
         patch("app.api.search.embedder_from_settings", return_value=MagicMock(dimension=1024)), \
         patch("app.api.search.QdrantStore", return_value=MagicMock()):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/search",
                json={"repo_id": 1, "query": "foo function", "k": 5},
            )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source_type"] == "file"
    assert data[0]["source_title"] == "src/foo.py"
    assert data[0]["github_number"] is None
    assert data[0]["rrf_score"] == pytest.approx(0.016)


@pytest.mark.asyncio
async def test_search_missing_query_returns_422():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post("/search", json={"repo_id": 1})

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_search_empty_results():
    with patch("app.api.search.retrieve", new=AsyncMock(return_value=[])), \
         patch("app.api.search.embedder_from_settings", return_value=MagicMock(dimension=1024)), \
         patch("app.api.search.QdrantStore", return_value=MagicMock()):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/search",
                json={"repo_id": 1, "query": "nothing matches", "k": 10},
            )

    assert resp.status_code == 200
    assert resp.json() == []
