"""Hydrate chunk IDs into SearchResult objects with source entity details."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.retrieval import SearchResult


async def hydrate(
    session: AsyncSession,
    ranked: list[tuple[str, float]],
) -> list[SearchResult]:
    """Given (qdrant_point_id, rrf_score) pairs, return fully hydrated SearchResults."""
    raise NotImplementedError
