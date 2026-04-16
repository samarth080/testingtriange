"""
Load historical labeled issues from Postgres for eval.

Issues with at least one label and matching `state` are used as ground truth:
the labels they actually received in GitHub are what the pipeline should predict.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

# Loaded via sys.path from run_eval.py
from app.models.orm import Issue


async def load_eval_issues(
    session: AsyncSession,
    repo_id: int,
    limit: int = 50,
    state: str = "closed",
) -> list[Issue]:
    """
    Fetch labeled historical issues to use as eval ground truth.

    Filters:
    - repo_id matches
    - state matches (or all states if state == "all")
    - labels array is non-empty (jsonb_array_length > 0)

    Ordered by created_at DESC so the most recent issues are evaluated first.
    """
    stmt = select(Issue).where(Issue.repo_id == repo_id)

    if state != "all":
        stmt = stmt.where(Issue.state == state)

    # jsonb_array_length returns NULL for NULL values — use coalesce to treat NULL as 0
    stmt = stmt.where(func.jsonb_array_length(Issue.labels) > 0)
    stmt = stmt.order_by(Issue.created_at.desc()).limit(limit)

    result = await session.execute(stmt)
    return list(result.scalars().all())
