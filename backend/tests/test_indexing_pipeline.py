"""
Indexing pipeline integration tests.

Uses real Postgres (NullPool — same pattern as test_fetchers.py).
Embedder and QdrantStore are mocked — we test chunking + DB logic.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.indexing.qdrant_store import CODE_COLLECTION, DISCUSSION_COLLECTION
from app.models.orm import Chunk, File, Issue, PullRequest, Repo

_test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
_TestSessionLocal = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session():
    async with _TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_repo(db_session: AsyncSession):
    stmt = (
        pg_insert(Repo)
        .values(github_id=888888, owner="pipelineowner", name="pipelinerepo", installation_id=222)
        .on_conflict_do_update(
            constraint="uq_repos_github_id",
            set_={"owner": "pipelineowner"},
        )
        .returning(Repo.id)
    )
    result = await db_session.execute(stmt)
    repo_id = result.scalar_one()
    repo = await db_session.get(Repo, repo_id)
    yield repo
    await db_session.execute(delete(Chunk).where(Chunk.repo_id == repo.id))
    await db_session.execute(delete(File).where(File.repo_id == repo.id))
    await db_session.execute(delete(Issue).where(Issue.repo_id == repo.id))
    await db_session.execute(delete(PullRequest).where(PullRequest.repo_id == repo.id))
    await db_session.execute(delete(Repo).where(Repo.id == repo.id))
    await db_session.commit()


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.model = "voyage-code-3"
    embedder.dimension = 1024

    async def embed_batch(texts, batch_size=100):
        return [[0.1] * 1024 for _ in texts]

    embedder.embed_batch = embed_batch
    return embedder


@pytest.fixture
def mock_qdrant():
    store = MagicMock()
    store.upsert_points = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_index_issues_creates_chunks(db_session, test_repo, mock_embedder, mock_qdrant):
    # Insert a test issue
    stmt = pg_insert(Issue).values(
        repo_id=test_repo.id,
        github_number=1,
        title="Fix memory leak",
        body="The server leaks on startup.\n\n## Steps\n\nRun it.",
        state="open",
        author="alice",
        labels=["bug"],
        created_at=datetime.now(tz=timezone.utc),
    ).on_conflict_do_nothing(constraint="uq_issues_repo_number")
    await db_session.execute(stmt)
    await db_session.commit()

    from app.indexing.pipeline import index_repo_discussions
    await index_repo_discussions(db_session, test_repo, mock_embedder, mock_qdrant)

    result = await db_session.execute(
        select(Chunk).where(Chunk.repo_id == test_repo.id, Chunk.source_type == "issue")
    )
    chunks = result.scalars().all()
    assert len(chunks) >= 1
    assert chunks[0].embedding_model == "voyage-code-3"
    assert chunks[0].qdrant_collection == DISCUSSION_COLLECTION
    assert chunks[0].qdrant_point_id is not None

    mock_qdrant.upsert_points.assert_called()


@pytest.mark.asyncio
async def test_index_files_creates_chunks(db_session, test_repo, mock_embedder, mock_qdrant):
    import base64

    # Insert a test file stub
    stmt = pg_insert(File).values(
        repo_id=test_repo.id,
        path="src/app.py",
        language="python",
        content_hash=None,
        last_indexed_at=None,
    ).on_conflict_do_nothing(constraint="uq_files_repo_path")
    await db_session.execute(stmt)
    await db_session.commit()

    python_source = "def hello():\n    return 'world'\n"

    mock_github_client = MagicMock()
    mock_github_client.get = AsyncMock(return_value={
        "content": base64.b64encode(python_source.encode()).decode(),
        "encoding": "base64",
        "size": len(python_source),
    })

    from app.indexing.pipeline import index_repo_files
    await index_repo_files(
        db_session, test_repo, mock_github_client, mock_embedder, mock_qdrant,
        default_branch="main",
    )

    result = await db_session.execute(
        select(Chunk).where(Chunk.repo_id == test_repo.id, Chunk.source_type == "file")
    )
    chunks = result.scalars().all()
    assert len(chunks) >= 1
    assert chunks[0].qdrant_collection == CODE_COLLECTION

    mock_qdrant.upsert_points.assert_called()


@pytest.mark.asyncio
async def test_index_discussions_handles_none_body(db_session, test_repo, mock_embedder, mock_qdrant):
    stmt = pg_insert(Issue).values(
        repo_id=test_repo.id,
        github_number=2,
        title="No body issue",
        body=None,
        state="open",
        author="bob",
        labels=[],
        created_at=datetime.now(tz=timezone.utc),
    ).on_conflict_do_nothing(constraint="uq_issues_repo_number")
    await db_session.execute(stmt)
    await db_session.commit()

    from app.indexing.pipeline import index_repo_discussions
    await index_repo_discussions(db_session, test_repo, mock_embedder, mock_qdrant)

    result = await db_session.execute(
        select(Chunk).where(Chunk.repo_id == test_repo.id, Chunk.source_type == "issue")
    )
    chunks = result.scalars().all()
    # Even with no body, at least one chunk must be created
    assert len(chunks) >= 1
