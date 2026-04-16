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
from app.github.comments import post_issue_comment
from app.indexing.embedder import embedder_from_settings
from app.indexing.qdrant_store import QdrantStore
from app.models.orm import Issue, Repo, TriageResult
from app.triage.formatter import format_triage_comment
from app.cache.semantic_cache import SemanticCache
from app.triage.pipeline import run_triage_pipeline
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_CONFIDENCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}


def _meets_confidence_threshold(output_confidence: str, min_confidence: str) -> bool:
    """Return True if output_confidence >= min_confidence in the low→high ranking."""
    return _CONFIDENCE_RANK.get(output_confidence, 0) >= _CONFIDENCE_RANK.get(min_confidence, 0)


async def _async_triage_issue(repo_id: int, issue_id: int) -> dict:
    async with AsyncSessionLocal() as session:
        repo = await session.get(Repo, repo_id)
        if not repo:
            # Not retrying: if the repo doesn't exist at task run time, retrying won't help.
            # The delay() call in webhooks.py only fires after a successful DB commit.
            logger.error("Repo id=%d not found — skipping triage", repo_id)
            return {"error": "repo_not_found"}

        issue = await session.get(Issue, issue_id)
        if not issue:
            # Not retrying: if the issue doesn't exist at task run time, retrying won't help.
            # The delay() call in webhooks.py only fires after a successful DB commit.
            logger.error("Issue id=%d not found — skipping triage", issue_id)
            return {"error": "issue_not_found"}

        logger.info("Triaging issue #%d for %s/%s", issue.github_number, repo.owner, repo.name)

        embedder = embedder_from_settings()
        qdrant = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension)
        cache = SemanticCache(redis_url=settings.redis_url, ttl=settings.semantic_cache_ttl)

        try:
            triage_output, latency_ms = await run_triage_pipeline(
                session=session, repo_id=repo_id, issue=issue,
                embedder=embedder, qdrant=qdrant, cfg=settings, cache=cache,
            )
        finally:
            await cache.close()

        output_dict = triage_output.model_dump()
        stmt = (
            pg_insert(TriageResult)
            .values(
                repo_id=repo_id,
                issue_id=issue_id,
                output=output_dict,
                latency_ms=latency_ms,
            )
            .on_conflict_do_update(
                constraint="uq_triage_results_issue",
                set_={
                    "output": output_dict,
                    "latency_ms": latency_ms,
                },
            )
        )
        await session.execute(stmt)
        await session.commit()

        result = {
            "issue_id": issue_id,
            "github_number": issue.github_number,
            "confidence": triage_output.confidence,
            "labels": triage_output.labels,
            "latency_ms": latency_ms,
        }

        # Post comment to GitHub only if confidence meets the configured threshold.
        # Triage result is always saved to DB regardless of confidence.
        if _meets_confidence_threshold(triage_output.confidence, settings.min_confidence):
            try:
                comment_body = format_triage_comment(triage_output, issue.github_number)
                comment_url = await post_issue_comment(
                    owner=repo.owner,
                    repo=repo.name,
                    issue_number=issue.github_number,
                    body=comment_body,
                    installation_id=repo.installation_id,
                )
                from sqlalchemy import update
                await session.execute(
                    update(TriageResult)
                    .where(TriageResult.issue_id == issue_id)
                    .values(comment_url=comment_url)
                )
                await session.commit()
                result["comment_url"] = comment_url
            except Exception as exc:
                logger.warning(
                    "Failed to post triage comment for issue #%d: %s",
                    issue.github_number, exc,
                )
        else:
            logger.info(
                "Skipping comment for issue #%d: confidence=%s below min=%s",
                issue.github_number, triage_output.confidence, settings.min_confidence,
            )

        return result


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
        raise self.retry(exc=exc, countdown=60)  # 60s matches project-wide retry convention
