"""Smoke tests for POST /triage. All external calls are mocked."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.core.database import get_db
from app.triage.schemas import TriageOutput


VALID_OUTPUT = TriageOutput(
    duplicate_of=None,
    labels=["bug"],
    relevant_files=["src/server.py"],
    suggested_assignees=[],
    confidence="high",
    reasoning="Clear regression introduced in last PR.",
)


def make_mock_issue():
    issue = MagicMock()
    issue.id = 1
    issue.github_number = 42
    issue.title = "Memory leak"
    issue.body = "Happens on startup"
    issue.labels = ["bug"]
    return issue


def make_mock_session(scalar_result):
    """Return an AsyncMock session where execute().scalar_one_or_none() returns scalar_result."""
    mock_session = AsyncMock()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=scalar_result)
    mock_session.execute = AsyncMock(return_value=execute_result)
    return mock_session


@pytest.mark.asyncio
async def test_triage_endpoint_returns_200_with_structured_output():
    mock_issue = make_mock_issue()
    mock_session = make_mock_session(mock_issue)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        with patch("app.api.triage.embedder_from_settings"), \
             patch("app.api.triage.QdrantStore"), \
             patch("app.api.triage.run_triage_pipeline") as mock_pipeline, \
             patch("app.api.triage.settings"):

            mock_pipeline.return_value = (VALID_OUTPUT, 450)

            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                response = await client.post("/triage", json={"repo_id": 1, "issue_github_number": 42})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()
    assert data["confidence"] == "high"
    assert data["labels"] == ["bug"]
    assert data["relevant_files"] == ["src/server.py"]
    assert data["issue_github_number"] == 42
    assert data["latency_ms"] == 450


@pytest.mark.asyncio
async def test_triage_endpoint_returns_404_when_issue_not_found():
    mock_session = make_mock_session(None)

    async def override_get_db():
        yield mock_session

    app.dependency_overrides[get_db] = override_get_db

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/triage", json={"repo_id": 1, "issue_github_number": 999})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 404
    assert "999" in response.json()["detail"]


@pytest.mark.asyncio
async def test_triage_endpoint_returns_422_missing_required_field():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/triage", json={"repo_id": 1})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_triage_endpoint_returns_422_invalid_issue_number():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/triage", json={"repo_id": 1, "issue_github_number": 0})
    assert response.status_code == 422
