"""
Celery task for incremental indexing — only processes new/unindexed content.

Triggered on GitHub push events. Uses the incremental=True flag on both
indexers to skip content that already has Qdrant vectors.
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.github_auth import get_installation_token
from app.indexing.embedder import embedder_from_settings
from app.indexing.pipeline import index_repo_discussions, index_repo_files
from app.indexing.qdrant_store import QdrantStore
from app.ingestion.github_client import GitHubClient
from app.models.orm import Repo
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _async_incremental_index(repo_id: int) -> dict:
    embedder = embedder_from_settings()
    qdrant = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension, api_key=settings.qdrant_api_key)
    await qdrant.ensure_collections()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Repo).where(Repo.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            logger.error("Repo id=%d not found — skipping incremental index", repo_id)
            return {"error": "repo_not_found"}

        logger.info(
            "Starting incremental index for %s/%s (id=%d)", repo.owner, repo.name, repo_id
        )

        token = await get_installation_token(repo.installation_id)
        async with GitHubClient(token=token) as client:
            repo_data = await client.get(f"/repos/{repo.owner}/{repo.name}")
            default_branch = repo_data.get("default_branch", "main")

            files_count = await index_repo_files(
                session, repo, client, embedder, qdrant,
                default_branch=default_branch, incremental=True,
            )

        discussion_counts = await index_repo_discussions(
            session, repo, embedder, qdrant, incremental=True
        )

        summary = {
            "repo_id": repo_id,
            "files_indexed": files_count,
            **discussion_counts,
        }
        logger.info(
            "Incremental index complete for %s/%s: %s", repo.owner, repo.name, summary
        )
        return summary


@celery_app.task(name="indexing.incremental_index_repo", bind=True, max_retries=3)
def incremental_index_repo(self, repo_id: int) -> dict:
    """
    Celery task: incrementally index only new/unindexed content for a repo.

    Called on push events. Skips already-indexed files and discussions.
    Retries up to 3 times on transient errors.
    """
    try:
        return asyncio.run(_async_incremental_index(repo_id))
    except Exception as exc:
        logger.exception("Incremental index failed for repo_id=%d: %s", repo_id, exc)
        raise self.retry(exc=exc, countdown=60)
