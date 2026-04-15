"""
POST /search — hybrid retrieval endpoint.

Accepts a plain-text query and repo_id, returns ranked SearchResult objects.
Embedder and QdrantStore are constructed per-request from settings.
"""
from dataclasses import asdict

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.indexing.embedder import embedder_from_settings
from app.indexing.qdrant_store import QdrantStore
from app.retrieval import retrieve

router = APIRouter()


class SearchRequest(BaseModel):
    repo_id: int
    query: str
    k: int = 10


@router.post("/search")
async def search_endpoint(
    req: SearchRequest,
    session: AsyncSession = Depends(get_db),
) -> list[dict]:
    embedder = embedder_from_settings()
    qdrant = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension)
    results = await retrieve(
        session=session,
        qdrant=qdrant,
        embedder=embedder,
        repo_id=req.repo_id,
        query=req.query,
        k=req.k,
    )
    return [asdict(r) for r in results]
