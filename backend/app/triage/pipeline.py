"""
Shared async triage pipeline called by both the API endpoint and Celery task.

Pipeline: retrieve() -> graph_expand() -> rerank() -> triage_with_llm()
"""
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.indexing.embedder import Embedder
from app.indexing.qdrant_store import QdrantStore
from app.models.orm import Issue
from app.retrieval import retrieve
from app.retrieval.graph import graph_expand
from app.retrieval.reranker import rerank
from app.triage.llm import triage_with_llm
from app.triage.schemas import TriageOutput

logger = logging.getLogger(__name__)

_RETRIEVAL_K = 30
_TRIAGE_TOP_N = 10


async def run_triage_pipeline(
    session: AsyncSession,
    repo_id: int,
    issue: Issue,
    embedder: Embedder,
    qdrant: QdrantStore,
    cfg: Settings,
) -> tuple[TriageOutput, int]:
    """
    Run the full triage pipeline for a single issue.

    Returns: (TriageOutput, latency_ms)
    """
    start_ms = int(time.monotonic() * 1000)
    query = f"{issue.title}\n{issue.body or ''}"

    results = await retrieve(
        session=session, qdrant=qdrant, embedder=embedder,
        repo_id=repo_id, query=query, k=_RETRIEVAL_K,
    )
    expanded = await graph_expand(session=session, results=results, repo_id=repo_id)
    reranked = await rerank(
        query=query,
        results=expanded,
        top_n=_TRIAGE_TOP_N,
        api_key=cfg.cohere_api_key,
        provider=cfg.reranker_provider,
    )
    triage_output = await triage_with_llm(
        title=issue.title,
        body=issue.body,
        labels=issue.labels or [],
        context_results=reranked,
        api_key=cfg.anthropic_api_key,
    )

    latency_ms = int(time.monotonic() * 1000) - start_ms
    logger.info(
        "Triage pipeline complete for issue #%d: confidence=%s latency=%dms",
        issue.github_number, triage_output.confidence, latency_ms,
    )
    return triage_output, latency_ms
