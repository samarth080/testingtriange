"""
Test configuration.

Sets required env vars BEFORE any app module is imported,
because pydantic-settings reads env at import time.
"""
import os

os.environ.setdefault("GITHUB_WEBHOOK_SECRET", "test-webhook-secret-for-pytest")
os.environ.setdefault("GITHUB_APP_ID", "12345")
os.environ.setdefault("GITHUB_PRIVATE_KEY_PATH", "/nonexistent.pem")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://triage:triage@localhost:5432/triage")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
