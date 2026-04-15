"""Sparse (BM25-style) search via Postgres full-text search."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def sparse_search(
    session: AsyncSession,
    repo_id: int,
    query: str,
    k: int,
) -> list[tuple[str, float]]:
    """
    Full-text search over chunks.text using Postgres ts_rank.

    Uses plainto_tsquery so multi-word queries work without special syntax.
    Skips chunks with a NULL qdrant_point_id (not yet indexed in Qdrant).

    Args:
        session:  Async SQLAlchemy session.
        repo_id:  Restrict to this repo.
        query:    Raw query string from the user.
        k:        Maximum results to return.

    Returns:
        List of (qdrant_point_id, ts_rank_score) ordered by score descending.
    """
    if not query.strip():
        return []

    sql = text("""
        SELECT qdrant_point_id,
               ts_rank(to_tsvector('english', text),
                       plainto_tsquery('english', :query)) AS score
        FROM   chunks
        WHERE  repo_id          = :repo_id
          AND  qdrant_point_id  IS NOT NULL
          AND  to_tsvector('english', text)
               @@ plainto_tsquery('english', :query)
        ORDER  BY score DESC
        LIMIT  :k
    """)
    result = await session.execute(sql, {"repo_id": repo_id, "query": query, "k": k})
    return [(row.qdrant_point_id, float(row.score)) for row in result]
