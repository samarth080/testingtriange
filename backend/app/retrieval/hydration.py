"""Hydrate RRF-ranked qdrant_point_ids into SearchResult objects."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk, File, Issue, PullRequest
from app.retrieval import SearchResult


async def hydrate(
    session: AsyncSession,
    ranked: list[tuple[str, float]],
) -> list[SearchResult]:
    """
    Fetch chunk rows and their source entities for a ranked list of Qdrant point IDs.

    Args:
        session: Async SQLAlchemy session.
        ranked:  List of (qdrant_point_id, rrf_score) in ranked order.

    Returns:
        SearchResult list in the same ranked order. Chunks missing from
        Postgres (e.g. stale point IDs) are silently skipped.
    """
    if not ranked:
        return []

    point_ids = [pid for pid, _ in ranked]
    score_map = {pid: score for pid, score in ranked}

    # ── 1. Batch-fetch chunks ────────────────────────────────────────────────
    result = await session.execute(
        select(Chunk).where(Chunk.qdrant_point_id.in_(point_ids))
    )
    chunks: dict[str, Chunk] = {
        c.qdrant_point_id: c for c in result.scalars().all()
    }

    # ── 2. Group source IDs by type ──────────────────────────────────────────
    file_ids = {c.source_id for c in chunks.values() if c.source_type == "file"}
    issue_ids = {c.source_id for c in chunks.values() if c.source_type == "issue"}
    pr_ids = {c.source_id for c in chunks.values() if c.source_type == "pull_request"}

    # ── 3. Batch-fetch source entities ───────────────────────────────────────
    files: dict[int, File] = {}
    issues: dict[int, Issue] = {}
    prs: dict[int, PullRequest] = {}

    if file_ids:
        r = await session.execute(select(File).where(File.id.in_(file_ids)))
        files = {f.id: f for f in r.scalars().all()}
    if issue_ids:
        r = await session.execute(select(Issue).where(Issue.id.in_(issue_ids)))
        issues = {i.id: i for i in r.scalars().all()}
    if pr_ids:
        r = await session.execute(select(PullRequest).where(PullRequest.id.in_(pr_ids)))
        prs = {p.id: p for p in r.scalars().all()}

    # ── 4. Build SearchResult list in ranked order ───────────────────────────
    results: list[SearchResult] = []
    for pid, rrf_score in ranked:
        chunk = chunks.get(pid)
        if not chunk:
            continue

        if chunk.source_type == "file":
            entity = files.get(chunk.source_id)
            source_title = entity.path if entity else ""
            github_number = None
        elif chunk.source_type == "issue":
            entity = issues.get(chunk.source_id)
            source_title = entity.title if entity else ""
            github_number = entity.github_number if entity else None
        elif chunk.source_type == "pull_request":
            entity = prs.get(chunk.source_id)
            source_title = entity.title if entity else ""
            github_number = entity.github_number if entity else None
        else:
            source_title = ""
            github_number = None

        results.append(
            SearchResult(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                metadata=chunk.chunk_metadata,
                source_type=chunk.source_type,
                source_id=chunk.source_id,
                rrf_score=rrf_score,
                source_title=source_title,
                github_number=github_number,
            )
        )

    return results
