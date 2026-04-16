"""
Dashboard API endpoints — triage history and explainability.

GET /dashboard/repos                               — list all repos
GET /dashboard/repos/{repo_id}/results             — list triage results (latest 50)
GET /dashboard/repos/{repo_id}/results/{result_id} — full triage detail
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.orm import Issue, Repo, TriageResult

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/repos")
async def list_repos(session: AsyncSession = Depends(get_db)) -> list[dict]:
    """Return all repos ordered by most recently created."""
    result = await session.execute(select(Repo).order_by(desc(Repo.created_at)))
    repos = result.scalars().all()
    return [
        {
            "id": r.id,
            "owner": r.owner,
            "name": r.name,
            "backfill_status": r.backfill_status,
            "created_at": r.created_at.isoformat(),
        }
        for r in repos
    ]


@router.get("/repos/{repo_id}/results")
async def list_triage_results(
    repo_id: int,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    """Return the 50 most recent triage results for a repo, joined with issue metadata."""
    stmt = (
        select(TriageResult, Issue)
        .join(Issue, TriageResult.issue_id == Issue.id)
        .where(TriageResult.repo_id == repo_id)
        .order_by(desc(TriageResult.created_at))
        .limit(50)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {
            "id": tr.id,
            "issue_id": tr.issue_id,
            "github_number": issue.github_number,
            "title": issue.title,
            "confidence": tr.output.get("confidence"),
            "labels": tr.output.get("labels", []),
            "latency_ms": tr.latency_ms,
            "comment_url": tr.comment_url,
            "created_at": tr.created_at.isoformat(),
        }
        for tr, issue in rows
    ]


@router.get("/repos/{repo_id}/results/{result_id}")
async def get_triage_detail(
    repo_id: int,
    result_id: int,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """Return full triage output + issue metadata for one result."""
    stmt = (
        select(TriageResult, Issue)
        .join(Issue, TriageResult.issue_id == Issue.id)
        .where(TriageResult.repo_id == repo_id, TriageResult.id == result_id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Triage result not found")
    tr, issue = row
    return {
        "id": tr.id,
        "issue_id": tr.issue_id,
        "github_number": issue.github_number,
        "title": issue.title,
        "body": issue.body,
        "actual_labels": issue.labels or [],
        "confidence": tr.output.get("confidence"),
        "labels": tr.output.get("labels", []),
        "duplicate_of": tr.output.get("duplicate_of"),
        "relevant_files": tr.output.get("relevant_files", []),
        "suggested_assignees": tr.output.get("suggested_assignees", []),
        "reasoning": tr.output.get("reasoning", ""),
        "latency_ms": tr.latency_ms,
        "comment_url": tr.comment_url,
        "created_at": tr.created_at.isoformat(),
    }
