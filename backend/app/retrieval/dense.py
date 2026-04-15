"""Dense vector search via Qdrant."""

from app.indexing.qdrant_store import QdrantStore


async def dense_search(
    qdrant: QdrantStore,
    collection: str,
    query_vector: list[float],
    repo_id: int,
    k: int,
) -> list[tuple[str, float, dict]]:
    """Returns list of (qdrant_point_id, score, payload) ordered by score desc."""
    raise NotImplementedError
