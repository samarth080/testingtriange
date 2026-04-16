"""
Integration tests for run_triage_pipeline.
All 4 pipeline steps (retrieve, graph_expand, rerank, triage_with_llm) are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.retrieval import SearchResult
from app.triage.pipeline import run_triage_pipeline
from app.triage.schemas import TriageOutput


def make_search_result(chunk_id: int = 1) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        chunk_index=0,
        text="some relevant text",
        metadata={},
        source_type="issue",
        source_id=chunk_id,
        rrf_score=0.9,
        source_title="Some issue title",
        github_number=chunk_id,
    )


def make_mock_issue(body: str | None = "Some body text"):
    issue = MagicMock()
    issue.id = 5
    issue.github_number = 10
    issue.title = "Fix memory leak"
    issue.body = body
    issue.labels = ["bug"]
    return issue


TRIAGE_OUTPUT = TriageOutput(confidence="high", reasoning="ok")


@pytest.mark.asyncio
async def test_pipeline_calls_all_steps_in_order():
    """Each step should be called exactly once with the right key arguments."""
    mock_session = AsyncMock()
    mock_embedder = MagicMock()
    mock_qdrant = MagicMock()
    mock_cfg = MagicMock()
    mock_cfg.cohere_api_key = "cohere-key"
    mock_cfg.reranker_provider = "cohere"
    mock_cfg.anthropic_api_key = "anthropic-key"

    mock_issue = make_mock_issue()

    retrieved = [make_search_result(1), make_search_result(2)]
    expanded = retrieved + [make_search_result(3)]
    reranked = expanded[:2]

    with (
        patch("app.triage.pipeline.retrieve", new_callable=AsyncMock, return_value=retrieved) as mock_retrieve,
        patch("app.triage.pipeline.graph_expand", new_callable=AsyncMock, return_value=expanded) as mock_expand,
        patch("app.triage.pipeline.rerank", new_callable=AsyncMock, return_value=reranked) as mock_rerank,
        patch("app.triage.pipeline.triage_with_llm", new_callable=AsyncMock, return_value=TRIAGE_OUTPUT) as mock_llm,
    ):
        output, latency_ms = await run_triage_pipeline(
            session=mock_session,
            repo_id=1,
            issue=mock_issue,
            embedder=mock_embedder,
            qdrant=mock_qdrant,
            cfg=mock_cfg,
        )

    mock_retrieve.assert_awaited_once()
    retrieve_call_kwargs = mock_retrieve.call_args.kwargs
    assert retrieve_call_kwargs["repo_id"] == 1
    assert retrieve_call_kwargs["session"] is mock_session

    mock_expand.assert_awaited_once()
    expand_call_kwargs = mock_expand.call_args.kwargs
    assert expand_call_kwargs["results"] is retrieved
    assert expand_call_kwargs["repo_id"] == 1

    mock_rerank.assert_awaited_once()
    rerank_call_kwargs = mock_rerank.call_args.kwargs
    assert rerank_call_kwargs["results"] is expanded

    mock_llm.assert_awaited_once()
    llm_call_kwargs = mock_llm.call_args.kwargs
    assert llm_call_kwargs["title"] == mock_issue.title
    assert llm_call_kwargs["context_results"] is reranked


@pytest.mark.asyncio
async def test_pipeline_returns_triage_output_and_latency():
    """Return type should be (TriageOutput, int) with latency_ms >= 0."""
    mock_issue = make_mock_issue()

    with (
        patch("app.triage.pipeline.retrieve", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.graph_expand", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.rerank", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.triage_with_llm", new_callable=AsyncMock, return_value=TRIAGE_OUTPUT),
    ):
        result = await run_triage_pipeline(
            session=AsyncMock(),
            repo_id=1,
            issue=mock_issue,
            embedder=MagicMock(),
            qdrant=MagicMock(),
            cfg=MagicMock(),
        )

    output, latency_ms = result
    assert isinstance(output, TriageOutput)
    assert isinstance(latency_ms, int)
    assert latency_ms >= 0


@pytest.mark.asyncio
async def test_pipeline_query_construction_when_body_is_none():
    """When issue.body is None, query passed to retrieve should be title + newline only."""
    mock_issue = make_mock_issue(body=None)

    captured_query = {}

    async def fake_retrieve(**kwargs):
        captured_query["query"] = kwargs["query"]
        return []

    with (
        patch("app.triage.pipeline.retrieve", side_effect=fake_retrieve),
        patch("app.triage.pipeline.graph_expand", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.rerank", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.triage_with_llm", new_callable=AsyncMock, return_value=TRIAGE_OUTPUT),
    ):
        await run_triage_pipeline(
            session=AsyncMock(),
            repo_id=1,
            issue=mock_issue,
            embedder=MagicMock(),
            qdrant=MagicMock(),
            cfg=MagicMock(),
        )

    expected_query = f"{mock_issue.title}\n"
    assert captured_query["query"] == expected_query
