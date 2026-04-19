"""
POST /triage — on-demand synchronous triage endpoint.

Accepts repo_id + issue_github_number, runs the full triage pipeline,
stores the result in triage_results, and returns structured JSON.
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.indexing.embedder import embedder_from_settings
from app.indexing.qdrant_store import QdrantStore
from app.models.orm import Issue, TriageResult
from app.cache.semantic_cache import SemanticCache
from app.triage.pipeline import run_triage_pipeline

router = APIRouter(prefix="/triage", tags=["triage"])


class TriageRequest(BaseModel):
    repo_id: int
    issue_github_number: int = Field(..., ge=1)


@router.post("")
async def triage_endpoint(
    req: TriageRequest,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """
    Run the full triage pipeline for an issue and return structured JSON.

    Pipeline: retrieve -> graph expand -> rerank -> LLM triage -> store -> return
    """
    issue_result = await session.execute(
        select(Issue).where(
            Issue.repo_id == req.repo_id,
            Issue.github_number == req.issue_github_number,
        )
    )
    issue = issue_result.scalar_one_or_none()
    if not issue:
        raise HTTPException(
            status_code=404,
            detail=f"Issue #{req.issue_github_number} not found in repo {req.repo_id}",
        )

    embedder = embedder_from_settings()
    qdrant = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension, api_key=settings.qdrant_api_key)

    cache = SemanticCache(redis_url=settings.redis_url, ttl=settings.semantic_cache_ttl)
    try:
        triage_output, latency_ms = await run_triage_pipeline(
            session=session, repo_id=req.repo_id, issue=issue,
            embedder=embedder, qdrant=qdrant, cfg=settings, cache=cache,
        )
    finally:
        await cache.close()

    stmt = (
        pg_insert(TriageResult)
        .values(
            repo_id=req.repo_id,
            issue_id=issue.id,
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
        **triage_output.model_dump(),
        "latency_ms": latency_ms,
        "issue_github_number": issue.github_number,
    }
