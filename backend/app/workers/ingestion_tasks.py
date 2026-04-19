"""
Celery tasks for GitHub data ingestion.

Task hierarchy:
  backfill_repo(repo_id)
    └─ runs all four fetchers sequentially inside an async context

Design: Celery workers are synchronous, but our fetchers are async.
We bridge this with asyncio.run() — the same pattern used in Alembic's env.py.
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.database import make_worker_session
from app.core.github_auth import get_installation_token
from app.ingestion.github_client import GitHubClient
from app.ingestion.fetchers import (
    fetch_and_store_commits,
    fetch_and_store_files,
    fetch_and_store_issues,
    fetch_and_store_pull_requests,
)
from app.models.orm import Repo
from app.workers.celery_app import celery_app
from app.workers.indexing_tasks import index_repo

logger = logging.getLogger(__name__)


async def _get_default_branch(client: GitHubClient, owner: str, name: str) -> str:
    """Fetch the repo's default branch name from GitHub API."""
    data = await client.get(f"/repos/{owner}/{name}")
    return data.get("default_branch", "main")


async def _async_backfill_repo(repo_id: int) -> dict:
    """
    Async implementation of the backfill task.

    Fetches issues → PRs → commits → files in order.
    Issues must come before PRs so issue_pr edges can reference existing issue rows.
    Returns a summary dict with counts per entity type.
    """
    async with make_worker_session()() as session:
        result = await session.execute(select(Repo).where(Repo.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            logger.error("Repo id=%d not found — skipping backfill", repo_id)
            return {"error": "repo_not_found"}

        logger.info("Starting backfill for %s/%s (id=%d)", repo.owner, repo.name, repo_id)

        token = await get_installation_token(repo.installation_id)
        async with GitHubClient(token=token) as client:
            default_branch = await _get_default_branch(client, repo.owner, repo.name)

            # Run fetchers — issues before PRs (issue_pr edge creation dependency)
            issues_count = await fetch_and_store_issues(session, repo, client)
            prs_count = await fetch_and_store_pull_requests(session, repo, client)
            commits_count = await fetch_and_store_commits(session, repo, client)
            files_count = await fetch_and_store_files(session, repo, client, default_branch=default_branch)

        # Mark backfill complete
        repo.backfill_status = "done"
        await session.commit()

        summary = {
            "repo_id": repo_id,
            "issues": issues_count,
            "prs": prs_count,
            "commits": commits_count,
            "files": files_count,
        }
        logger.info("Backfill complete for %s/%s: %s", repo.owner, repo.name, summary)
        return summary


@celery_app.task(name="ingestion.backfill_repo", bind=True, max_retries=3)
def backfill_repo(self, repo_id: int) -> dict:
    """
    Celery task: fetch and store all GitHub data for a repo.

    Retries up to 3 times on transient errors (rate limits, network blips).
    On success, enqueues index_repo to chunk and embed the stored data.
    bind=True gives access to self.retry().
    """
    try:
        result = asyncio.run(_async_backfill_repo(repo_id))
        index_repo.delay(repo_id)
        return result
    except Exception as exc:
        logger.exception("Backfill failed for repo_id=%d: %s", repo_id, exc)
        raise self.retry(exc=exc, countdown=60)
