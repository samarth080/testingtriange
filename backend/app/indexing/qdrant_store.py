"""
Async Qdrant client wrapper.

Two collections:
  code_chunks       — vectors from source code files
  discussion_chunks — vectors from issues and PRs

Point IDs are deterministic UUIDs derived from (repo_id, source_type,
source_id, chunk_index) — makes upserts idempotent across re-index runs.
"""
import logging
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)

CODE_COLLECTION = "code_chunks"
DISCUSSION_COLLECTION = "discussion_chunks"

_UUID_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def point_id(repo_id: int, source_type: str, source_id: int, chunk_index: int) -> str:
    """Generate a stable UUID string for a chunk."""
    key = f"{repo_id}:{source_type}:{source_id}:{chunk_index}"
    return str(uuid.uuid5(_UUID_NS, key))


class QdrantStore:
    def __init__(self, url: str, vector_dim: int) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._dim = vector_dim

    async def ensure_collections(self) -> None:
        for name in (CODE_COLLECTION, DISCUSSION_COLLECTION):
            exists = await self._client.collection_exists(collection_name=name)
            if not exists:
                await self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
                )
                logger.info("Created Qdrant collection: %s (dim=%d)", name, self._dim)

    async def upsert_points(self, collection: str, points: list[dict]) -> None:
        if not points:
            return
        structs = [
            PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ]
        await self._client.upsert(collection_name=collection, points=structs)

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        repo_id: int,
        k: int,
    ) -> list[dict]:
        """
        Search for nearest neighbours in a collection, filtered to a single repo.

        Returns:
            List of {"id": str, "score": float, "payload": dict} ordered by score desc.
        """
        if k < 1:
            raise ValueError(f"k must be >= 1, got {k}")
        response = await self._client.query_points(
            collection_name=collection,
            query=query_vector,
            query_filter=Filter(
                must=[FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
            ),
            limit=k,
            with_payload=True,
        )
        return [
            {"id": str(r.id), "score": r.score, "payload": r.payload or {}}
            for r in response.points
        ]

    async def delete_repo_points(self, repo_id: int) -> None:
        condition = Filter(
            must=[FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
        )
        for collection in (CODE_COLLECTION, DISCUSSION_COLLECTION):
            await self._client.delete(
                collection_name=collection,
                points_selector=FilterSelector(filter=condition),
            )
        logger.info("Deleted all Qdrant points for repo_id=%d", repo_id)
