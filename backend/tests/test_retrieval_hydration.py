"""Hydration tests — mock AsyncSession; verify SearchResult fields are populated."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.retrieval.hydration import hydrate
from app.retrieval import SearchResult


def _make_chunk(qdrant_point_id, source_type, source_id,
                chunk_id=1, chunk_index=0, text="chunk text", metadata=None):
    c = MagicMock()
    c.id = chunk_id
    c.qdrant_point_id = qdrant_point_id
    c.chunk_index = chunk_index
    c.text = text
    c.chunk_metadata = metadata or {}
    c.source_type = source_type
    c.source_id = source_id
    return c


def _make_issue(issue_id, title, github_number):
    i = MagicMock()
    i.id = issue_id
    i.title = title
    i.github_number = github_number
    return i


def _make_pr(pr_id, title, github_number):
    p = MagicMock()
    p.id = pr_id
    p.title = title
    p.github_number = github_number
    return p


def _make_file(file_id, path):
    f = MagicMock()
    f.id = file_id
    f.path = path
    return f


def _session_with_execute_returns(*scalars_results):
    """Build a mock session whose sequential execute() calls return different rows."""
    session = AsyncMock()
    side_effects = []
    for rows in scalars_results:
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        side_effects.append(result)
    session.execute.side_effect = side_effects
    return session


@pytest.mark.asyncio
async def test_hydrate_issue_chunk():
    chunk = _make_chunk("uuid-1", "issue", 10, chunk_id=1, text="Memory leak")
    issue = _make_issue(10, "Memory leak in worker", 42)

    # execute calls: chunks → issues
    session = _session_with_execute_returns([chunk], [issue])

    results = await hydrate(session, [("uuid-1", 0.016)])

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.source_type == "issue"
    assert r.source_title == "Memory leak in worker"
    assert r.github_number == 42
    assert r.rrf_score == 0.016
    assert r.text == "Memory leak"


@pytest.mark.asyncio
async def test_hydrate_pull_request_chunk():
    chunk = _make_chunk("uuid-2", "pull_request", 20, chunk_id=2)
    pr = _make_pr(20, "Add rate limiting", 7)

    session = _session_with_execute_returns([chunk], [pr])

    results = await hydrate(session, [("uuid-2", 0.012)])

    r = results[0]
    assert r.source_type == "pull_request"
    assert r.source_title == "Add rate limiting"
    assert r.github_number == 7


@pytest.mark.asyncio
async def test_hydrate_file_chunk():
    chunk = _make_chunk("uuid-3", "file", 30, chunk_id=3)
    file_ = _make_file(30, "src/worker.py")

    session = _session_with_execute_returns([chunk], [file_])

    results = await hydrate(session, [("uuid-3", 0.010)])

    r = results[0]
    assert r.source_type == "file"
    assert r.source_title == "src/worker.py"
    assert r.github_number is None


@pytest.mark.asyncio
async def test_hydrate_preserves_rrf_order():
    chunk1 = _make_chunk("uuid-a", "issue", 1, chunk_id=1)
    chunk2 = _make_chunk("uuid-b", "issue", 2, chunk_id=2)
    issue1 = _make_issue(1, "Issue A", 10)
    issue2 = _make_issue(2, "Issue B", 11)

    session = _session_with_execute_returns([chunk1, chunk2], [issue1, issue2])

    results = await hydrate(session, [("uuid-a", 0.020), ("uuid-b", 0.010)])

    assert results[0].rrf_score == 0.020
    assert results[1].rrf_score == 0.010


@pytest.mark.asyncio
async def test_hydrate_empty_ranked():
    session = AsyncMock()
    results = await hydrate(session, [])
    assert results == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_hydrate_skips_missing_chunks():
    """Stale point IDs (no matching chunk in Postgres) are silently skipped."""
    session = _session_with_execute_returns([])  # chunks query returns nothing
    results = await hydrate(session, [("stale-uuid", 0.015)])
    assert results == []
