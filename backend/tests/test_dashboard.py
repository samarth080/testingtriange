"""Tests for GET /dashboard/* endpoints."""
import pytest
from datetime import datetime, timezone
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock

from app.core.database import get_db
from app.main import app


def dt() -> datetime:
    return datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_repo() -> MagicMock:
    r = MagicMock()
    r.id = 1
    r.owner = "acme"
    r.name = "myrepo"
    r.backfill_status = "done"
    r.created_at = dt()
    return r


def make_triage_result() -> MagicMock:
    tr = MagicMock()
    tr.id = 10
    tr.issue_id = 5
    tr.output = {
        "confidence": "high",
        "labels": ["bug"],
        "reasoning": "It's a bug.",
        "relevant_files": ["src/main.py"],
        "suggested_assignees": [],
        "duplicate_of": None,
    }
    tr.latency_ms = 1200
    tr.comment_url = "https://github.com/acme/myrepo/issues/42#issuecomment-1"
    tr.created_at = dt()
    return tr


def make_issue() -> MagicMock:
    i = MagicMock()
    i.id = 5
    i.github_number = 42
    i.title = "Fix memory leak"
    i.body = "Details here."
    i.labels = ["bug"]
    return i


# ── /dashboard/repos ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_repos_returns_repos():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [make_repo()]
    session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield session

    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/repos")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["owner"] == "acme"
    assert data[0]["name"] == "myrepo"
    assert data[0]["backfill_status"] == "done"
    assert "id" in data[0]
    assert "created_at" in data[0]


@pytest.mark.asyncio
async def test_list_repos_empty():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield session

    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/repos")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert resp.json() == []


# ── /dashboard/repos/{repo_id}/results ───────────────────────────────────────

@pytest.mark.asyncio
async def test_list_triage_results():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.all.return_value = [(make_triage_result(), make_issue())]
    session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield session

    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/repos/1/results")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["github_number"] == 42
    assert data[0]["title"] == "Fix memory leak"
    assert data[0]["confidence"] == "high"
    assert data[0]["labels"] == ["bug"]
    assert data[0]["latency_ms"] == 1200


# ── /dashboard/repos/{repo_id}/results/{result_id} ───────────────────────────

@pytest.mark.asyncio
async def test_get_triage_detail():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = (make_triage_result(), make_issue())
    session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield session

    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/repos/1/results/10")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    data = resp.json()
    assert data["github_number"] == 42
    assert data["title"] == "Fix memory leak"
    assert data["confidence"] == "high"
    assert data["reasoning"] == "It's a bug."
    assert data["relevant_files"] == ["src/main.py"]
    assert data["labels"] == ["bug"]


@pytest.mark.asyncio
async def test_get_triage_detail_not_found():
    session = AsyncMock()
    mock_result = MagicMock()
    mock_result.one_or_none.return_value = None
    session.execute = AsyncMock(return_value=mock_result)

    async def override():
        yield session

    app.dependency_overrides[get_db] = override
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/dashboard/repos/1/results/999")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 404
