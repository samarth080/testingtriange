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
    Return (context_manager, session_mock) where context_manager wraps session_mock.
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


def make_worker_session_patch(mock_cm):
    """
    Return a mock for make_worker_session so that make_worker_session()() returns mock_cm.
    The code does: async with make_worker_session()() as session
    """
    mock_factory = MagicMock(return_value=mock_cm)
    return MagicMock(return_value=mock_factory)


@pytest.mark.asyncio
async def test_repo_not_found_returns_error():
    """When session.get(Repo, repo_id) returns None, return repo_not_found error."""
    mock_cm, _ = make_mock_session_cm(get_side_effect=[None])
    mock_make_session = make_worker_session_patch(mock_cm)

    with patch("app.workers.triage_tasks.make_worker_session", mock_make_session):
        result = await _async_triage_issue(repo_id=99, issue_id=10)

    assert result == {"error": "repo_not_found"}


@pytest.mark.asyncio
async def test_issue_not_found_returns_error():
    """When repo exists but issue.get returns None, return issue_not_found error."""
    mock_repo = make_mock_repo()
    mock_cm, _ = make_mock_session_cm(get_side_effect=[mock_repo, None])
    mock_make_session = make_worker_session_patch(mock_cm)

    with patch("app.workers.triage_tasks.make_worker_session", mock_make_session):
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
    mock_make_session = make_worker_session_patch(mock_cm)
    mock_cache = AsyncMock()

    with (
        patch("app.workers.triage_tasks.make_worker_session", mock_make_session),
        patch("app.workers.triage_tasks.run_triage_pipeline",
              new_callable=AsyncMock, return_value=(VALID_OUTPUT, 123)),
        patch("app.workers.triage_tasks.embedder_from_settings"),
        patch("app.workers.triage_tasks.QdrantStore"),
        patch("app.workers.triage_tasks.SemanticCache", return_value=mock_cache),
    ):
        result = await _async_triage_issue(repo_id=1, issue_id=10)

    assert result["confidence"] == "high"
    assert result["github_number"] == 42
    assert result["issue_id"] == 10
    assert result["labels"] == ["bug", "performance"]
    assert isinstance(result["latency_ms"], int)
    assert mock_session.execute.await_count >= 1
    assert mock_session.commit.await_count >= 1


# ---------------------------------------------------------------------------
# Comment posting tests (Task 3 additions)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_async_triage_issue_posts_comment_on_success():
    """After a successful triage, a comment should be posted."""
    mock_repo = MagicMock()
    mock_repo.owner = "myorg"
    mock_repo.name = "myrepo"
    mock_repo.installation_id = 99

    mock_issue = MagicMock()
    mock_issue.github_number = 42
    mock_issue.title = "Bug"
    mock_issue.body = "Details"
    mock_issue.labels = []

    mock_output = TriageOutput(confidence="high", reasoning="Clear bug.")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=[mock_repo, mock_issue])
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_make_session = make_worker_session_patch(mock_cm)
    mock_cache = AsyncMock()

    with patch("app.workers.triage_tasks.make_worker_session", mock_make_session), \
         patch("app.workers.triage_tasks.run_triage_pipeline", AsyncMock(return_value=(mock_output, 100))), \
         patch("app.workers.triage_tasks.embedder_from_settings", MagicMock()), \
         patch("app.workers.triage_tasks.QdrantStore", MagicMock()), \
         patch("app.workers.triage_tasks.SemanticCache", return_value=mock_cache), \
         patch("app.workers.triage_tasks.post_issue_comment", AsyncMock(return_value="https://github.com/myorg/myrepo/issues/42#issuecomment-1")) as mock_comment:
        result = await _async_triage_issue(repo_id=1, issue_id=1)

    mock_comment.assert_awaited_once()
    call_kwargs = mock_comment.call_args.kwargs
    assert call_kwargs["owner"] == "myorg"
    assert call_kwargs["repo"] == "myrepo"
    assert call_kwargs["issue_number"] == 42
    assert call_kwargs["installation_id"] == 99
    assert result["comment_url"] == "https://github.com/myorg/myrepo/issues/42#issuecomment-1"


@pytest.mark.asyncio
async def test_async_triage_issue_continues_if_comment_fails():
    """If posting the comment raises, the task should still return success (not raise)."""
    import httpx

    mock_repo = MagicMock()
    mock_repo.owner = "o"
    mock_repo.name = "r"
    mock_repo.installation_id = 1

    mock_issue = MagicMock()
    mock_issue.github_number = 1
    mock_issue.title = "Bug"
    mock_issue.body = None
    mock_issue.labels = []

    mock_output = TriageOutput(confidence="low", reasoning="Unclear.")

    mock_session = AsyncMock()
    mock_session.get = AsyncMock(side_effect=[mock_repo, mock_issue])
    mock_session.execute = AsyncMock()
    mock_session.commit = AsyncMock()

    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_make_session = make_worker_session_patch(mock_cm)
    mock_cache = AsyncMock()

    with patch("app.workers.triage_tasks.make_worker_session", mock_make_session), \
         patch("app.workers.triage_tasks.run_triage_pipeline", AsyncMock(return_value=(mock_output, 50))), \
         patch("app.workers.triage_tasks.embedder_from_settings", MagicMock()), \
         patch("app.workers.triage_tasks.QdrantStore", MagicMock()), \
         patch("app.workers.triage_tasks.SemanticCache", return_value=mock_cache), \
         patch("app.workers.triage_tasks.post_issue_comment", AsyncMock(side_effect=httpx.HTTPStatusError("403", request=MagicMock(), response=MagicMock()))):
        result = await _async_triage_issue(repo_id=1, issue_id=1)

    # Task should still return normally — comment failure is non-fatal
    assert result["confidence"] == "low"
    assert "issue_id" in result
    assert "comment_url" not in result
