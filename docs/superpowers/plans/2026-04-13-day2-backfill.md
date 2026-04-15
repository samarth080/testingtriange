# Day 2 — Full Backfill Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fetch all issues, PRs, commits, and files from GitHub API for an installed repo, store them in Postgres, and create graph relationship edges — triggered by a `installation.created` webhook event and run as Celery background tasks.

**Architecture:** A `GitHubClient` handles paginated API calls using Link-header pagination. Four fetchers (issues, PRs, commits, files) each upsert their records into Postgres via `INSERT ... ON CONFLICT DO UPDATE`. A Celery task `backfill_repo` fans out to all four fetchers. The installation webhook handler is updated to upsert a `Repo` row and enqueue `backfill_repo`.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (async), asyncpg, httpx, Celery, Redis, PostgreSQL, pydantic-settings.

---

## File Structure

**New files:**
- `backend/app/core/database.py` — async engine + `AsyncSessionLocal` factory + `get_db` dependency
- `backend/app/ingestion/__init__.py` — empty package marker
- `backend/app/ingestion/github_client.py` — `_parse_next_url()` helper + `GitHubClient` class
- `backend/app/ingestion/fetchers.py` — `fetch_issues`, `fetch_pull_requests`, `fetch_commits`, `fetch_files`, `upsert_relationship`
- `backend/app/workers/ingestion_tasks.py` — Celery task definitions
- `backend/tests/test_github_client.py` — unit tests for client pagination helper
- `backend/tests/test_fetchers.py` — unit tests for fetchers using a mock client + real async DB session

**Modified files:**
- `backend/app/workers/celery_app.py` — add `"app.workers.ingestion_tasks"` to `include`
- `backend/app/api/webhooks.py` — add `AsyncSession` dependency, wire `_handle_installation` to upsert Repo + enqueue task

---

## Task 1: Async database session module

**Files:**
- Create: `backend/app/core/database.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_database.py
import pytest
from app.core.database import AsyncSessionLocal, get_db

@pytest.mark.asyncio
async def test_get_db_yields_session():
    """get_db() must yield an AsyncSession and close it."""
    from sqlalchemy.ext.asyncio import AsyncSession
    gen = get_db()
    session = await gen.__anext__()
    assert isinstance(session, AsyncSession)
    try:
        await gen.aclose()
    except StopAsyncIteration:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_database.py -v
```

Expected: `ImportError: cannot import name 'AsyncSessionLocal' from 'app.core.database'`

- [ ] **Step 3: Write implementation**

```python
# backend/app/core/database.py
"""
Async SQLAlchemy engine and session factory.

Usage in FastAPI routes:
    from app.core.database import get_db
    async def my_route(db: AsyncSession = Depends(get_db)): ...

Usage in Celery tasks (sync context):
    from app.core.database import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        ...
    # Then wrap with asyncio.run() in the Celery task
"""
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,  # Reconnect if Postgres dropped the connection
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False,  # Don't expire objects after commit — we read them after
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields an AsyncSession, closes it when the request ends."""
    async with AsyncSessionLocal() as session:
        yield session
```

- [ ] **Step 4: Run test to verify it passes**

```bash
python -m pytest tests/test_database.py -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/core/database.py backend/tests/test_database.py
git commit -m "feat: add async database session module"
```

---

## Task 2: GitHub API paginated client

**Files:**
- Create: `backend/app/ingestion/__init__.py`
- Create: `backend/app/ingestion/github_client.py`
- Create: `backend/tests/test_github_client.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_github_client.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.ingestion.github_client import _parse_next_url, GitHubClient


# ── _parse_next_url tests (pure function, no mocking needed) ─────────────────

def test_parse_next_url_returns_next_link():
    header = '<https://api.github.com/repos/foo/bar/issues?page=2&per_page=100>; rel="next", <https://api.github.com/repos/foo/bar/issues?page=5>; rel="last"'
    assert _parse_next_url(header) == "https://api.github.com/repos/foo/bar/issues?page=2&per_page=100"


def test_parse_next_url_none_when_no_next():
    header = '<https://api.github.com/repos/foo/bar/issues?page=1>; rel="prev"'
    assert _parse_next_url(header) is None


def test_parse_next_url_none_when_header_missing():
    assert _parse_next_url(None) is None


def test_parse_next_url_none_when_empty_string():
    assert _parse_next_url("") is None


# ── GitHubClient.paginate tests ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_paginate_single_page():
    """paginate() yields all items from a single-page response."""
    page1 = [{"id": 1}, {"id": 2}]

    mock_response = MagicMock()
    mock_response.json.return_value = page1
    mock_response.headers = {}
    mock_response.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_response):
        client = GitHubClient(token="test-token")
        results = [item async for item in client.paginate("/repos/foo/bar/issues")]

    assert results == [{"id": 1}, {"id": 2}]


@pytest.mark.asyncio
async def test_paginate_two_pages():
    """paginate() follows Link next header across two pages."""
    page1 = [{"id": 1}]
    page2 = [{"id": 2}]

    resp1 = MagicMock()
    resp1.json.return_value = page1
    resp1.headers = {"Link": '<https://api.github.com/repos/foo/bar/issues?page=2>; rel="next"'}
    resp1.raise_for_status = MagicMock()

    resp2 = MagicMock()
    resp2.json.return_value = page2
    resp2.headers = {}
    resp2.raise_for_status = MagicMock()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=[resp1, resp2]):
        client = GitHubClient(token="test-token")
        results = [item async for item in client.paginate("/repos/foo/bar/issues")]

    assert results == [{"id": 1}, {"id": 2}]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_github_client.py -v
```

Expected: `ImportError: cannot import name '_parse_next_url' from 'app.ingestion.github_client'`

- [ ] **Step 3: Create the package marker**

```python
# backend/app/ingestion/__init__.py
```

(empty file)

- [ ] **Step 4: Write implementation**

```python
# backend/app/ingestion/github_client.py
"""
GitHub REST API client with transparent Link-header pagination.

Usage:
    client = GitHubClient(token=await get_installation_token(installation_id))
    async for issue in client.paginate("/repos/owner/repo/issues", {"state": "all"}):
        process(issue)

Pagination: GitHub returns a Link header like:
    <https://api.github.com/...?page=2>; rel="next"
We follow it automatically, yielding items from all pages.
"""
import re
from collections.abc import AsyncGenerator
from typing import Any

import httpx

BASE_URL = "https://api.github.com"

_NEXT_LINK_RE = re.compile(r'<([^>]+)>;\s*rel="next"')


def _parse_next_url(link_header: str | None) -> str | None:
    """Extract the 'next' URL from a GitHub Link response header, or None."""
    if not link_header:
        return None
    match = _NEXT_LINK_RE.search(link_header)
    return match.group(1) if match else None


class GitHubClient:
    """
    Thin async HTTP client for the GitHub REST API.

    Handles:
    - Bearer token auth
    - GitHub API versioning headers
    - Transparent multi-page pagination via _parse_next_url
    """

    def __init__(self, token: str) -> None:
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def paginate(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        Yield every item across all pages for a list endpoint.

        Args:
            path: API path, e.g. "/repos/owner/repo/issues"
            params: Extra query params merged with per_page=100
        """
        request_params: dict[str, Any] = {"per_page": 100, **(params or {})}
        url: str | None = f"{BASE_URL}{path}"

        async with httpx.AsyncClient(headers=self._headers) as client:
            while url:
                response = await client.get(url, params=request_params)
                response.raise_for_status()
                for item in response.json():
                    yield item
                url = _parse_next_url(response.headers.get("Link"))
                # After the first request, pagination URL carries all params already
                request_params = {}

    async def get(self, path: str) -> dict[str, Any]:
        """Fetch a single resource (non-paginated)."""
        async with httpx.AsyncClient(headers=self._headers) as client:
            response = await client.get(f"{BASE_URL}{path}")
            response.raise_for_status()
            return response.json()
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
python -m pytest tests/test_github_client.py -v
```

Expected: `5 passed`

- [ ] **Step 6: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/ingestion/__init__.py backend/app/ingestion/github_client.py backend/tests/test_github_client.py
git commit -m "feat: add paginated GitHub API client"
```

---

## Task 3: Issue fetcher

**Files:**
- Create: `backend/app/ingestion/fetchers.py` (initial — issues only)
- Create: `backend/tests/test_fetchers.py` (initial — issues only)

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_fetchers.py
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
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.ingestion.fetchers import fetch_and_store_issues
from app.models.orm import Issue, Repo


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
    "pull_request": None,   # absence of this key = it's a real issue
}


@pytest_asyncio.fixture
async def db_session():
    async with AsyncSessionLocal() as session:
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_fetchers.py -v
```

Expected: `ImportError: cannot import name 'fetch_and_store_issues'`

- [ ] **Step 3: Write the issue fetcher (start of fetchers.py)**

```python
# backend/app/ingestion/fetchers.py
"""
GitHub data fetchers — one function per entity type.

Each function:
1. Calls GitHubClient.paginate() to get all pages from GitHub API
2. Upserts records into Postgres using INSERT ... ON CONFLICT DO UPDATE
3. Returns count of records processed

Date cutoff: we pass since=TWO_YEARS_AGO to GitHub for issues/commits.
PRs and files don't support a 'since' filter so we fetch all and rely on
upsert idempotency if re-run.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.github_client import GitHubClient
from app.models.orm import Commit, File, Issue, PullRequest, Relationship, Repo

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Fetch issues/commits created in the last 2 years
BACKFILL_SINCE = datetime.now(tz=timezone.utc) - timedelta(days=730)

# Regex to extract linked issue numbers from PR bodies:
# matches: closes #123, fixes #42, resolves #7, close #1, fix #99, resolve #5
_LINKED_RE = re.compile(r"(?:closes?|fixes?|resolves?)\s+#(\d+)", re.IGNORECASE)


def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO-8601 UTC string from GitHub ('2025-01-15T10:00:00Z') to datetime."""
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _extract_linked_issues(body: str | None) -> list[int]:
    """Return issue numbers referenced in a PR body via closes/fixes/resolves patterns."""
    if not body:
        return []
    return [int(n) for n in _LINKED_RE.findall(body)]


# ── Issue fetcher ─────────────────────────────────────────────────────────────

async def fetch_and_store_issues(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
) -> int:
    """
    Fetch all issues for a repo (since 2 years ago) and upsert into the issues table.

    Skips items that are actually PRs (GitHub's /issues endpoint returns both;
    PR items carry a 'pull_request' key).

    Returns: count of issues stored.
    """
    path = f"/repos/{repo.owner}/{repo.name}/issues"
    params = {
        "state": "all",
        "since": BACKFILL_SINCE.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sort": "created",
        "direction": "asc",
    }

    count = 0
    async for item in client.paginate(path, params):
        # GitHub /issues returns PRs too — skip them
        if item.get("pull_request"):
            continue

        data = {
            "repo_id": repo.id,
            "github_number": item["number"],
            "title": item["title"],
            "body": item.get("body") or "",
            "state": item["state"],
            "author": item["user"]["login"],
            "labels": [label["name"] for label in item.get("labels", [])],
            "created_at": _parse_dt(item["created_at"]),
            "closed_at": _parse_dt(item.get("closed_at")),
        }

        stmt = (
            insert(Issue)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_issues_repo_number",
                set_={
                    "title": data["title"],
                    "body": data["body"],
                    "state": data["state"],
                    "labels": data["labels"],
                    "closed_at": data["closed_at"],
                },
            )
        )
        await session.execute(stmt)
        count += 1

    await session.commit()
    logger.info("Stored %d issues for %s/%s", count, repo.owner, repo.name)
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_fetchers.py::test_fetch_issues_stores_issue tests/test_fetchers.py::test_fetch_issues_skips_pull_requests tests/test_fetchers.py::test_fetch_issues_upserts_on_duplicate -v
```

Expected: `3 passed`

- [ ] **Step 5: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/ingestion/fetchers.py backend/tests/test_fetchers.py
git commit -m "feat: add issue fetcher with upsert"
```

---

## Task 4: PR fetcher with relationship extraction

**Files:**
- Modify: `backend/app/ingestion/fetchers.py` (add `fetch_and_store_pull_requests`)
- Modify: `backend/tests/test_fetchers.py` (add PR tests)

- [ ] **Step 1: Add failing PR tests to test_fetchers.py**

Append to `backend/tests/test_fetchers.py`:

```python
# ── Append to backend/tests/test_fetchers.py ─────────────────────────────────
from app.ingestion.fetchers import fetch_and_store_pull_requests
from app.models.orm import PullRequest, Relationship

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_fetchers.py::test_fetch_prs_stores_pr -v
```

Expected: `ImportError: cannot import name 'fetch_and_store_pull_requests'`

- [ ] **Step 3: Add PR fetcher + upsert_relationship to fetchers.py**

Append to `backend/app/ingestion/fetchers.py`:

```python
# ── Append to backend/app/ingestion/fetchers.py ──────────────────────────────

async def upsert_relationship(
    session: AsyncSession,
    repo_id: int,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    edge_type: str,
) -> None:
    """Insert a graph edge, silently skip if it already exists."""
    stmt = (
        insert(Relationship)
        .values(
            repo_id=repo_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            edge_type=edge_type,
        )
        .on_conflict_do_nothing(constraint="uq_relationships")
    )
    await session.execute(stmt)


async def fetch_and_store_pull_requests(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
) -> int:
    """
    Fetch all PRs and upsert into pull_requests table.

    Also:
    - Extracts linked issue numbers from PR body (closes/fixes/resolves #N)
    - Creates issue_pr graph edges for each linked issue found in our DB
    - Fetches PR file list and creates pr_file edges

    Returns: count of PRs stored.
    """
    from sqlalchemy import select as sa_select

    path = f"/repos/{repo.owner}/{repo.name}/pulls"
    params = {"state": "all", "sort": "created", "direction": "asc"}

    count = 0
    async for item in client.paginate(path, params):
        linked_numbers = _extract_linked_issues(item.get("body"))

        data = {
            "repo_id": repo.id,
            "github_number": item["number"],
            "title": item["title"],
            "body": item.get("body") or "",
            "state": item["state"],
            "author": item["user"]["login"],
            "merged_at": _parse_dt(item.get("merged_at")),
            "linked_issue_numbers": linked_numbers,
            "created_at": _parse_dt(item["created_at"]),
        }

        stmt = (
            insert(PullRequest)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_prs_repo_number",
                set_={
                    "title": data["title"],
                    "body": data["body"],
                    "state": data["state"],
                    "merged_at": data["merged_at"],
                    "linked_issue_numbers": data["linked_issue_numbers"],
                },
            )
            .returning(PullRequest.id)
        )
        result = await session.execute(stmt)
        pr_id = result.scalar_one()

        # issue_pr edges: find each linked issue in our DB and create an edge
        for issue_number in linked_numbers:
            issue_result = await session.execute(
                sa_select(Issue.id).where(
                    Issue.repo_id == repo.id,
                    Issue.github_number == issue_number,
                )
            )
            issue_id = issue_result.scalar_one_or_none()
            if issue_id:
                await upsert_relationship(
                    session,
                    repo_id=repo.id,
                    source_type="issue",
                    source_id=issue_id,
                    target_type="pull_request",
                    target_id=pr_id,
                    edge_type="issue_pr",
                )

        # pr_file edges: fetch the list of files this PR changed
        files_path = f"/repos/{repo.owner}/{repo.name}/pulls/{item['number']}/files"
        async for file_item in client.paginate(files_path):
            # Store the file path as target_id placeholder — we use a hash
            # Real File rows are created in fetch_and_store_files; here we store
            # the path string as a string in a separate column. Since Relationship
            # target_id is BigInteger, we skip pr_file here and create them in
            # fetch_and_store_files after File rows exist.
            # Instead: store (pr_id → file path) as a pr_file edge where target_id
            # is set to 0 temporarily and updated in Task 6.
            # Simplification for Day 2: create File stub rows on the fly.
            file_stmt = (
                insert(File)
                .values(
                    repo_id=repo.id,
                    path=file_item["filename"],
                    language=None,
                    content_hash=None,
                    last_indexed_at=None,
                )
                .on_conflict_do_nothing(constraint="uq_files_repo_path")
                .returning(File.id)
            )
            file_result = await session.execute(file_stmt)
            file_id = file_result.scalar_one_or_none()

            if file_id is None:
                # Row already existed — fetch its id
                existing = await session.execute(
                    sa_select(File.id).where(
                        File.repo_id == repo.id,
                        File.path == file_item["filename"],
                    )
                )
                file_id = existing.scalar_one()

            await upsert_relationship(
                session,
                repo_id=repo.id,
                source_type="pull_request",
                source_id=pr_id,
                target_type="file",
                target_id=file_id,
                edge_type="pr_file",
            )

        count += 1

    await session.commit()
    logger.info("Stored %d PRs for %s/%s", count, repo.owner, repo.name)
    return count
```

- [ ] **Step 4: Run PR tests**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_fetchers.py::test_fetch_prs_stores_pr tests/test_fetchers.py::test_fetch_prs_creates_issue_pr_edge tests/test_fetchers.py::test_fetch_prs_creates_pr_file_edges -v
```

Expected: `3 passed`

- [ ] **Step 5: Run all fetcher tests to check for regressions**

```bash
python -m pytest tests/test_fetchers.py -v
```

Expected: `6 passed`

- [ ] **Step 6: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/ingestion/fetchers.py backend/tests/test_fetchers.py
git commit -m "feat: add PR fetcher with issue_pr and pr_file graph edges"
```

---

## Task 5: Commit fetcher

**Files:**
- Modify: `backend/app/ingestion/fetchers.py` (add `fetch_and_store_commits`)
- Modify: `backend/tests/test_fetchers.py` (add commit tests)

- [ ] **Step 1: Add failing commit tests to test_fetchers.py**

Append to `backend/tests/test_fetchers.py`:

```python
# ── Append to backend/tests/test_fetchers.py ─────────────────────────────────
from app.ingestion.fetchers import fetch_and_store_commits
from app.models.orm import Commit

MOCK_COMMIT = {
    "sha": "abc123def456abc123def456abc123def456abc123",
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


@pytest.mark.asyncio
async def test_fetch_commits_stores_commit(db_session: AsyncSession, test_repo: Repo):
    client = MockGitHubClient()
    client._commits = [MOCK_COMMIT]

    # Monkey-patch paginate for commits path
    original_paginate = client.paginate

    async def patched_paginate(path, params=None):
        if "/commits" in path:
            for item in client._commits:
                yield item
        else:
            async for item in original_paginate(path, params):
                yield item

    client.paginate = patched_paginate

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
    client = MockGitHubClient()
    client._commits = [MOCK_COMMIT]

    async def patched_paginate(path, params=None):
        if "/commits" in path:
            for item in client._commits:
                yield item
        return
        yield  # make it an async generator

    client.paginate = patched_paginate

    await fetch_and_store_commits(db_session, test_repo, client)
    count = await fetch_and_store_commits(db_session, test_repo, client)
    assert count == 1  # second run also returns 1 (upserted)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_fetchers.py::test_fetch_commits_stores_commit -v
```

Expected: `ImportError: cannot import name 'fetch_and_store_commits'`

- [ ] **Step 3: Add commit fetcher to fetchers.py**

Append to `backend/app/ingestion/fetchers.py`:

```python
# ── Append to backend/app/ingestion/fetchers.py ──────────────────────────────

async def fetch_and_store_commits(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
) -> int:
    """
    Fetch commits from the last 2 years and upsert into the commits table.

    GitHub's commit list endpoint returns basic info (sha, message, author, date).
    changed_files is left empty here; it gets populated in Day 3 when we index
    files and can derive commit→file relationships from the tree.

    Returns: count of commits stored.
    """
    path = f"/repos/{repo.owner}/{repo.name}/commits"
    params = {"since": BACKFILL_SINCE.strftime("%Y-%m-%dT%H:%M:%SZ")}

    count = 0
    async for item in client.paginate(path, params):
        commit_data = item.get("commit", {})
        author_data = commit_data.get("author", {})

        # Prefer the GitHub login (item["author"]) over git author name
        author_login = (item.get("author") or {}).get("login") or author_data.get("name", "unknown")

        data = {
            "repo_id": repo.id,
            "sha": item["sha"],
            "message": commit_data.get("message", ""),
            "author": author_login,
            "committed_at": _parse_dt(author_data.get("date")),
            "changed_files": [],  # Populated in Day 3 during file indexing
        }

        stmt = (
            insert(Commit)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_commits_repo_sha",
                set_={
                    "message": data["message"],
                    "author": data["author"],
                },
            )
        )
        await session.execute(stmt)
        count += 1

    await session.commit()
    logger.info("Stored %d commits for %s/%s", count, repo.owner, repo.name)
    return count
```

- [ ] **Step 4: Run commit tests**

```bash
python -m pytest tests/test_fetchers.py::test_fetch_commits_stores_commit tests/test_fetchers.py::test_fetch_commits_upserts_on_duplicate -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/ingestion/fetchers.py backend/tests/test_fetchers.py
git commit -m "feat: add commit fetcher"
```

---

## Task 6: File fetcher

**Files:**
- Modify: `backend/app/ingestion/fetchers.py` (add `fetch_and_store_files`)
- Modify: `backend/tests/test_fetchers.py` (add file tests)

- [ ] **Step 1: Add failing file tests to test_fetchers.py**

Append to `backend/tests/test_fetchers.py`:

```python
# ── Append to backend/tests/test_fetchers.py ─────────────────────────────────
from app.ingestion.fetchers import fetch_and_store_files
from app.models.orm import File

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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_fetchers.py::test_fetch_files_stores_blobs_only -v
```

Expected: `ImportError: cannot import name 'fetch_and_store_files'`

- [ ] **Step 3: Add file fetcher to fetchers.py**

Append to `backend/app/ingestion/fetchers.py`:

```python
# ── Append to backend/app/ingestion/fetchers.py ──────────────────────────────

# Extension → language name mapping (extend as needed)
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sh": "shell",
    ".sql": "sql",
}


def _detect_language(path: str) -> str | None:
    """Return a language name based on file extension, or None if unknown."""
    from pathlib import PurePosixPath
    suffix = PurePosixPath(path).suffix.lower()
    return _EXT_TO_LANG.get(suffix)


async def fetch_and_store_files(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
    default_branch: str = "main",
) -> int:
    """
    Fetch the full repo file tree (recursive) and upsert File stubs.

    Uses GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
    which returns all blob (file) and tree (directory) entries in one call.
    We store only blob entries and detect language from extension.

    content_hash and last_indexed_at are left None — they are populated
    in Day 3 when we download and chunk file content.

    Returns: count of files stored.
    """
    tree_data = await client.get(
        f"/repos/{repo.owner}/{repo.name}/git/trees/{default_branch}?recursive=1"
    )

    count = 0
    for entry in tree_data.get("tree", []):
        if entry.get("type") != "blob":
            continue  # Skip directories

        data = {
            "repo_id": repo.id,
            "path": entry["path"],
            "language": _detect_language(entry["path"]),
            "content_hash": None,
            "last_indexed_at": None,
        }

        stmt = (
            insert(File)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_files_repo_path",
                set_={"language": data["language"]},
            )
        )
        await session.execute(stmt)
        count += 1

    await session.commit()
    logger.info("Stored %d files for %s/%s", count, repo.owner, repo.name)
    return count
```

- [ ] **Step 4: Run file tests**

```bash
python -m pytest tests/test_fetchers.py::test_fetch_files_stores_blobs_only tests/test_fetchers.py::test_fetch_files_detects_language -v
```

Expected: `2 passed`

- [ ] **Step 5: Run the full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass (5 webhook + 1 DB + 5 github_client + 8 fetcher = 19 total)

- [ ] **Step 6: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/ingestion/fetchers.py backend/tests/test_fetchers.py
git commit -m "feat: add file fetcher with language detection"
```

---

## Task 7: Celery ingestion tasks

**Files:**
- Create: `backend/app/workers/ingestion_tasks.py`
- Modify: `backend/app/workers/celery_app.py`

- [ ] **Step 1: Write failing test**

```python
# backend/tests/test_ingestion_tasks.py
"""
Ingestion task tests — verify task routing and status updates.
We mock the fetchers so no real GitHub API calls are made.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.workers.ingestion_tasks import _async_backfill_repo


@pytest.mark.asyncio
async def test_async_backfill_repo_updates_status_to_done(tmp_path):
    """
    _async_backfill_repo should set backfill_status='done' after all fetchers complete.
    We mock the DB and all four fetchers.
    """
    from unittest.mock import MagicMock, AsyncMock

    mock_repo = MagicMock()
    mock_repo.id = 1
    mock_repo.owner = "testowner"
    mock_repo.name = "testrepo"
    mock_repo.installation_id = 111
    mock_repo.backfill_status = "running"

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_repo)))
    mock_session.commit = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    mock_session_factory = MagicMock(return_value=mock_session)

    with (
        patch("app.workers.ingestion_tasks.AsyncSessionLocal", mock_session_factory),
        patch("app.workers.ingestion_tasks.get_installation_token", new_callable=AsyncMock, return_value="tok"),
        patch("app.workers.ingestion_tasks.GitHubClient"),
        patch("app.workers.ingestion_tasks.fetch_and_store_issues", new_callable=AsyncMock, return_value=5),
        patch("app.workers.ingestion_tasks.fetch_and_store_pull_requests", new_callable=AsyncMock, return_value=3),
        patch("app.workers.ingestion_tasks.fetch_and_store_commits", new_callable=AsyncMock, return_value=10),
        patch("app.workers.ingestion_tasks.fetch_and_store_files", new_callable=AsyncMock, return_value=20),
        patch("app.workers.ingestion_tasks._get_default_branch", new_callable=AsyncMock, return_value="main"),
    ):
        result = await _async_backfill_repo(repo_id=1)

    assert result["issues"] == 5
    assert result["prs"] == 3
    assert result["commits"] == 10
    assert result["files"] == 20
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_ingestion_tasks.py -v
```

Expected: `ImportError: cannot import name '_async_backfill_repo'`

- [ ] **Step 3: Write ingestion_tasks.py**

```python
# backend/app/workers/ingestion_tasks.py
"""
Celery tasks for GitHub data ingestion.

Task hierarchy:
  backfill_repo(repo_id)
    └─ runs all four fetchers sequentially inside an async context

Design: Celery workers are synchronous, but our fetchers are async.
We bridge this with asyncio.run() — the same pattern used in Alembic's env.py.
"""
import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.core.github_auth import get_installation_token
from app.ingestion.github_client import GitHubClient
from app.ingestion.fetchers import (
    fetch_and_store_commits,
    fetch_and_store_files,
    fetch_and_store_issues,
    fetch_and_store_pull_requests,
)
from app.models.orm import Repo
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _get_default_branch(client: GitHubClient, owner: str, name: str) -> str:
    """Fetch the repo's default branch name from GitHub API."""
    data = await client.get(f"/repos/{owner}/{name}")
    return data.get("default_branch", "main")


async def _async_backfill_repo(repo_id: int) -> dict:
    """
    Async implementation of the backfill task.

    Fetches issues → PRs → commits → files in order.
    Issues must come before PRs so issue_pr edges can reference existing issue rows.
    Returns a summary dict with counts per entity type.
    """
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            __import__("sqlalchemy", fromlist=["select"]).select(Repo).where(Repo.id == repo_id)
        )
        repo = result.scalar_one_or_none()
        if not repo:
            logger.error("Repo id=%d not found — skipping backfill", repo_id)
            return {"error": "repo_not_found"}

        logger.info("Starting backfill for %s/%s (id=%d)", repo.owner, repo.name, repo_id)

        token = await get_installation_token(repo.installation_id)
        client = GitHubClient(token=token)
        default_branch = await _get_default_branch(client, repo.owner, repo.name)

        # Run fetchers — issues before PRs (edge creation dependency)
        issues_count = await fetch_and_store_issues(session, repo, client)
        prs_count = await fetch_and_store_pull_requests(session, repo, client)
        commits_count = await fetch_and_store_commits(session, repo, client)
        files_count = await fetch_and_store_files(session, repo, client, default_branch=default_branch)

        # Mark backfill complete
        repo.backfill_status = "done"
        await session.commit()

        summary = {
            "repo_id": repo_id,
            "issues": issues_count,
            "prs": prs_count,
            "commits": commits_count,
            "files": files_count,
        }
        logger.info("Backfill complete for %s/%s: %s", repo.owner, repo.name, summary)
        return summary


@celery_app.task(name="ingestion.backfill_repo", bind=True, max_retries=3)
def backfill_repo(self, repo_id: int) -> dict:
    """
    Celery task: fetch and store all GitHub data for a repo.

    Retries up to 3 times on transient errors (rate limits, network blips).
    bind=True gives access to self.retry().
    """
    try:
        return asyncio.run(_async_backfill_repo(repo_id))
    except Exception as exc:
        logger.exception("Backfill failed for repo_id=%d: %s", repo_id, exc)
        raise self.retry(exc=exc, countdown=60)  # Retry after 60 seconds
```

- [ ] **Step 4: Update celery_app.py to autodiscover ingestion tasks**

Edit `backend/app/workers/celery_app.py` — change the `include` list:

```python
# backend/app/workers/celery_app.py  — only the changed section
celery_app = Celery(
    "triage_copilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.ingestion_tasks",  # Day 2: backfill_repo task
        # "app.workers.triage_tasks",   # Day 5
    ],
)
```

- [ ] **Step 5: Run the task test**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_ingestion_tasks.py -v
```

Expected: `1 passed`

- [ ] **Step 6: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/workers/ingestion_tasks.py backend/app/workers/celery_app.py backend/tests/test_ingestion_tasks.py
git commit -m "feat: add Celery backfill_repo task"
```

---

## Task 8: Wire installation webhook to create Repo and enqueue backfill

**Files:**
- Modify: `backend/app/api/webhooks.py`
- Modify: `backend/tests/test_webhooks.py`

- [ ] **Step 1: Add failing webhook wiring test**

Append to `backend/tests/test_webhooks.py`:

```python
# ── Append to backend/tests/test_webhooks.py ─────────────────────────────────
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

# Helper already defined in the file — reuse _make_sig and client fixture

INSTALLATION_PAYLOAD = {
    "action": "created",
    "installation": {"id": 55555},
    "repositories": [
        {"id": 999001, "name": "myrepo", "full_name": "alice/myrepo"}
    ],
    "sender": {"login": "alice"},
}


def test_installation_created_enqueues_backfill(client):
    """Installation webhook must upsert Repo and enqueue backfill_repo task."""
    body = json.dumps(INSTALLATION_PAYLOAD).encode()
    sig = _make_sig(body)

    with (
        patch("app.api.webhooks.AsyncSessionLocal") as mock_session_factory,
        patch("app.api.webhooks.backfill_repo") as mock_task,
        patch("app.api.webhooks.asyncio") as mock_asyncio,
    ):
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session.execute = AsyncMock(return_value=MagicMock(
            scalar_one_or_none=MagicMock(return_value=None)  # Repo doesn't exist yet
        ))
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()
        mock_session_factory.return_value = mock_session
        mock_asyncio.run = MagicMock(return_value=42)  # Returns fake repo.id

        response = client.post(
            "/webhooks/github",
            content=body,
            headers={
                "X-Hub-Signature-256": sig,
                "X-GitHub-Event": "installation",
                "Content-Type": "application/json",
            },
        )

    assert response.status_code == 202
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_webhooks.py::test_installation_created_enqueues_backfill -v
```

Expected: The test fails because the handler doesn't yet call `backfill_repo`.

- [ ] **Step 3: Update webhooks.py to wire installation event**

Replace the `_handle_installation` function in `backend/app/api/webhooks.py` and add the required imports:

```python
# backend/app/api/webhooks.py — add these imports at the top of the file
import asyncio

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.database import AsyncSessionLocal
from app.models.orm import Repo
```

Replace the `_handle_installation` function body:

```python
async def _handle_installation(body: dict) -> Response:
    """
    Handle GitHub App installation events.

    action=created → upsert Repo rows + enqueue backfill_repo for each repo
    action=deleted → log only (cleanup deferred to Day 8)
    """
    action = body.get("action")
    installation_id = body.get("installation", {}).get("id")
    repos = body.get("repositories", [])

    logger.info(
        "Installation event: action=%s installation_id=%s repos=%s",
        action,
        installation_id,
        [r.get("full_name") for r in repos],
    )

    if action == "created" and repos:
        # Import here to avoid circular import at module load time
        from app.workers.ingestion_tasks import backfill_repo

        async def _upsert_and_enqueue() -> None:
            async with AsyncSessionLocal() as session:
                for repo_data in repos:
                    owner, name = repo_data["full_name"].split("/", 1)
                    stmt = (
                        pg_insert(Repo)
                        .values(
                            github_id=repo_data["id"],
                            owner=owner,
                            name=name,
                            installation_id=installation_id,
                            backfill_status="running",
                        )
                        .on_conflict_do_update(
                            constraint="uq_repos_github_id",
                            set_={
                                "installation_id": installation_id,
                                "backfill_status": "running",
                            },
                        )
                        .returning(Repo.id)
                    )
                    result = await session.execute(stmt)
                    repo_id = result.scalar_one()
                    await session.commit()

                    # Enqueue Celery task — non-blocking
                    backfill_repo.delay(repo_id)
                    logger.info("Enqueued backfill_repo for repo_id=%d (%s)", repo_id, repo_data["full_name"])

        asyncio.run(_upsert_and_enqueue())

    return Response(status_code=202)
```

- [ ] **Step 4: Run all webhook tests**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m pytest tests/test_webhooks.py -v
```

Expected: All 6 tests pass

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v
```

Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/api/webhooks.py backend/tests/test_webhooks.py
git commit -m "feat: wire installation webhook to upsert Repo and enqueue backfill"
```

---

## Task 9: Smoke test on real repo

This is a manual end-to-end test. No new code — verify the pipeline works against your real GitHub App and the `testingtriange` repo.

**Prerequisites:**
- `.env` filled with real `GITHUB_APP_ID`, `GITHUB_WEBHOOK_SECRET`, `GITHUB_PRIVATE_KEY_PATH`
- GitHub App installed on `samarth080/testingtriange`
- Postgres running locally (from Day 1)

- [ ] **Step 1: Run Postgres and Redis**

If using Postgres.app:
```bash
# Postgres should already be running from Day 1
# If not: open Postgres.app and click Start

# Redis (if installed from source in Day 1):
redis-server --daemonize yes
```

- [ ] **Step 2: Apply migrations (if not already applied)**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -m alembic upgrade head
```

Expected: `Running upgrade  -> 001, initial schema`

- [ ] **Step 3: Start a Celery worker in one terminal**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
celery -A app.workers.celery_app worker --loglevel=info
```

Expected: Worker starts, shows `[tasks]` list including `ingestion.backfill_repo`

- [ ] **Step 4: Manually trigger backfill via Python shell in a second terminal**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python - <<'EOF'
import asyncio
from app.core.config import settings
from app.core.github_auth import get_installation_token, create_github_jwt

# Verify JWT generation works
jwt = create_github_jwt()
print(f"JWT generated: {jwt[:30]}...")
EOF
```

Expected: Prints a JWT token prefix without errors.

- [ ] **Step 5: Find your installation ID**

```bash
python - <<'EOF'
import asyncio
import httpx
from app.core.github_auth import create_github_jwt

async def main():
    jwt = create_github_jwt()
    async with httpx.AsyncClient() as client:
        r = await client.get(
            "https://api.github.com/app/installations",
            headers={
                "Authorization": f"Bearer {jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        r.raise_for_status()
        for inst in r.json():
            print(f"installation_id={inst['id']} account={inst['account']['login']}")

asyncio.run(main())
EOF
```

Expected: Prints your installation ID for `samarth080`.

- [ ] **Step 6: Insert a Repo row and trigger backfill**

Replace `INSTALLATION_ID` with the value from Step 5 and `GITHUB_REPO_ID` with the numeric ID of `testingtriange` (find it at `https://api.github.com/repos/samarth080/testingtriange`):

```bash
python - <<'EOF'
import asyncio
from app.core.database import AsyncSessionLocal
from app.models.orm import Repo
from sqlalchemy.dialects.postgresql import insert as pg_insert

INSTALLATION_ID = 12345678   # replace with your real installation_id
GITHUB_REPO_ID  = 87654321   # replace with testingtriange's github_id

async def main():
    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(Repo)
            .values(
                github_id=GITHUB_REPO_ID,
                owner="samarth080",
                name="testingtriange",
                installation_id=INSTALLATION_ID,
                backfill_status="running",
            )
            .on_conflict_do_update(
                constraint="uq_repos_github_id",
                set_={"backfill_status": "running"},
            )
            .returning(Repo.id)
        )
        result = await session.execute(stmt)
        repo_id = result.scalar_one()
        await session.commit()
        print(f"Repo inserted: id={repo_id}")
        return repo_id

repo_id = asyncio.run(main())

# Enqueue the Celery task
from app.workers.ingestion_tasks import backfill_repo
task = backfill_repo.delay(repo_id)
print(f"Task enqueued: {task.id}")
EOF
```

Expected: Prints `Repo inserted: id=1` and a Celery task UUID.

- [ ] **Step 7: Watch the Celery worker terminal**

Expected output in the worker terminal:
```
[INFO] Starting backfill for samarth080/testingtriange (id=1)
[INFO] Stored N issues for samarth080/testingtriange
[INFO] Stored N PRs for samarth080/testingtriange
[INFO] Stored N commits for samarth080/testingtriange
[INFO] Stored N files for samarth080/testingtriange
[INFO] Backfill complete for samarth080/testingtriange: {...}
```

- [ ] **Step 8: Verify data in Postgres**

```bash
psql -U triage -d triage -c "
SELECT
  (SELECT count(*) FROM issues WHERE repo_id=1)    AS issues,
  (SELECT count(*) FROM pull_requests WHERE repo_id=1) AS prs,
  (SELECT count(*) FROM commits WHERE repo_id=1)   AS commits,
  (SELECT count(*) FROM files WHERE repo_id=1)     AS files,
  (SELECT count(*) FROM relationships WHERE repo_id=1) AS edges,
  (SELECT backfill_status FROM repos WHERE id=1)   AS status;
"
```

Expected: All counts > 0 (exact values depend on the repo), `status = done`.

- [ ] **Step 9: Commit any final fixes, then push**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git push
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] Full backfill pipeline — issues, PRs, commits, files (Tasks 3-6)
- [x] Celery tasks with fan-out (Task 7)
- [x] Backfill scope: last 2 years via `since` param (fetchers.py: `BACKFILL_SINCE`)
- [x] Relationship edges: `issue_pr` from PR body parsing, `pr_file` from PR files endpoint (Task 4)
- [x] Installation webhook → upsert Repo → enqueue backfill (Task 8)
- [x] Test on one real repo (Task 9 smoke test)

**Placeholder scan:** None found — all steps contain full code.

**Type consistency:**
- `fetch_and_store_*` functions all take `(session: AsyncSession, repo: Repo, client: GitHubClient)` ✓
- `upsert_relationship` used consistently in Task 4 and 5 ✓
- `MockGitHubClient` in tests matches the real `GitHubClient` interface (`.paginate()`, `.get()`) ✓
