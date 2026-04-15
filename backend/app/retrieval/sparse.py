"""Sparse (BM25-style) search via Postgres full-text search."""

from sqlalchemy.ext.asyncio import AsyncSession


async def sparse_search(
    session: AsyncSession,
    repo_id: int,
    query: str,
    k: int,
) -> list[tuple[str, float]]:
    """Returns list of (qdrant_point_id, ts_rank_score) ordered by score desc."""
    raise NotImplementedError
