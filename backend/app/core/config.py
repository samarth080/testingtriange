"""
Application configuration loaded from environment variables.

Uses pydantic-settings so every setting is typed and validated at startup.
Missing required settings raise a clear ValidationError — no silent misconfig.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── GitHub App ────────────────────────────────────────────────────────────
    github_app_id: str = ""
    github_private_key_path: str = "./certs/github-app.pem"
    github_webhook_secret: str = ""

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "postgresql+asyncpg://triage:triage@localhost:5432/triage"

    # ── Redis ─────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── Qdrant ────────────────────────────────────────────────────────────────
    qdrant_url: str = "http://localhost:6333"

    # ── Embeddings (optional — auto-detected at startup) ──────────────────────
    voyage_api_key: str = ""
    openai_api_key: str = ""

    # ── Reranker (optional — auto-detected at startup) ────────────────────────
    cohere_api_key: str = ""

    # ── LLM ───────────────────────────────────────────────────────────────────
    anthropic_api_key: str = ""

    # ── Calibration ───────────────────────────────────────────────────────────
    # Minimum confidence level before posting a GitHub comment.
    # Values: "low" (always post) | "medium" | "high" (only post high-confidence)
    min_confidence: str = "low"

    # ── Semantic cache ────────────────────────────────────────────────────────
    semantic_cache_ttl: int = 3600  # seconds

    # ── CORS ─────────────────────────────────────────────────────────────────
    # Comma-separated list of allowed origins. Use "*" to allow all (dev default).
    # Example: "http://localhost:3000,https://your-app.vercel.app"
    cors_origins: str = "*"

    @property
    def embedding_provider(self) -> str:
        """Return which embedding provider to use based on available API keys."""
        if self.voyage_api_key:
            return "voyage"
        if self.openai_api_key:
            return "openai"
        return "huggingface"  # bge-large-en fallback

    @property
    def reranker_provider(self) -> str:
        """Return which reranker to use based on available API keys."""
        if self.cohere_api_key:
            return "cohere"
        return "huggingface"  # bge-reranker-large fallback


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton — call this everywhere instead of instantiating Settings()."""
    return Settings()


# Module-level singleton for use in non-DI contexts (e.g. Alembic env.py)
settings = get_settings()
