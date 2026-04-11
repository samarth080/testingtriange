"""
GitHub App authentication helpers.

GitHub App auth flow:
1. Generate a short-lived JWT signed with the App's RSA private key (valid 10 min)
2. Use the JWT to call POST /app/installations/{installation_id}/access_tokens
3. The response contains an installation access token valid for 1 hour
4. Use the installation token for all API calls scoped to that repo

These tokens are used in Day 2 (backfill) and Day 6 (posting comments).
"""
import time
from pathlib import Path

import jwt

from app.core.config import settings


def _load_private_key() -> str:
    """Load the GitHub App RSA private key from the configured path."""
    key_path = Path(settings.github_private_key_path)
    if not key_path.exists():
        raise FileNotFoundError(
            f"GitHub App private key not found at {key_path}. "
            "Download it from your GitHub App settings page."
        )
    return key_path.read_text()


def create_github_jwt() -> str:
    """
    Create a JWT for GitHub App authentication.

    Signed with RS256 (RSA + SHA-256) using the App's private key.
    iat is backdated 60 seconds to account for clock drift between servers.
    exp is set 10 minutes from now (GitHub's maximum allowed).
    """
    now = int(time.time())
    private_key = _load_private_key()
    payload = {
        "iat": now - 60,   # Issued 60s ago — tolerate clock skew
        "exp": now + 600,  # Expires in 10 minutes
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    """
    Exchange a GitHub App JWT for an installation access token.

    The installation token grants permissions scoped to one installation
    (i.e., one org/user that installed the App). Valid for 1 hour.

    Used in: backfill tasks (Day 2), comment posting (Day 6).
    """
    import httpx

    app_jwt = create_github_jwt()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        return response.json()["token"]
