"""
GitHub data fetchers — one function per entity type.

Each function:
1. Calls GitHubClient.paginate() to get all pages from GitHub API
2. Upserts records into Postgres using INSERT ... ON CONFLICT DO UPDATE
3. Returns count of records processed

Date cutoff: we pass since=TWO_YEARS_AGO to GitHub for issues/commits.
PRs and files don't support a 'since' filter so we fetch all and rely on
upsert idempotency if re-run.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.github_client import GitHubClient
from app.models.orm import Commit, File, Issue, PullRequest, Relationship, Repo

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Fetch issues/commits created in the last 2 years
BACKFILL_SINCE = datetime.now(tz=timezone.utc) - timedelta(days=730)

# Regex to extract linked issue numbers from PR bodies
_LINKED_RE = re.compile(r"(?:closes?|fixes?|resolves?)\s+#(\d+)", re.IGNORECASE)


def _parse_dt(s: str | None) -> datetime | None:
    """Parse an ISO-8601 UTC string from GitHub ('2025-01-15T10:00:00Z') to datetime."""
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _extract_linked_issues(body: str | None) -> list[int]:
    """Return issue numbers referenced in a PR body via closes/fixes/resolves patterns."""
    if not body:
        return []
    return [int(n) for n in _LINKED_RE.findall(body)]


async def fetch_and_store_issues(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
) -> int:
    """
    Fetch all issues for a repo (since 2 years ago) and upsert into the issues table.

    Skips items that are actually PRs (GitHub's /issues endpoint returns both;
    PR items carry a 'pull_request' key).

    Returns: count of issues stored.
    """
    path = f"/repos/{repo.owner}/{repo.name}/issues"
    params = {
        "state": "all",
        "since": BACKFILL_SINCE.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sort": "created",
        "direction": "asc",
    }

    count = 0
    async for item in client.paginate(path, params):
        # GitHub /issues returns PRs too — skip them
        if item.get("pull_request"):
            continue

        data = {
            "repo_id": repo.id,
            "github_number": item["number"],
            "title": item["title"],
            "body": item.get("body") or "",
            "state": item["state"],
            "author": item["user"]["login"],
            "labels": [label["name"] for label in item.get("labels", [])],
            "created_at": _parse_dt(item["created_at"]),
            "closed_at": _parse_dt(item.get("closed_at")),
        }

        stmt = (
            insert(Issue)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_issues_repo_number",
                set_={
                    "title": data["title"],
                    "body": data["body"],
                    "state": data["state"],
                    "labels": data["labels"],
                    "closed_at": data["closed_at"],
                },
            )
        )
        await session.execute(stmt)
        count += 1

    await session.commit()
    logger.info("Stored %d issues for %s/%s", count, repo.owner, repo.name)
    return count
