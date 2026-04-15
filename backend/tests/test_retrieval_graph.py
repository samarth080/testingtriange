"""Unit tests for graph expansion. No DB, no network — pure mock."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from app.retrieval import SearchResult
from app.retrieval.graph import graph_expand


def make_result(chunk_id, source_type="issue", source_id=10):
    return SearchResult(
        chunk_id=chunk_id, chunk_index=0, text=f"text {chunk_id}",
        metadata={}, source_type=source_type, source_id=source_id,
        rrf_score=0.9, source_title="Title", github_number=42,
    )


def make_exec(items):
    """Return a mock that behaves like an AsyncSession.execute() result."""
    m = MagicMock()
    m.scalars.return_value.all.return_value = items
    return m


@pytest.mark.asyncio
async def test_graph_expand_empty_results_returns_empty():
    session = AsyncMock()
    result = await graph_expand(session, [], repo_id=1)
    assert result == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_graph_expand_no_relationships_returns_original():
    session = AsyncMock()
    # Relationships query returns empty list — early return, no chunk query
    session.execute.return_value = make_exec([])
    results = [make_result(1)]
    expanded = await graph_expand(session, results, repo_id=1)
    assert expanded == results


@pytest.mark.asyncio
async def test_graph_expand_adds_neighbor_pr_chunk():
    from app.models.orm import Chunk, PullRequest, Relationship

    rel = MagicMock(spec=Relationship)
    rel.target_type = "pull_request"
    rel.target_id = 99

    neighbor_chunk = MagicMock(spec=Chunk)
    neighbor_chunk.id = 50
    neighbor_chunk.chunk_index = 0
    neighbor_chunk.text = "PR neighbor text"
    neighbor_chunk.chunk_metadata = {}
    neighbor_chunk.source_type = "pull_request"
    neighbor_chunk.source_id = 99

    pr_entity = MagicMock(spec=PullRequest)
    pr_entity.id = 99
    pr_entity.title = "Fix memory leak"
    pr_entity.github_number = 77

    # execute calls: 1) relationships 2) neighbor chunks 3) PRs
    session = AsyncMock()
    session.execute.side_effect = [
        make_exec([rel]),
        make_exec([neighbor_chunk]),
        make_exec([pr_entity]),
    ]

    results = [make_result(1, "issue", 10)]
    expanded = await graph_expand(session, results, repo_id=1)

    assert len(expanded) == 2
    neighbor = expanded[1]
    assert neighbor.chunk_id == 50
    assert neighbor.rrf_score == 0.0
    assert neighbor.source_type == "pull_request"
    assert neighbor.source_title == "Fix memory leak"
    assert neighbor.github_number == 77


@pytest.mark.asyncio
async def test_graph_expand_deduplicates_already_seen_chunk():
    from app.models.orm import Chunk, Relationship

    rel = MagicMock(spec=Relationship)
    rel.target_type = "pull_request"
    rel.target_id = 99

    # Neighbor chunk has same id as original result — should be skipped
    neighbor_chunk = MagicMock(spec=Chunk)
    neighbor_chunk.id = 1  # already in seen_chunk_ids
    neighbor_chunk.chunk_index = 0
    neighbor_chunk.text = "dup"
    neighbor_chunk.chunk_metadata = {}
    neighbor_chunk.source_type = "pull_request"
    neighbor_chunk.source_id = 99

    # 2 execute calls: relationships + chunks; no entity batch (all deduped)
    session = AsyncMock()
    session.execute.side_effect = [
        make_exec([rel]),
        make_exec([neighbor_chunk]),
    ]

    results = [make_result(1, "issue", 10)]
    expanded = await graph_expand(session, results, repo_id=1)
    assert len(expanded) == 1  # no new chunk added


@pytest.mark.asyncio
async def test_graph_expand_respects_max_neighbors():
    from app.models.orm import Chunk, Relationship

    rel = MagicMock(spec=Relationship)
    rel.target_type = "issue"
    rel.target_id = 200

    chunks = []
    for i in range(5):
        c = MagicMock(spec=Chunk)
        c.id = 100 + i
        c.chunk_index = i
        c.text = f"chunk {i}"
        c.chunk_metadata = {}
        c.source_type = "issue"
        c.source_id = 200
        chunks.append(c)

    # execute calls: 1) relationships 2) chunks 3) issues (source_id=200)
    session = AsyncMock()
    session.execute.side_effect = [
        make_exec([rel]),
        make_exec(chunks),
        make_exec([]),  # issue entity not found — title falls back to ""
    ]

    results = [make_result(1, "issue", 10)]
    expanded = await graph_expand(session, results, repo_id=1, max_neighbors=2)
    assert len(expanded) == 3  # 1 original + 2 neighbors (capped)
