"""
Fetcher unit tests.

Strategy: replace GitHubClient with a MockGitHubClient that yields
pre-canned data. Use a real async Postgres session (same DB as dev)
so upsert logic is tested end-to-end without mocking SQLAlchemy.
"""
import asyncio
from datetime import datetime, timezone
from typing import Any
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.ingestion.fetchers import fetch_and_store_issues
from app.models.orm import File, Issue, PullRequest, Relationship, Repo

# Use NullPool so connections are never reused across event loops (one per test).
# This prevents asyncpg "attached to a different loop" errors in function-scoped tests.
_test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
_TestSessionLocal = async_sessionmaker(_test_engine, expire_on_commit=False)


# ── Helpers ─────────────────────────────────────────────────────────────────

class MockGitHubClient:
    """Minimal stub that replaces GitHubClient in fetcher tests."""

    def __init__(self, issues: list[dict] | None = None, prs: list[dict] | None = None):
        self._issues = issues or []
        self._prs = prs or []

    async def paginate(self, path: str, params: dict | None = None) -> AsyncGenerator[dict, None]:
        if "/issues" in path and "/pulls" not in path:
            for item in self._issues:
                yield item
        elif "/pulls" in path and "/files" not in path:
            for item in self._prs:
                yield item
        else:
            return

    async def get(self, path: str) -> dict:
        return {}


MOCK_ISSUE = {
    "number": 42,
    "title": "Fix memory leak",
    "body": "It leaks on every request",
    "state": "open",
    "user": {"login": "alice"},
    "labels": [{"name": "bug"}, {"name": "performance"}],
    "created_at": "2025-01-15T10:00:00Z",
    "closed_at": None,
}


@pytest_asyncio.fixture
async def db_session():
    async with _TestSessionLocal() as session:
        yield session
        await session.rollback()  # Clean up after each test


@pytest_asyncio.fixture
async def test_repo(db_session: AsyncSession):
    """Insert a temporary Repo row for tests, delete after."""
    repo = Repo(
        github_id=999999,
        owner="testowner",
        name="testrepo",
        installation_id=111,
        backfill_status="running",
    )
    db_session.add(repo)
    await db_session.flush()
    yield repo
    await db_session.execute(delete(Relationship).where(Relationship.repo_id == repo.id))
    await db_session.execute(delete(PullRequest).where(PullRequest.repo_id == repo.id))
    await db_session.execute(delete(File).where(File.repo_id == repo.id))
    await db_session.execute(delete(Issue).where(Issue.repo_id == repo.id))
    await db_session.execute(delete(Repo).where(Repo.id == repo.id))
    await db_session.commit()


# ── Tests ────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fetch_issues_stores_issue(db_session: AsyncSession, test_repo: Repo):
    """fetch_and_store_issues upserts issues and skips pull_requests."""
    client = MockGitHubClient(issues=[MOCK_ISSUE])

    count = await fetch_and_store_issues(db_session, test_repo, client)

    assert count == 1
    result = await db_session.execute(
        select(Issue).where(Issue.repo_id == test_repo.id, Issue.github_number == 42)
    )
    issue = result.scalar_one()
    assert issue.title == "Fix memory leak"
    assert issue.state == "open"
    assert issue.author == "alice"
    assert issue.labels == ["bug", "performance"]


@pytest.mark.asyncio
async def test_fetch_issues_skips_pull_requests(db_session: AsyncSession, test_repo: Repo):
    """Items with a 'pull_request' key are PRs — must not be stored as issues."""
    pr_disguised_as_issue = {**MOCK_ISSUE, "pull_request": {"url": "https://..."}}
    client = MockGitHubClient(issues=[pr_disguised_as_issue])

    count = await fetch_and_store_issues(db_session, test_repo, client)

    assert count == 0


@pytest.mark.asyncio
async def test_fetch_issues_upserts_on_duplicate(db_session: AsyncSession, test_repo: Repo):
    """Re-fetching a changed issue updates it rather than failing."""
    client1 = MockGitHubClient(issues=[MOCK_ISSUE])
    await fetch_and_store_issues(db_session, test_repo, client1)

    updated = {**MOCK_ISSUE, "title": "Fix memory leak (updated)", "state": "closed",
               "closed_at": "2025-02-01T12:00:00Z"}
    client2 = MockGitHubClient(issues=[updated])
    await fetch_and_store_issues(db_session, test_repo, client2)

    result = await db_session.execute(
        select(Issue).where(Issue.repo_id == test_repo.id, Issue.github_number == 42)
    )
    issue = result.scalar_one()
    assert issue.title == "Fix memory leak (updated)"
    assert issue.state == "closed"


# ── PR Tests ─────────────────────────────────────────────────────────────────

from app.ingestion.fetchers import fetch_and_store_pull_requests

MOCK_PR = {
    "number": 10,
    "title": "Fix the leak",
    "body": "Closes #42\n\nThis PR fixes the memory leak.",
    "state": "closed",
    "user": {"login": "bob"},
    "merged_at": "2025-02-01T12:00:00Z",
    "created_at": "2025-01-30T09:00:00Z",
}

MOCK_PR_FILES = [
    {"filename": "src/server.py", "status": "modified"},
    {"filename": "tests/test_server.py", "status": "modified"},
]


class MockGitHubClientWithPRFiles(MockGitHubClient):
    """Extended mock that also handles the PR files sub-endpoint."""

    async def paginate(self, path: str, params: dict | None = None) -> AsyncGenerator[dict, None]:
        if "/pulls" in path and "/files" in path:
            for f in MOCK_PR_FILES:
                yield f
        else:
            async for item in super().paginate(path, params):
                yield item


@pytest.mark.asyncio
async def test_fetch_prs_stores_pr(db_session: AsyncSession, test_repo: Repo):
    client = MockGitHubClientWithPRFiles(prs=[MOCK_PR])
    count = await fetch_and_store_pull_requests(db_session, test_repo, client)
    assert count == 1
    result = await db_session.execute(
        select(PullRequest).where(PullRequest.repo_id == test_repo.id, PullRequest.github_number == 10)
    )
    pr = result.scalar_one()
    assert pr.author == "bob"
    assert pr.linked_issue_numbers == [42]


@pytest.mark.asyncio
async def test_fetch_prs_creates_issue_pr_edge(db_session: AsyncSession, test_repo: Repo):
    """PR body with 'Closes #42' should create an issue_pr relationship."""
    # First store issue #42 so we have its id
    issue_client = MockGitHubClient(issues=[MOCK_ISSUE])
    await fetch_and_store_issues(db_session, test_repo, issue_client)

    pr_client = MockGitHubClientWithPRFiles(prs=[MOCK_PR])
    await fetch_and_store_pull_requests(db_session, test_repo, pr_client)

    # Check relationship was created
    result = await db_session.execute(
        select(Relationship).where(
            Relationship.repo_id == test_repo.id,
            Relationship.edge_type == "issue_pr",
        )
    )
    rels = result.scalars().all()
    assert len(rels) == 1
    assert rels[0].target_type == "pull_request"


@pytest.mark.asyncio
async def test_fetch_prs_creates_pr_file_edges(db_session: AsyncSession, test_repo: Repo):
    """Each file changed in a PR should create a pr_file relationship."""
    client = MockGitHubClientWithPRFiles(prs=[MOCK_PR])
    await fetch_and_store_pull_requests(db_session, test_repo, client)

    result = await db_session.execute(
        select(Relationship).where(
            Relationship.repo_id == test_repo.id,
            Relationship.edge_type == "pr_file",
        )
    )
    rels = result.scalars().all()
    assert len(rels) == 2  # MOCK_PR_FILES has 2 files


# ── Commit fetcher tests ──────────────────────────────────────────────────────

from app.ingestion.fetchers import fetch_and_store_commits  # noqa: E402
from app.models.orm import Commit  # noqa: E402

MOCK_COMMIT = {
    "sha": "abc123def456abc123def456abc123def456abc1",
    "commit": {
        "message": "fix: resolve memory leak in server.py",
        "author": {
            "name": "Bob Smith",
            "email": "bob@example.com",
            "date": "2025-01-20T08:00:00Z",
        },
    },
    "author": {"login": "bob"},
}


class MockGitHubClientWithCommits(MockGitHubClient):
    """Extended mock that handles the commits path."""

    def __init__(self, commits: list[dict] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._commits = commits or []

    async def paginate(self, path: str, params: dict | None = None):
        if "/commits" in path and "/pulls" not in path:
            for item in self._commits:
                yield item
        else:
            async for item in super().paginate(path, params):
                yield item


@pytest.mark.asyncio
async def test_fetch_commits_stores_commit(db_session: AsyncSession, test_repo: Repo):
    client = MockGitHubClientWithCommits(commits=[MOCK_COMMIT])
    count = await fetch_and_store_commits(db_session, test_repo, client)

    assert count == 1
    result = await db_session.execute(
        select(Commit).where(Commit.repo_id == test_repo.id, Commit.sha == MOCK_COMMIT["sha"])
    )
    commit = result.scalar_one()
    assert commit.message == "fix: resolve memory leak in server.py"
    assert commit.author == "bob"


@pytest.mark.asyncio
async def test_fetch_commits_upserts_on_duplicate(db_session: AsyncSession, test_repo: Repo):
    """Running fetch twice for the same sha must not raise an error."""
    client = MockGitHubClientWithCommits(commits=[MOCK_COMMIT])
    await fetch_and_store_commits(db_session, test_repo, client)
    count = await fetch_and_store_commits(db_session, test_repo, client)
    assert count == 1  # second run also returns 1 (upserted)


# ── File fetcher tests ────────────────────────────────────────────────────────

from app.ingestion.fetchers import fetch_and_store_files  # noqa: E402

MOCK_TREE = {
    "tree": [
        {"path": "src/server.py", "type": "blob", "sha": "aaa111"},
        {"path": "src/utils.py", "type": "blob", "sha": "bbb222"},
        {"path": "README.md", "type": "blob", "sha": "ccc333"},
        {"path": "src/", "type": "tree", "sha": "ddd444"},  # directory — must be skipped
    ],
    "truncated": False,
}


class MockGitHubClientWithTree(MockGitHubClient):
    async def get(self, path: str) -> dict:
        if "/git/trees" in path:
            return MOCK_TREE
        return {}


@pytest.mark.asyncio
async def test_fetch_files_stores_blobs_only(db_session: AsyncSession, test_repo: Repo):
    """fetch_and_store_files skips 'tree' type entries, stores only 'blob'."""
    client = MockGitHubClientWithTree()
    count = await fetch_and_store_files(db_session, test_repo, client, default_branch="main")

    assert count == 3  # 3 blobs, 1 tree entry skipped

    result = await db_session.execute(
        select(File).where(File.repo_id == test_repo.id)
    )
    files = result.scalars().all()
    paths = {f.path for f in files}
    assert "src/server.py" in paths
    assert "src/" not in paths


@pytest.mark.asyncio
async def test_fetch_files_detects_language(db_session: AsyncSession, test_repo: Repo):
    """Language is detected from file extension."""
    client = MockGitHubClientWithTree()
    await fetch_and_store_files(db_session, test_repo, client, default_branch="main")

    result = await db_session.execute(
        select(File).where(File.repo_id == test_repo.id, File.path == "src/server.py")
    )
    f = result.scalar_one()
    assert f.language == "python"
