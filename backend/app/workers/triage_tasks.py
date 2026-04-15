"""
Celery task: run the full triage pipeline for a new issue.

  triage.triage_issue(repo_id, issue_id)
    Fetches repo + issue from Postgres, runs the triage pipeline,
    upserts result into triage_results, retries up to 3x on failure.
"""
import asyncio
import logging

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.indexing.embedder import embedder_from_settings
from app.indexing.qdrant_store import QdrantStore
from app.models.orm import Issue, Repo, TriageResult
from app.triage.pipeline import run_triage_pipeline
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _async_triage_issue(repo_id: int, issue_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        repo = await session.get(Repo, repo_id)
        if not repo:
            logger.error("Repo id=%d not found — skipping triage", repo_id)
            return {"error": "repo_not_found"}

        issue = await session.get(Issue, issue_id)
        if not issue:
            logger.error("Issue id=%d not found — skipping triage", issue_id)
            return {"error": "issue_not_found"}

        logger.info("Triaging issue #%d for %s/%s", issue.github_number, repo.owner, repo.name)

        embedder = embedder_from_settings()
        qdrant = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension)

        triage_output, latency_ms = await run_triage_pipeline(
            session=session, repo_id=repo_id, issue=issue,
            embedder=embedder, qdrant=qdrant, cfg=settings,
        )

        stmt = (
            pg_insert(TriageResult)
            .values(
                repo_id=repo_id,
                issue_id=issue_id,
                output=triage_output.model_dump(),
                latency_ms=latency_ms,
            )
            .on_conflict_do_update(
                constraint="uq_triage_results_issue",
                set_={
                    "output": triage_output.model_dump(),
                    "latency_ms": latency_ms,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()

        return {
            "issue_id": issue_id,
            "github_number": issue.github_number,
            "confidence": triage_output.confidence,
            "labels": triage_output.labels,
            "latency_ms": latency_ms,
        }


@celery_app.task(name="triage.triage_issue", bind=True, max_retries=3)
def triage_issue(self, repo_id: int, issue_id: int) -> dict:
    """
    Celery task: full triage pipeline for a new or reopened issue.

    Retries up to 3 times on transient failures. bind=True gives access to self.retry().
    """
    try:
        return asyncio.run(_async_triage_issue(repo_id, issue_id))
    except Exception as exc:
        logger.exception("Triage failed for issue_id=%d: %s", issue_id, exc)
        raise self.retry(exc=exc, countdown=30)
