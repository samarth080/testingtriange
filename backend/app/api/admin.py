"""
Admin endpoints for triggering background tasks manually.

No auth — intended for internal use via Render Shell or curl from a trusted source.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.orm import Repo
from app.workers.ingestion_tasks import backfill_repo
from app.workers.indexing_tasks import index_repo

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/backfill/{repo_id}")
async def trigger_backfill(repo_id: int, db: AsyncSession = Depends(get_db)):
    """Enqueue backfill_repo task (fetches GitHub data then auto-triggers index_repo)."""
    repo = await db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repo {repo_id} not found")
    task = backfill_repo.delay(repo_id)
    return {"task_id": task.id, "repo": f"{repo.owner}/{repo.name}"}


@router.post("/index/{repo_id}")
async def trigger_index(repo_id: int, db: AsyncSession = Depends(get_db)):
    """Enqueue index_repo task (chunk, embed, store in Qdrant)."""
    repo = await db.get(Repo, repo_id)
    if not repo:
        raise HTTPException(status_code=404, detail=f"Repo {repo_id} not found")
    task = index_repo.delay(repo_id)
    return {"task_id": task.id, "repo": f"{repo.owner}/{repo.name}"}


@router.get("/repos")
async def list_repos(db: AsyncSession = Depends(get_db)):
    """List all repos in the database with their IDs."""
    from sqlalchemy import select
    result = await db.execute(select(Repo))
    repos = result.scalars().all()
    return [{"id": r.id, "owner": r.owner, "name": r.name, "backfill_status": r.backfill_status} for r in repos]
