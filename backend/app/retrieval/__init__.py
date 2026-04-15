"""
Hybrid retrieval pipeline: dense (Qdrant) + sparse (Postgres FTS) fused with RRF.

Public interface:
    SearchResult  — dataclass returned by retrieve()
    retrieve()    — async entry point; embed → search → fuse → hydrate
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing.embedder import Embedder
from app.indexing.qdrant_store import CODE_COLLECTION, DISCUSSION_COLLECTION, QdrantStore


@dataclass
class SearchResult:
    chunk_id: int
    chunk_index: int
    text: str
    metadata: dict
    source_type: str       # file | issue | pull_request
    source_id: int
    rrf_score: float
    source_title: str      # file path, or issue/PR title
    github_number: int | None  # None for file chunks


async def retrieve(
    session: AsyncSession,
    qdrant: QdrantStore,
    embedder: Embedder,
    repo_id: int,
    query: str,
    k: int = 20,
    n_candidates: int = 50,
) -> list[SearchResult]:
    """
    Hybrid retrieval entry point.

    1. Embed query with the configured embedder.
    2. Dense search: code_chunks + discussion_chunks in Qdrant (n_candidates each).
    3. Sparse search: Postgres ts_rank over chunks.text (n_candidates).
    4. RRF fuse all three ranked lists on qdrant_point_id.
    5. Take top-k, hydrate from Postgres (chunks + source entities).
    """
    from app.retrieval.dense import dense_search
    from app.retrieval.fusion import rrf_fuse
    from app.retrieval.hydration import hydrate
    from app.retrieval.sparse import sparse_search

    vectors = await embedder.embed_batch([query])
    query_vector = vectors[0]

    dense_code = await dense_search(qdrant, CODE_COLLECTION, query_vector, repo_id, n_candidates)
    dense_disc = await dense_search(qdrant, DISCUSSION_COLLECTION, query_vector, repo_id, n_candidates)
    sparse = await sparse_search(session, repo_id, query, n_candidates)

    # Extract ordered ID lists for RRF (each list preserves rank order)
    code_ids = [pid for pid, _score, _payload in dense_code]
    disc_ids = [pid for pid, _score, _payload in dense_disc]
    sparse_ids = [pid for pid, _score in sparse]

    fused = rrf_fuse(code_ids, disc_ids, sparse_ids)
    top_k = fused[:k]

    return await hydrate(session, top_k)
