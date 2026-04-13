"""
GitHub REST API client with transparent Link-header pagination.

Usage (async context manager — preferred):
    async with GitHubClient(token=await get_installation_token(installation_id)) as client:
        async for issue in client.paginate("/repos/owner/repo/issues", {"state": "all"}):
            process(issue)

Usage (explicit close — backward-compatible):
    client = GitHubClient(token=token)
    async for issue in client.paginate("/repos/owner/repo/issues"):
        process(issue)
    await client.aclose()

Pagination: GitHub returns a Link header like:
    <https://api.github.com/...?page=2>; rel="next"
We follow it automatically, yielding items from all pages.
"""
import asyncio
import re
import time
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
    - Connection-pool reuse (single httpx.AsyncClient per GitHubClient instance)
    - Rate-limit retry on 403/429 with Retry-After / X-RateLimit-Reset headers
    """

    def __init__(self, token: str) -> None:
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self._client = httpx.AsyncClient(headers=headers, base_url=BASE_URL)

    # ── Async context manager support ────────────────────────────────────────

    async def __aenter__(self) -> "GitHubClient":
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_with_rate_limit_retry(
        self, url: str, **kwargs: Any
    ) -> httpx.Response:
        """
        Perform a GET request, retrying once if GitHub rate-limits us (403/429).

        Reads Retry-After (seconds) or X-RateLimit-Reset (Unix timestamp) to
        determine how long to sleep before the single retry.
        """
        response = await self._client.get(url, **kwargs)

        if response.status_code in (403, 429):
            sleep_seconds = self._parse_retry_after(response)
            await asyncio.sleep(sleep_seconds)
            response = await self._client.get(url, **kwargs)

        response.raise_for_status()
        return response

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float:
        """Return seconds to sleep based on Retry-After or X-RateLimit-Reset headers."""
        retry_after = response.headers.get("Retry-After")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass

        reset_ts = response.headers.get("X-RateLimit-Reset")
        if reset_ts is not None:
            try:
                return max(0.0, float(reset_ts) - time.time())
            except ValueError:
                pass

        # Fallback: 60 s is a safe default
        return 60.0

    # ── Public API ────────────────────────────────────────────────────────────

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
        url: str | None = path

        while url:
            response = await self._get_with_rate_limit_retry(url, params=request_params)
            data = response.json()
            if not isinstance(data, list):
                raise ValueError(
                    f"Expected list from paginate, got {type(data).__name__}: {data!r}"
                )
            for item in data:
                yield item
            url = _parse_next_url(response.headers.get("Link"))
            # After the first request, pagination URL carries all params already
            request_params = {}

    async def get(self, path: str) -> dict[str, Any]:
        """Fetch a single resource (non-paginated)."""
        response = await self._get_with_rate_limit_retry(path)
        return response.json()
