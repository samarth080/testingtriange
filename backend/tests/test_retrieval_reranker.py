"""Unit tests for the reranker. No real Cohere calls — all mocked."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.retrieval import SearchResult
from app.retrieval.reranker import rerank


def make_result(chunk_id, text="text", rrf_score=0.5):
    return SearchResult(
        chunk_id=chunk_id, chunk_index=0, text=text,
        metadata={}, source_type="issue", source_id=chunk_id,
        rrf_score=rrf_score, source_title="", github_number=None,
    )


@pytest.mark.asyncio
async def test_rerank_empty_results_returns_empty():
    result = await rerank("query", [], top_n=5)
    assert result == []


@pytest.mark.asyncio
async def test_rerank_passthrough_no_api_key_slices_to_top_n():
    results = [make_result(i) for i in range(5)]
    reranked = await rerank("query", results, top_n=3, api_key="", provider="cohere")
    assert reranked == results[:3]


@pytest.mark.asyncio
async def test_rerank_passthrough_provider_slices_to_top_n():
    results = [make_result(i) for i in range(5)]
    reranked = await rerank("query", results, top_n=3, api_key="key", provider="passthrough")
    assert reranked == results[:3]


@pytest.mark.asyncio
async def test_rerank_cohere_reorders_by_relevance():
    results = [
        make_result(1, "less relevant"),
        make_result(2, "most relevant"),
        make_result(3, "somewhat relevant"),
    ]
    # Cohere says index 1 is best, then index 2
    mock_item_0 = MagicMock()
    mock_item_0.index = 1
    mock_item_1 = MagicMock()
    mock_item_1.index = 2

    mock_response = MagicMock()
    mock_response.results = [mock_item_0, mock_item_1]

    mock_client = AsyncMock()
    mock_client.rerank = AsyncMock(return_value=mock_response)

    with patch("app.retrieval.reranker.cohere") as mock_cohere:
        mock_cohere.AsyncClientV2.return_value = mock_client
        reranked = await rerank("query", results, top_n=2, api_key="test-key", provider="cohere")

    assert len(reranked) == 2
    assert reranked[0].chunk_id == 2  # "most relevant"
    assert reranked[1].chunk_id == 3  # "somewhat relevant"


@pytest.mark.asyncio
async def test_rerank_cohere_passes_correct_params():
    results = [make_result(i, f"doc {i}") for i in range(3)]

    mock_item = MagicMock()
    mock_item.index = 0
    mock_response = MagicMock()
    mock_response.results = [mock_item]

    mock_client = AsyncMock()
    mock_client.rerank = AsyncMock(return_value=mock_response)

    with patch("app.retrieval.reranker.cohere") as mock_cohere:
        mock_cohere.AsyncClientV2.return_value = mock_client
        await rerank("my query", results, top_n=1, api_key="key123", provider="cohere")

    mock_cohere.AsyncClientV2.assert_called_once_with(api_key="key123")
    mock_client.rerank.assert_called_once_with(
        model="rerank-english-v3.0",
        query="my query",
        documents=["doc 0", "doc 1", "doc 2"],
        top_n=1,
    )
