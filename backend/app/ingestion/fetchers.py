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

from sqlalchemy import select as sa_select
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


async def fetch_and_store_commits(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
) -> int:
    """
    Fetch commits from the last 2 years and upsert into the commits table.

    GitHub's commit list endpoint returns basic info (sha, message, author, date).
    changed_files is left empty here; it gets populated in Day 3 when we index
    files and can derive commit→file relationships from the tree.

    Returns: count of commits stored.
    """
    path = f"/repos/{repo.owner}/{repo.name}/commits"
    params = {"since": BACKFILL_SINCE.strftime("%Y-%m-%dT%H:%M:%SZ")}

    count = 0
    async for item in client.paginate(path, params):
        commit_data = item.get("commit", {})
        author_data = commit_data.get("author", {})

        # Prefer the GitHub login over git author name (login is more useful for attribution)
        author_login = (item.get("author") or {}).get("login") or author_data.get("name", "unknown")

        data = {
            "repo_id": repo.id,
            "sha": item["sha"],
            "message": commit_data.get("message", ""),
            "author": author_login,
            "committed_at": _parse_dt(author_data.get("date")),
            "changed_files": [],  # Populated in Day 3 during file indexing
        }

        stmt = (
            insert(Commit)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_commits_repo_sha",
                set_={
                    "message": data["message"],
                    "author": data["author"],
                },
            )
        )
        await session.execute(stmt)
        count += 1

    await session.commit()
    logger.info("Stored %d commits for %s/%s", count, repo.owner, repo.name)
    return count


# Extension → language name mapping
_EXT_TO_LANG: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
    ".rb": "ruby",
    ".md": "markdown",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".json": "json",
    ".toml": "toml",
    ".sh": "shell",
    ".sql": "sql",
}


def _detect_language(path: str) -> str | None:
    """Return a language name based on file extension, or None if unknown."""
    from pathlib import PurePosixPath
    suffix = PurePosixPath(path).suffix.lower()
    return _EXT_TO_LANG.get(suffix)


async def fetch_and_store_files(
    session: AsyncSession,
    repo: Repo,
    client: GitHubClient,
    default_branch: str = "main",
) -> int:
    """
    Fetch the full repo file tree (recursive) and upsert File stubs.

    Uses GET /repos/{owner}/{repo}/git/trees/{branch}?recursive=1
    which returns all blob (file) and tree (directory) entries in one call.
    We store only blob entries and detect language from extension.

    content_hash and last_indexed_at are left None — they are populated
    in Day 3 when we download and chunk file content.

    Returns: count of files stored.
    """
    tree_data = await client.get(
        f"/repos/{repo.owner}/{repo.name}/git/trees/{default_branch}?recursive=1"
    )

    count = 0
    for entry in tree_data.get("tree", []):
        if entry.get("type") != "blob":
            continue  # Skip directories

        data = {
            "repo_id": repo.id,
            "path": entry["path"],
            "language": _detect_language(entry["path"]),
            "content_hash": None,
            "last_indexed_at": None,
        }

        stmt = (
            insert(File)
            .values(**data)
            .on_conflict_do_update(
                constraint="uq_files_repo_path",
                set_={"language": data["language"]},
            )
        )
        await session.execute(stmt)
        count += 1

    await session.commit()
    logger.info("Stored %d files for %s/%s", count, repo.owner, repo.name)
    return count
