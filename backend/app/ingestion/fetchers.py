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

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.github_client import GitHubClient
from app.models.orm import Commit, File, Issue, PullRequest, Relationship, Repo

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
            "body": item.get("body"),
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


async def upsert_relationship(
    session: AsyncSession,
    repo_id: int,
    source_type: str,
    source_id: int,
    target_type: str,
    target_id: int,
    edge_type: str,
) -> None:
    """Insert a graph edge, silently skip if it already exists."""
    stmt = (
        insert(Relationship)
        .values(
            repo_id=repo_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            edge_type=edge_type,
        )
        .on_conflict_do_nothing(constraint="uq_relationships")
    )
    await session.execute(stmt)


async def fetch_and_store_pull_requests(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
) -> int:
    """
    Fetch all PRs and upsert into pull_requests table.

    Also:
    - Extracts linked issue numbers from PR body (closes/fixes/resolves #N)
    - Creates issue_pr graph edges for each linked issue found in our DB
    - Fetches PR file list and creates pr_file edges (creating File stubs if needed)

    Returns: count of PRs stored.
    """
    from sqlalchemy import select as sa_select

    path = f"/repos/{repo.owner}/{repo.name}/pulls"
    params = {"state": "all", "sort": "created", "direction": "asc"}

    count = 0
    async for item in client.paginate(path, params):
        linked_numbers = _extract_linked_issues(item.get("body"))

        data = {
            "repo_id": repo.id,
            "github_number": item["number"],
            "title": item["title"],
            "body": item.get("body"),
            "state": item["state"],
            "author": item["user"]["login"],
            "merged_at": _parse_dt(item.get("merged_at")),
            "linked_issue_numbers": linked_numbers,
            "created_at": _parse_dt(item["created_at"]),
        }

        stmt = (
            insert(PullRequest)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_prs_repo_number",
                set_={
                    "title": data["title"],
                    "body": data["body"],
                    "state": data["state"],
                    "merged_at": data["merged_at"],
                    "linked_issue_numbers": data["linked_issue_numbers"],
                },
            )
            .returning(PullRequest.id)
        )
        result = await session.execute(stmt)
        pr_id = result.scalar_one()

        # issue_pr edges: find each linked issue in our DB and create an edge
        for issue_number in linked_numbers:
            issue_result = await session.execute(
                sa_select(Issue.id).where(
                    Issue.repo_id == repo.id,
                    Issue.github_number == issue_number,
                )
            )
            issue_id = issue_result.scalar_one_or_none()
            if issue_id:
                await upsert_relationship(
                    session,
                    repo_id=repo.id,
                    source_type="issue",
                    source_id=issue_id,
                    target_type="pull_request",
                    target_id=pr_id,
                    edge_type="issue_pr",
                )

        # pr_file edges: fetch the list of files this PR changed
        files_path = f"/repos/{repo.owner}/{repo.name}/pulls/{item['number']}/files"
        async for file_item in client.paginate(files_path):
            # Create File stub rows on the fly so we can store the pr_file edge
            file_stmt = (
                insert(File)
                .values(
                    repo_id=repo.id,
                    path=file_item["filename"],
                    language=None,
                    content_hash=None,
                    last_indexed_at=None,
                )
                .on_conflict_do_nothing(constraint="uq_files_repo_path")
                .returning(File.id)
            )
            file_result = await session.execute(file_stmt)
            file_id = file_result.scalar_one_or_none()

            if file_id is None:
                # Row already existed — fetch its id
                existing = await session.execute(
                    sa_select(File.id).where(
                        File.repo_id == repo.id,
                        File.path == file_item["filename"],
                    )
                )
                file_id = existing.scalar_one()

            await upsert_relationship(
                session,
                repo_id=repo.id,
                source_type="pull_request",
                source_id=pr_id,
                target_type="file",
                target_id=file_id,
                edge_type="pr_file",
            )

        count += 1

    await session.commit()
    logger.info("Stored %d PRs for %s/%s", count, repo.owner, repo.name)
    return count
