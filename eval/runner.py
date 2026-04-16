"""
Run the triage pipeline for a single issue and return an eval record.

Imports from backend/app via sys.path (set by run_eval.py before this module loads).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.indexing.embedder import Embedder
from app.indexing.qdrant_store import QdrantStore
from app.models.orm import Issue
from app.triage.pipeline import run_triage_pipeline

# metrics is in the same eval/ directory
from metrics import label_metrics


async def eval_issue(
    session: AsyncSession,
    repo_id: int,
    issue: Issue,
    embedder: Embedder,
    qdrant: QdrantStore,
    cfg: Settings,
) -> dict:
    """
    Run the full triage pipeline on one issue and return an eval result dict.

    Returns a dict with:
        github_number, actual_labels, predicted_labels, confidence,
        latency_ms, precision, recall, f1
    """
    actual_labels: list[str] = list(issue.labels or [])

    triage_output, latency_ms = await run_triage_pipeline(
        session=session,
        repo_id=repo_id,
        issue=issue,
        embedder=embedder,
        qdrant=qdrant,
        cfg=cfg,
    )

    predicted_labels = triage_output.labels
    m = label_metrics(predicted_labels, actual_labels)

    return {
        "github_number": issue.github_number,
        "actual_labels": actual_labels,
        "predicted_labels": predicted_labels,
        "confidence": triage_output.confidence,
        "latency_ms": latency_ms,
        **m,
    }
