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
from app.models.orm import Issue, Repo

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
