"""
Ingestion task tests — verify task routing and status updates.
We mock the fetchers so no real GitHub API calls are made.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.ingestion_tasks import _async_backfill_repo


@pytest.mark.asyncio
async def test_async_backfill_repo_returns_summary():
    """
    _async_backfill_repo should return a dict with counts for all 4 entity types.
    We mock the DB session, GitHub token, and all four fetchers.
    """
    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_repo.owner = "testowner"
    mock_repo.name = "testrepo"
    mock_repo.installation_id = 111
    mock_repo.backfill_status = "running"

    # Mock the scalar result for the DB repo lookup
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar_one_or_none.return_value = mock_repo

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_scalar_result)
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_cm = MagicMock()
    mock_session_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session_cm.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.workers.ingestion_tasks.AsyncSessionLocal", return_value=mock_session_cm),
        patch("app.workers.ingestion_tasks.get_installation_token", new_callable=AsyncMock, return_value="tok"),
        patch("app.workers.ingestion_tasks.GitHubClient"),
        patch("app.workers.ingestion_tasks._get_default_branch", new_callable=AsyncMock, return_value="main"),
        patch("app.workers.ingestion_tasks.fetch_and_store_issues", new_callable=AsyncMock, return_value=5),
        patch("app.workers.ingestion_tasks.fetch_and_store_pull_requests", new_callable=AsyncMock, return_value=3),
        patch("app.workers.ingestion_tasks.fetch_and_store_commits", new_callable=AsyncMock, return_value=10),
        patch("app.workers.ingestion_tasks.fetch_and_store_files", new_callable=AsyncMock, return_value=20),
    ):
        result = await _async_backfill_repo(repo_id=1)

    assert result["issues"] == 5
    assert result["prs"] == 3
    assert result["commits"] == 10
    assert result["files"] == 20
    assert result["repo_id"] == 1
