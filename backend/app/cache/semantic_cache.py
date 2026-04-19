"""
Redis-backed semantic cache for triage pipeline results.

Keys are SHA-256 hashes of (repo_id, query) so identical queries on the same
repo skip the full embedding + LLM round-trip. TTL is configurable.

Error handling: Redis failures are logged as warnings and swallowed so that
a cache outage never breaks the triage flow.
"""
from __future__ import annotations

import hashlib
import json
import logging
import ssl
import urllib.parse

import redis.asyncio as aioredis

from app.triage.schemas import TriageOutput

logger = logging.getLogger(__name__)


class SemanticCache:
    def __init__(self, redis_url: str, ttl: int = 3600) -> None:
        # Strip ssl_cert_reqs from the URL (redis-py rejects "CERT_NONE" as a value)
        # and instead pass it as an explicit kwarg for rediss:// connections.
        parsed = urllib.parse.urlparse(redis_url)
        qs = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        qs.pop("ssl_cert_reqs", None)
        clean_url = parsed._replace(query=urllib.parse.urlencode(qs, doseq=True)).geturl()

        kwargs: dict = {"decode_responses": True}
        if redis_url.startswith("rediss://"):
            kwargs["ssl_cert_reqs"] = ssl.CERT_NONE

        self._client: aioredis.Redis = aioredis.from_url(clean_url, **kwargs)
        self._ttl = ttl

    def cache_key(self, repo_id: int, query: str) -> str:
        """Return a stable Redis key for this (repo_id, query) pair."""
        h = hashlib.sha256(f"{repo_id}:{query}".encode()).hexdigest()
        return f"triage:{h}"

    async def get(self, key: str) -> TriageOutput | None:
        """Return a cached TriageOutput, or None on miss or error."""
        try:
            raw = await self._client.get(key)
            if raw is None:
                return None
            data = json.loads(raw)
            return TriageOutput(**data)
        except Exception as exc:
            logger.warning("Cache get failed for key=%s: %s", key, exc)
            return None

    async def set(self, key: str, output: TriageOutput) -> None:
        """Store a TriageOutput in Redis with the configured TTL. Errors are swallowed."""
        try:
            raw = json.dumps(output.model_dump())
            await self._client.set(key, raw, ex=self._ttl)
        except Exception as exc:
            logger.warning("Cache set failed for key=%s: %s", key, exc)

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        await self._client.aclose()
