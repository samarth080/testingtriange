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
