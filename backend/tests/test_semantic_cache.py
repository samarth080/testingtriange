"""
Tests for SemanticCache and the triage pipeline cache integration.

Redis is mocked via AsyncMock — no real Redis needed.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.cache.semantic_cache import SemanticCache
from app.triage.schemas import TriageOutput


def make_cache(ttl: int = 3600) -> SemanticCache:
    """Return a SemanticCache with a mocked Redis client."""
    cache = SemanticCache.__new__(SemanticCache)
    cache._ttl = ttl
    cache._client = AsyncMock()
    return cache


def sample_output() -> TriageOutput:
    return TriageOutput(
        labels=["bug"],
        confidence="high",
        reasoning="Looks like a bug.",
    )


# ── cache_key ────────────────────────────────────────────────────────────────

def test_cache_key_is_deterministic():
    cache = make_cache()
    k1 = cache.cache_key(1, "fix memory leak")
    k2 = cache.cache_key(1, "fix memory leak")
    assert k1 == k2


def test_cache_key_differs_by_repo():
    cache = make_cache()
    k1 = cache.cache_key(1, "same query")
    k2 = cache.cache_key(2, "same query")
    assert k1 != k2


def test_cache_key_has_triage_prefix():
    cache = make_cache()
    assert cache.cache_key(1, "x").startswith("triage:")


# ── get ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_returns_none_on_miss():
    cache = make_cache()
    cache._client.get = AsyncMock(return_value=None)
    result = await cache.get("triage:abc")
    assert result is None


@pytest.mark.asyncio
async def test_get_returns_triage_output_on_hit():
    cache = make_cache()
    output = sample_output()
    cache._client.get = AsyncMock(return_value=json.dumps(output.model_dump()))
    result = await cache.get("triage:abc")
    assert isinstance(result, TriageOutput)
    assert result.confidence == "high"
    assert result.labels == ["bug"]


@pytest.mark.asyncio
async def test_get_returns_none_on_redis_error():
    cache = make_cache()
    cache._client.get = AsyncMock(side_effect=ConnectionError("redis down"))
    result = await cache.get("triage:abc")
    assert result is None  # errors are swallowed, never raised


# ── set ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_set_stores_json_with_ttl():
    cache = make_cache(ttl=600)
    output = sample_output()
    cache._client.set = AsyncMock()
    await cache.set("triage:abc", output)
    cache._client.set.assert_awaited_once_with(
        "triage:abc",
        json.dumps(output.model_dump()),
        ex=600,
    )


@pytest.mark.asyncio
async def test_set_swallows_redis_error():
    cache = make_cache()
    cache._client.set = AsyncMock(side_effect=ConnectionError("redis down"))
    output = sample_output()
    await cache.set("triage:abc", output)  # must not raise


# ── pipeline integration ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_uses_cache_on_hit():
    """When cache returns a hit, pipeline must NOT call retrieve/LLM."""
    from app.triage.pipeline import run_triage_pipeline

    cached_output = sample_output()
    cache = make_cache()
    cache.cache_key = MagicMock(return_value="triage:xyz")
    cache.get = AsyncMock(return_value=cached_output)
    cache.set = AsyncMock()

    mock_issue = MagicMock()
    mock_issue.github_number = 42
    mock_issue.title = "crash on startup"
    mock_issue.body = "stack overflow"
    mock_issue.labels = []

    with (
        patch("app.triage.pipeline.retrieve", new_callable=AsyncMock) as mock_retrieve,
        patch("app.triage.pipeline.graph_expand", new_callable=AsyncMock),
        patch("app.triage.pipeline.rerank", new_callable=AsyncMock),
        patch("app.triage.pipeline.triage_with_llm", new_callable=AsyncMock),
    ):
        output, latency_ms = await run_triage_pipeline(
            session=AsyncMock(),
            repo_id=1,
            issue=mock_issue,
            embedder=MagicMock(),
            qdrant=MagicMock(),
            cfg=MagicMock(),
            cache=cache,
        )

    mock_retrieve.assert_not_awaited()
    assert output.confidence == "high"
    assert latency_ms == 0


@pytest.mark.asyncio
async def test_pipeline_sets_cache_on_miss():
    """When cache misses, pipeline runs normally and stores result in cache."""
    from app.triage.pipeline import run_triage_pipeline

    pipeline_output = sample_output()
    cache = make_cache()
    cache.cache_key = MagicMock(return_value="triage:xyz")
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()

    mock_issue = MagicMock()
    mock_issue.github_number = 42
    mock_issue.title = "crash on startup"
    mock_issue.body = "stack overflow"
    mock_issue.labels = []

    with (
        patch("app.triage.pipeline.retrieve", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.graph_expand", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.rerank", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.triage_with_llm", new_callable=AsyncMock, return_value=pipeline_output),
    ):
        output, latency_ms = await run_triage_pipeline(
            session=AsyncMock(),
            repo_id=1,
            issue=mock_issue,
            embedder=MagicMock(),
            qdrant=MagicMock(),
            cfg=MagicMock(),
            cache=cache,
        )

    cache.set.assert_awaited_once_with("triage:xyz", pipeline_output)
    assert output.confidence == "high"
    assert latency_ms >= 0


@pytest.mark.asyncio
async def test_pipeline_works_without_cache():
    """When cache=None, pipeline runs normally with no cache calls."""
    from app.triage.pipeline import run_triage_pipeline

    pipeline_output = sample_output()
    mock_issue = MagicMock()
    mock_issue.github_number = 42
    mock_issue.title = "crash on startup"
    mock_issue.body = None
    mock_issue.labels = []

    with (
        patch("app.triage.pipeline.retrieve", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.graph_expand", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.rerank", new_callable=AsyncMock, return_value=[]),
        patch("app.triage.pipeline.triage_with_llm", new_callable=AsyncMock, return_value=pipeline_output),
    ):
        output, latency_ms = await run_triage_pipeline(
            session=AsyncMock(),
            repo_id=1,
            issue=mock_issue,
            embedder=MagicMock(),
            qdrant=MagicMock(),
            cfg=MagicMock(),
            cache=None,
        )

    assert isinstance(output, TriageOutput)
