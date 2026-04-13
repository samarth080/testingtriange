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
