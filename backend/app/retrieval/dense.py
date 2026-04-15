"""Dense vector search via Qdrant."""

from app.indexing.qdrant_store import QdrantStore


async def dense_search(
    qdrant: QdrantStore,
    collection: str,
    query_vector: list[float],
    repo_id: int,
    k: int,
) -> list[tuple[str, float, dict]]:
    """
    Search Qdrant for the k nearest vectors in a collection.

    Args:
        qdrant:       QdrantStore instance.
        collection:   Collection name ("code_chunks" or "discussion_chunks").
        query_vector: Embedded query vector.
        repo_id:      Only return points belonging to this repo.
        k:            Number of results to return.

    Returns:
        List of (qdrant_point_id, score, payload) ordered by score descending.
    """
    hits = await qdrant.search(collection, query_vector, repo_id, k)
    return [(h["id"], h["score"], h["payload"]) for h in hits]
