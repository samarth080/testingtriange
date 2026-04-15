"""
Reranker: score and reorder retrieval results by relevance to a query.

Provider selection (caller reads from settings and passes in):
  "cohere" + non-empty api_key  ->  Cohere Rerank v3 (rerank-english-v3.0)
  any other case                ->  passthrough: results sliced to top_n
"""
import logging

import cohere

from app.retrieval import SearchResult

logger = logging.getLogger(__name__)


async def rerank(
    query: str,
    results: list[SearchResult],
    top_n: int,
    api_key: str = "",
    provider: str = "cohere",
) -> list[SearchResult]:
    """
    Rerank results by relevance to query.

    Args:
        query:    The search query string.
        results:  Candidate results to rerank (order doesn't matter for Cohere).
        top_n:    Number of results to return.
        api_key:  Provider API key (empty string triggers passthrough).
        provider: "cohere" or "passthrough".

    Returns:
        top_n results in descending relevance order.
    """
    if not results:
        return results

    if provider == "cohere" and api_key:
        return await _cohere_rerank(query, results, top_n, api_key)

    logger.warning(
        "No reranker configured (provider=%s, has_key=%s) — returning top %d unchanged",
        provider, bool(api_key), top_n,
    )
    return results[:top_n]


async def _cohere_rerank(
    query: str,
    results: list[SearchResult],
    top_n: int,
    api_key: str,
) -> list[SearchResult]:
    client = cohere.AsyncClientV2(api_key=api_key)
    try:
        response = await client.rerank(
            model="rerank-english-v3.0",
            query=query,
            documents=[r.text for r in results],
            top_n=top_n,
        )
        return [results[item.index] for item in response.results]
    finally:
        await client.close()
