"""
GitHub Issues comment client.

Posts a comment to a GitHub issue using an installation access token.
The token is fetched fresh on each call — tokens are valid for 1 hour but
we don't cache them here to keep this module stateless and easy to test.
"""
import logging

import httpx

from app.core.github_auth import get_installation_token

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_GITHUB_API_VERSION = "2022-11-28"


async def post_issue_comment(
    owner: str,
    repo: str,
    issue_number: int,
    body: str,
    installation_id: int,
) -> str:
    """
    Post a comment to a GitHub issue and return the comment's html_url.

    Args:
        owner:           Repository owner (user or org login).
        repo:            Repository name.
        issue_number:    GitHub issue number (the #N shown in the UI).
        body:            Markdown comment body to post.
        installation_id: GitHub App installation ID — used to obtain a token.

    Returns:
        The html_url of the created comment.

    Raises:
        httpx.HTTPStatusError: If GitHub returns a non-2xx response.
    """
    token = await get_installation_token(installation_id)
    url = f"{_GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/comments"

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": _GITHUB_API_VERSION,
            },
            json={"body": body},
        )
        response.raise_for_status()
        data = response.json()

    comment_url: str = data["html_url"]
    logger.info(
        "Posted triage comment on %s/%s#%d: %s",
        owner, repo, issue_number, comment_url,
    )
    return comment_url
