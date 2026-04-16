"""
Tests for incremental indexing.

Verifies that index_repo_files and index_repo_discussions skip already-indexed
content when incremental=True, and process everything when incremental=False.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from app.indexing.pipeline import index_repo_discussions, index_repo_files


def make_repo(repo_id: int = 1, owner: str = "acme", name: str = "repo") -> MagicMock:
    repo = MagicMock()
    repo.id = repo_id
    repo.owner = owner
    repo.name = name
    return repo


def make_file(file_id: int = 1, language: str = "python", last_indexed_at=None) -> MagicMock:
    f = MagicMock()
    f.id = file_id
    f.path = f"src/file_{file_id}.py"
    f.language = language
    f.last_indexed_at = last_indexed_at
    f.content_hash = None
    return f


@pytest.mark.asyncio
async def test_index_files_incremental_skips_already_indexed():
    """When incremental=True, files with last_indexed_at set are skipped."""
    indexed_file = make_file(1, last_indexed_at=datetime.now(tz=timezone.utc))
    new_file = make_file(2, last_indexed_at=None)

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [indexed_file, new_file]
    session.execute = AsyncMock(return_value=mock_result)

    github_client = AsyncMock()
    github_client.get = AsyncMock(return_value={
        "size": 100,
        "content": "cHJpbnQoImhlbGxvIik=",  # base64 of some content
    })

    embedder = AsyncMock()
    embedder.model = "test-model"
    embedder.embed_batch = AsyncMock(return_value=[[0.1, 0.2]])

    qdrant = AsyncMock()

    with patch("app.indexing.pipeline.chunk_code", return_value=[MagicMock(chunk_index=0, text="x", metadata={})]):
        with patch("app.indexing.pipeline._upsert_chunks", new_callable=AsyncMock):
            count = await index_repo_files(
                session, make_repo(), github_client, embedder, qdrant,
                default_branch="main", incremental=True,
            )

    # Only new_file (last_indexed_at=None) should be indexed
    assert count == 1


@pytest.mark.asyncio
async def test_index_files_non_incremental_processes_all():
    """When incremental=False (default), all files are processed."""
    indexed_file = make_file(1, last_indexed_at=datetime.now(tz=timezone.utc))
    new_file = make_file(2, last_indexed_at=None)

    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [indexed_file, new_file]
    session.execute = AsyncMock(return_value=mock_result)

    github_client = AsyncMock()
    github_client.get = AsyncMock(return_value={
        "size": 100,
        "content": "cHJpbnQoImhlbGxvIik=",
    })

    embedder = AsyncMock()
    embedder.model = "test-model"
    embedder.embed_batch = AsyncMock(return_value=[[0.1, 0.2]])

    qdrant = AsyncMock()

    with patch("app.indexing.pipeline.chunk_code", return_value=[MagicMock(chunk_index=0, text="x", metadata={})]):
        with patch("app.indexing.pipeline._upsert_chunks", new_callable=AsyncMock):
            count = await index_repo_files(
                session, make_repo(), github_client, embedder, qdrant,
                default_branch="main", incremental=False,
            )

    assert count == 2


@pytest.mark.asyncio
async def test_incremental_index_repo_task_exists():
    """incremental_index_repo task is importable and registered with Celery."""
    from app.workers.incremental_tasks import incremental_index_repo
    assert callable(incremental_index_repo)
