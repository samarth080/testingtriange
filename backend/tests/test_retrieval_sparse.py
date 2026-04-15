"""Sparse search tests — mock the AsyncSession."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from app.retrieval.sparse import sparse_search


def _make_session(rows):
    """Build a mock AsyncSession whose execute() returns rows."""
    row_iter = iter(rows)
    result = MagicMock()
    result.__iter__ = MagicMock(return_value=row_iter)
    session = AsyncMock()
    session.execute.return_value = result
    return session


def _make_row(qdrant_point_id: str, score: float):
    row = MagicMock()
    row.qdrant_point_id = qdrant_point_id
    row.score = score
    return row


@pytest.mark.asyncio
async def test_sparse_search_returns_ranked_list():
    session = _make_session([_make_row("uuid-1", 0.8), _make_row("uuid-2", 0.5)])
    hits = await sparse_search(session, repo_id=1, query="memory leak", k=10)
    assert hits == [("uuid-1", 0.8), ("uuid-2", 0.5)]


@pytest.mark.asyncio
async def test_sparse_search_empty_query_skips_db():
    session = AsyncMock()
    hits = await sparse_search(session, repo_id=1, query="   ", k=10)
    assert hits == []
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sparse_search_no_matches_returns_empty():
    session = _make_session([])
    hits = await sparse_search(session, repo_id=1, query="xyznonexistent", k=10)
    assert hits == []


@pytest.mark.asyncio
async def test_sparse_search_score_is_float():
    """ts_rank can return Decimal on some Postgres drivers — ensure float coercion."""
    from decimal import Decimal
    row = _make_row("uuid-1", Decimal("0.075990"))
    session = _make_session([row])
    hits = await sparse_search(session, repo_id=1, query="leak", k=5)
    assert isinstance(hits[0][1], float)


@pytest.mark.asyncio
async def test_sparse_search_passes_correct_params_to_db():
    session = _make_session([])
    await sparse_search(session, repo_id=7, query="auth bug", k=25)
    session.execute.assert_called_once()
    call_args = session.execute.call_args
    params = call_args[0][1]  # second positional arg is the params dict
    assert params["repo_id"] == 7
    assert params["query"] == "auth bug"
    assert params["k"] == 25
