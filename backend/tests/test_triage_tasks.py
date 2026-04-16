"""
Unit tests for the triage_issue Celery task.
All external calls (DB, Qdrant, LLM) are mocked.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.workers.triage_tasks import _async_triage_issue
from app.triage.schemas import TriageOutput


VALID_OUTPUT = TriageOutput(
    duplicate_of=None,
    labels=["bug", "performance"],
    relevant_files=["src/main.py"],
    suggested_assignees=[],
    confidence="high",
    reasoning="Clearly a regression.",
)


def make_mock_repo():
    repo = MagicMock()
    repo.id = 1
    repo.owner = "acme"
    repo.name = "myrepo"
    return repo


def make_mock_issue():
    issue = MagicMock()
    issue.id = 10
    issue.github_number = 42
    issue.title = "Server crashes on startup"
    issue.body = "Reproducible with --debug flag"
    issue.labels = ["bug"]
    return issue


def make_mock_session_cm(get_side_effect):
    """
    Return a context manager whose __aenter__ yields a session mock.
    `get_side_effect` is passed as the `side_effect` of session.get.
    """
    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=get_side_effect)
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)

    return mock_cm, mock_session


@pytest.mark.asyncio
async def test_repo_not_found_returns_error():
    """When session.get(Repo, repo_id) returns None, return repo_not_found error."""
    mock_cm, _ = make_mock_session_cm(get_side_effect=[None])

    with patch("app.workers.triage_tasks.AsyncSessionLocal", return_value=mock_cm):
        result = await _async_triage_issue(repo_id=99, issue_id=10)

    assert result == {"error": "repo_not_found"}


@pytest.mark.asyncio
async def test_issue_not_found_returns_error():
    """When repo exists but issue.get returns None, return issue_not_found error."""
    mock_repo = make_mock_repo()
    mock_cm, _ = make_mock_session_cm(get_side_effect=[mock_repo, None])

    with patch("app.workers.triage_tasks.AsyncSessionLocal", return_value=mock_cm):
        result = await _async_triage_issue(repo_id=1, issue_id=999)

    assert result == {"error": "issue_not_found"}


@pytest.mark.asyncio
async def test_happy_path_returns_expected_keys():
    """
    When both repo and issue exist and pipeline succeeds,
    the result dict must contain confidence, github_number, latency_ms, issue_id, labels.
    The triage result upsert must be committed.
    """
    mock_repo = make_mock_repo()
    mock_issue = make_mock_issue()
    mock_cm, mock_session = make_mock_session_cm(
        get_side_effect=[mock_repo, mock_issue]
    )

    with (
        patch("app.workers.triage_tasks.AsyncSessionLocal", return_value=mock_cm),
        patch(
            "app.workers.triage_tasks.run_triage_pipeline",
            new_callable=AsyncMock,
            return_value=(VALID_OUTPUT, 123),
        ),
        patch("app.workers.triage_tasks.embedder_from_settings"),
        patch("app.workers.triage_tasks.QdrantStore"),
    ):
        result = await _async_triage_issue(repo_id=1, issue_id=10)

    assert result["confidence"] == "high"
    assert result["github_number"] == 42
    assert result["issue_id"] == 10
    assert result["labels"] == ["bug", "performance"]
    assert isinstance(result["latency_ms"], int)
    mock_session.execute.assert_awaited_once()
    mock_session.commit.assert_awaited_once()
