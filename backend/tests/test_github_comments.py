"""Unit tests for the GitHub comments client. All HTTP calls are mocked."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.github.comments import post_issue_comment


@pytest.mark.asyncio
async def test_post_issue_comment_returns_comment_url():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "id": 1234567890,
        "html_url": "https://github.com/owner/repo/issues/42#issuecomment-1234567890",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.github.comments.get_installation_token", AsyncMock(return_value="tok_abc")), \
         patch("app.github.comments.httpx.AsyncClient", return_value=mock_client):
        url = await post_issue_comment(
            owner="owner",
            repo="repo",
            issue_number=42,
            body="## Comment body",
            installation_id=99,
        )

    assert url == "https://github.com/owner/repo/issues/42#issuecomment-1234567890"


@pytest.mark.asyncio
async def test_post_issue_comment_sends_correct_request():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {
        "html_url": "https://github.com/owner/repo/issues/1#issuecomment-999",
    }

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.github.comments.get_installation_token", AsyncMock(return_value="tok_xyz")), \
         patch("app.github.comments.httpx.AsyncClient", return_value=mock_client):
        await post_issue_comment(
            owner="myorg",
            repo="myrepo",
            issue_number=1,
            body="Test comment",
            installation_id=42,
        )

    mock_client.post.assert_awaited_once()
    call_args = mock_client.post.call_args
    assert "myorg/myrepo/issues/1/comments" in call_args.args[0]
    assert call_args.kwargs["json"] == {"body": "Test comment"}
    assert "tok_xyz" in call_args.kwargs["headers"]["Authorization"]


@pytest.mark.asyncio
async def test_post_issue_comment_uses_installation_token():
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json.return_value = {"html_url": "https://github.com/o/r/issues/1#issuecomment-1"}

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    mock_get_token = AsyncMock(return_value="installation-token-here")

    with patch("app.github.comments.get_installation_token", mock_get_token), \
         patch("app.github.comments.httpx.AsyncClient", return_value=mock_client):
        await post_issue_comment("o", "r", 1, "body", installation_id=77)

    mock_get_token.assert_awaited_once_with(77)


@pytest.mark.asyncio
async def test_post_issue_comment_propagates_http_error():
    import httpx

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "403 Forbidden",
        request=MagicMock(),
        response=MagicMock(),
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=mock_response)

    with patch("app.github.comments.get_installation_token", AsyncMock(return_value="tok")), \
         patch("app.github.comments.httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await post_issue_comment("o", "r", 1, "body", installation_id=1)
