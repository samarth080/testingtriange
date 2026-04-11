# TriageCopilot Day 1 — Scaffold Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a fully runnable monorepo with Docker Compose (Postgres, Redis, Qdrant), a FastAPI backend with HMAC-SHA256 webhook signature verification, SQLAlchemy ORM models for all 8 tables, and an Alembic initial migration — with GitHub App registration instructions included.

**Architecture:** FastAPI app with a single `/webhooks/github` endpoint that verifies GitHub's HMAC-SHA256 signature before dispatching events. SQLAlchemy 2.0 async ORM models define the full schema. Alembic handles migrations. All services run via Docker Compose.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 + asyncpg, Alembic, pydantic-settings, Docker Compose (Postgres 15, Redis 7, Qdrant latest), pytest + httpx for tests.

---

## File Map

| File | Purpose |
|---|---|
| `docker-compose.yml` | Orchestrates postgres, redis, qdrant, backend, worker |
| `.env.example` | All environment variable placeholders |
| `README.md` | Architecture overview + setup instructions stub |
| `backend/pyproject.toml` | Python project config + dependencies |
| `backend/Dockerfile` | Backend Docker image |
| `backend/alembic.ini` | Alembic config pointing to `alembic/` |
| `backend/alembic/env.py` | Alembic async migration runner |
| `backend/alembic/script.py.mako` | Migration file template |
| `backend/alembic/versions/001_initial_schema.py` | Creates all 8 tables |
| `backend/app/__init__.py` | Package marker |
| `backend/app/core/__init__.py` | Package marker |
| `backend/app/core/config.py` | pydantic-settings: reads env vars, exposes typed settings |
| `backend/app/core/github_auth.py` | JWT creation + installation token exchange (stubs used in Day 2) |
| `backend/app/models/__init__.py` | Package marker |
| `backend/app/models/orm.py` | SQLAlchemy 2.0 ORM: Repo, Issue, PR, Commit, File, Chunk, Relationship, TriageResult |
| `backend/app/api/__init__.py` | Package marker |
| `backend/app/api/health.py` | GET /health — returns 200 + service status |
| `backend/app/api/webhooks.py` | POST /webhooks/github — HMAC verify + event dispatch |
| `backend/app/main.py` | FastAPI app factory, mounts routers |
| `backend/app/workers/__init__.py` | Package marker (Celery tasks added Day 2) |
| `backend/tests/__init__.py` | Package marker |
| `backend/tests/conftest.py` | Sets test env vars before app import |
| `backend/tests/test_webhooks.py` | Tests: valid sig → 200, bad sig → 401, missing sig → 401 |

---

## Task 1: Monorepo directory skeleton

**Files:**
- Create: `backend/app/__init__.py`
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/models/__init__.py`
- Create: `backend/app/api/__init__.py`
- Create: `backend/app/workers/__init__.py`
- Create: `backend/tests/__init__.py`
- Create: `frontend/.gitkeep`
- Create: `eval/.gitkeep`

- [ ] **Step 1: Create directory structure**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
mkdir -p backend/app/core backend/app/models backend/app/api backend/app/workers
mkdir -p backend/alembic/versions backend/tests
mkdir -p frontend eval
touch backend/app/__init__.py
touch backend/app/core/__init__.py
touch backend/app/models/__init__.py
touch backend/app/api/__init__.py
touch backend/app/workers/__init__.py
touch backend/tests/__init__.py
touch frontend/.gitkeep
touch eval/.gitkeep
```

Expected: no errors, directories exist.

- [ ] **Step 2: Verify structure**

```bash
find "/Users/samarthchatli/rag pipeline claude/backend" -type f | sort
```

Expected output includes `backend/app/__init__.py`, `backend/app/core/__init__.py`, etc.

- [ ] **Step 3: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git init
git add .
git commit -m "day-1: initialize monorepo directory structure"
```

---

## Task 2: Docker Compose + environment files

**Files:**
- Create: `docker-compose.yml`
- Create: `.env.example`
- Create: `.gitignore`

- [ ] **Step 1: Write `.gitignore`**

Create `/Users/samarthchatli/rag pipeline claude/.gitignore`:

```
.env
*.pem
__pycache__/
*.pyc
.pytest_cache/
*.egg-info/
dist/
.venv/
node_modules/
.next/
```

- [ ] **Step 2: Write `.env.example`**

Create `/Users/samarthchatli/rag pipeline claude/.env.example`:

```bash
# ── GitHub App ────────────────────────────────────────────────────────────────
# Register at https://github.com/settings/apps/new
# Required for ALL webhook functionality
GITHUB_APP_ID=
GITHUB_PRIVATE_KEY_PATH=./certs/github-app.pem
GITHUB_WEBHOOK_SECRET=

# ── Postgres ──────────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://triage:triage@localhost:5432/triage

# ── Redis (Celery broker + result backend) ────────────────────────────────────
REDIS_URL=redis://localhost:6379/0

# ── Qdrant ────────────────────────────────────────────────────────────────────
QDRANT_URL=http://localhost:6333

# ── Embeddings (optional — falls back to bge-large-en via HuggingFace) ────────
VOYAGE_API_KEY=
OPENAI_API_KEY=

# ── Reranker (optional — falls back to bge-reranker-large via HuggingFace) ───
COHERE_API_KEY=

# ── LLM (required for /triage endpoint) ──────────────────────────────────────
ANTHROPIC_API_KEY=
```

- [ ] **Step 3: Write `docker-compose.yml`**

Create `/Users/samarthchatli/rag pipeline claude/docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: triage
      POSTGRES_USER: triage
      POSTGRES_PASSWORD: triage
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U triage"]
      interval: 5s
      timeout: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 10

  qdrant:
    image: qdrant/qdrant:v1.9.2
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage
    healthcheck:
      test: ["CMD-SHELL", "curl -sf http://localhost:6333/healthz || exit 1"]
      interval: 10s
      timeout: 5s
      retries: 10

  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: .env
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
      qdrant:
        condition: service_healthy
    volumes:
      - ./backend:/app
      - ./certs:/certs:ro
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    env_file: .env
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    volumes:
      - ./backend:/app
    command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=4

volumes:
  postgres_data:
  qdrant_data:
```

- [ ] **Step 4: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add docker-compose.yml .env.example .gitignore
git commit -m "day-1: add docker-compose, env template, gitignore"
```

---

## Task 3: Backend Python project (pyproject.toml + Dockerfile)

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/Dockerfile`

- [ ] **Step 1: Write `backend/pyproject.toml`**

Create `/Users/samarthchatli/rag pipeline claude/backend/pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "triage-copilot-backend"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    # Web framework
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "python-multipart>=0.0.9",
    # Database — async ORM + driver + migrations
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29.0",
    "alembic>=1.13.1",
    # Config
    "pydantic-settings>=2.2.1",
    # Task queue
    "celery[redis]>=5.3.6",
    "redis>=5.0.4",
    # GitHub App auth
    "PyJWT>=2.8.0",
    "cryptography>=42.0.5",
    # HTTP client (used in ingestion + tests)
    "httpx>=0.27.0",
    # GitHub REST API wrapper (used in actions layer)
    "PyGithub>=2.3.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2.0",
    "pytest-asyncio>=0.23.6",
    "pytest-cov>=5.0.0",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

- [ ] **Step 2: Write `backend/Dockerfile`**

Create `/Users/samarthchatli/rag pipeline claude/backend/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# System deps: curl for healthcheck, build tools for compiled extensions
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source
# (layer cached unless pyproject.toml changes)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/pyproject.toml backend/Dockerfile
git commit -m "day-1: backend pyproject.toml and Dockerfile"
```

---

## Task 4: Core configuration (pydantic-settings)

**Files:**
- Create: `backend/app/core/config.py`

- [ ] **Step 1: Write `backend/app/core/config.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/app/core/config.py`:

```python
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
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -c "from app.core.config import settings; print('OK:', settings.embedding_provider)"
```

Expected: `OK: huggingface` (no API keys set yet)

- [ ] **Step 3: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/core/config.py
git commit -m "day-1: typed settings via pydantic-settings with provider auto-detection"
```

---

## Task 5: SQLAlchemy ORM models (all 8 tables)

**Files:**
- Create: `backend/app/models/orm.py`

- [ ] **Step 1: Write `backend/app/models/orm.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/app/models/orm.py`:

```python
"""
SQLAlchemy 2.0 ORM models for all TriageCopilot entities.

Design notes:
- All tables carry repo_id for multi-tenant isolation — queries always filter by repo.
- JSONB columns (labels, metadata, output) are used instead of separate junction
  tables for fields that are read together and never filtered on in SQL.
- The `relationships` table stores the graph edges walked during graph expansion.
  edge_type values: issue_pr | pr_file | issue_issue | commit_file
- chunks.qdrant_collection mirrors which Qdrant collection the vector lives in
  (code_chunks or discussion_chunks), so we can hydrate results without re-querying.
"""
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Repo(Base):
    __tablename__ = "repos"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    github_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    owner: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    installation_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # pending | running | done | failed
    backfill_status: Mapped[str] = mapped_column(String(50), nullable=False, server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("github_id", name="uq_repos_github_id"),)


class Issue(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    github_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(50), nullable=False)  # open | closed
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    # Stored as JSON list of label name strings: ["bug", "help wanted"]
    labels: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("repo_id", "github_number", name="uq_issues_repo_number"),
        Index("ix_issues_repo_id", "repo_id"),
    )


class PullRequest(Base):
    __tablename__ = "pull_requests"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    github_number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(50), nullable=False)  # open | closed | merged
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    merged_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # List of issue numbers this PR closes/references: [42, 57]
    linked_issue_numbers: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("repo_id", "github_number", name="uq_prs_repo_number"),
        Index("ix_prs_repo_id", "repo_id"),
    )


class Commit(Base):
    __tablename__ = "commits"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    sha: Mapped[str] = mapped_column(String(40), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # List of file paths changed: ["src/foo.py", "tests/test_foo.py"]
    changed_files: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="[]")

    __table_args__ = (
        UniqueConstraint("repo_id", "sha", name="uq_commits_repo_sha"),
        Index("ix_commits_repo_id", "repo_id"),
    )


class File(Base):
    __tablename__ = "files"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[Optional[str]] = mapped_column(String(50))  # python | javascript | go | etc.
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))  # SHA-256 of file content
    last_indexed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("repo_id", "path", name="uq_files_repo_path"),
        Index("ix_files_repo_id", "repo_id"),
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    # code | discussion | doc | commit
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # FK to the source row's id in issues/pull_requests/commits/files
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    # Source-specific metadata: {symbol, language, heading_path, labels, etc.}
    metadata: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # Which embedding model was used (determines which vector space it lives in)
    embedding_model: Mapped[Optional[str]] = mapped_column(String(100))
    # Back-pointer to the Qdrant point so we can delete/update without full re-scan
    qdrant_point_id: Mapped[Optional[str]] = mapped_column(String(36))  # UUID
    # code_chunks | discussion_chunks
    qdrant_collection: Mapped[Optional[str]] = mapped_column(String(50))

    __table_args__ = (
        UniqueConstraint("repo_id", "source_type", "source_id", "chunk_index", name="uq_chunks_source"),
        Index("ix_chunks_repo_source", "repo_id", "source_type", "source_id"),
    )


class Relationship(Base):
    """
    Graph edges used during retrieval graph expansion.

    edge_type values:
    - issue_pr:      issue → pull_request (issue was closed by this PR)
    - pr_file:       pull_request → file (PR changed this file)
    - issue_issue:   issue → issue (duplicate or reference link)
    - commit_file:   commit → file (commit modified this file)

    Walk: for a retrieved chunk's source, fetch 1-hop neighbors and pull their chunks.
    """
    __tablename__ = "relationships"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    target_type: Mapped[str] = mapped_column(String(50), nullable=False)
    target_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    edge_type: Mapped[str] = mapped_column(String(50), nullable=False)

    __table_args__ = (
        UniqueConstraint("repo_id", "source_type", "source_id", "target_type", "target_id",
                         name="uq_relationships"),
        Index("ix_relationships_source", "repo_id", "source_type", "source_id"),
    )


class TriageResult(Base):
    __tablename__ = "triage_results"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    repo_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("repos.id", ondelete="CASCADE"), nullable=False)
    issue_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("issues.id", ondelete="CASCADE"), nullable=False)
    # Full structured JSON output from the LLM layer
    output: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # URL of the posted GitHub comment
    comment_url: Mapped[Optional[str]] = mapped_column(Text)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("issue_id", name="uq_triage_results_issue"),
        Index("ix_triage_results_repo_id", "repo_id"),
    )
```

- [ ] **Step 2: Verify import**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -c "from app.models.orm import Base; print('Tables:', list(Base.metadata.tables.keys()))"
```

Expected:
```
Tables: ['repos', 'issues', 'pull_requests', 'commits', 'files', 'chunks', 'relationships', 'triage_results']
```

- [ ] **Step 3: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/models/orm.py
git commit -m "day-1: SQLAlchemy ORM — all 8 tables with indexes and constraints"
```

---

## Task 6: Alembic setup + initial migration

**Files:**
- Create: `backend/alembic.ini`
- Create: `backend/alembic/env.py`
- Create: `backend/alembic/script.py.mako`
- Create: `backend/alembic/versions/001_initial_schema.py`

- [ ] **Step 1: Write `backend/alembic.ini`**

Create `/Users/samarthchatli/rag pipeline claude/backend/alembic.ini`:

```ini
[alembic]
script_location = alembic
# URL is overridden by env.py reading from app.core.config — this is a fallback placeholder
sqlalchemy.url = postgresql+asyncpg://triage:triage@localhost:5432/triage

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 2: Write `backend/alembic/script.py.mako`**

Create `/Users/samarthchatli/rag pipeline claude/backend/alembic/script.py.mako`:

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 3: Write `backend/alembic/env.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/alembic/env.py`:

```python
"""
Alembic migration environment — async mode using asyncpg.

We run migrations via asyncio.run() so we can reuse the same asyncpg URL
as the application. This avoids maintaining a separate psycopg2 connection.
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Alembic config object — provides access to values in alembic.ini
config = context.config

# Set up Python logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import models so Alembic's autogenerate sees them
from app.models.orm import Base  # noqa: E402
from app.core.config import settings  # noqa: E402

target_metadata = Base.metadata

# Override alembic.ini URL with the value from pydantic-settings
config.set_main_option("sqlalchemy.url", str(settings.database_url))


def run_migrations_offline() -> None:
    """Offline mode: generate SQL script without DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Online mode: connect to DB and run migrations."""
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = str(settings.database_url)

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # Don't pool connections during migration
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 4: Write `backend/alembic/versions/001_initial_schema.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/alembic/versions/001_initial_schema.py`:

```python
"""Initial schema — all 8 tables

Revision ID: 001
Revises: 
Create Date: 2026-04-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "repos",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("owner", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("installation_id", sa.BigInteger(), nullable=False),
        sa.Column("backfill_status", sa.String(50), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("github_id", name="uq_repos_github_id"),
    )

    op.create_table(
        "issues",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("state", sa.String(50), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("labels", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("repo_id", "github_number", name="uq_issues_repo_number"),
    )
    op.create_index("ix_issues_repo_id", "issues", ["repo_id"])

    op.create_table(
        "pull_requests",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("github_number", sa.Integer(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text()),
        sa.Column("state", sa.String(50), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("merged_at", sa.DateTime(timezone=True)),
        sa.Column("linked_issue_numbers", JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("repo_id", "github_number", name="uq_prs_repo_number"),
    )
    op.create_index("ix_prs_repo_id", "pull_requests", ["repo_id"])

    op.create_table(
        "commits",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sha", sa.String(40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("author", sa.String(255), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("changed_files", JSONB(), nullable=False, server_default="[]"),
        sa.UniqueConstraint("repo_id", "sha", name="uq_commits_repo_sha"),
    )
    op.create_index("ix_commits_repo_id", "commits", ["repo_id"])

    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(50)),
        sa.Column("content_hash", sa.String(64)),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("repo_id", "path", name="uq_files_repo_path"),
    )
    op.create_index("ix_files_repo_id", "files", ["repo_id"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("embedding_model", sa.String(100)),
        sa.Column("qdrant_point_id", sa.String(36)),
        sa.Column("qdrant_collection", sa.String(50)),
        sa.UniqueConstraint(
            "repo_id", "source_type", "source_id", "chunk_index",
            name="uq_chunks_source"
        ),
    )
    op.create_index("ix_chunks_repo_source", "chunks", ["repo_id", "source_type", "source_id"])

    op.create_table(
        "relationships",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=False),
        sa.Column("target_id", sa.BigInteger(), nullable=False),
        sa.Column("edge_type", sa.String(50), nullable=False),
        sa.UniqueConstraint(
            "repo_id", "source_type", "source_id", "target_type", "target_id",
            name="uq_relationships"
        ),
    )
    op.create_index("ix_relationships_source", "relationships", ["repo_id", "source_type", "source_id"])

    op.create_table(
        "triage_results",
        sa.Column("id", sa.BigInteger(), autoincrement=True, primary_key=True),
        sa.Column("repo_id", sa.BigInteger(), sa.ForeignKey("repos.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_id", sa.BigInteger(), sa.ForeignKey("issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("output", JSONB(), nullable=False, server_default="{}"),
        sa.Column("comment_url", sa.Text()),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("issue_id", name="uq_triage_results_issue"),
    )
    op.create_index("ix_triage_results_repo_id", "triage_results", ["repo_id"])


def downgrade() -> None:
    op.drop_table("triage_results")
    op.drop_table("relationships")
    op.drop_table("chunks")
    op.drop_table("files")
    op.drop_table("commits")
    op.drop_table("pull_requests")
    op.drop_table("issues")
    op.drop_table("repos")
```

- [ ] **Step 5: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/alembic.ini backend/alembic/
git commit -m "day-1: Alembic async env + initial schema migration for all 8 tables"
```

---

## Task 7: FastAPI app + health endpoint

**Files:**
- Create: `backend/app/api/health.py`
- Create: `backend/app/main.py`

- [ ] **Step 1: Write `backend/app/api/health.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/app/api/health.py`:

```python
"""Health check endpoint — used by Docker healthchecks and load balancers."""
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}
```

- [ ] **Step 2: Write `backend/app/main.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/app/main.py`:

```python
"""
FastAPI application factory.

Router mounting order matters — health before webhooks so a failed
import in webhooks.py doesn't break the health endpoint.
"""
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.webhooks import router as webhook_router
from app.core.config import settings


def create_app() -> FastAPI:
    app = FastAPI(
        title="TriageCopilot",
        description="Graph-aware RAG GitHub issue triage assistant",
        version="0.1.0",
    )
    app.include_router(health_router)
    app.include_router(webhook_router)
    return app


app = create_app()
```

- [ ] **Step 3: Verify app starts (without DB — settings have defaults)**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -c "from app.main import app; print('Routers:', [r.path for r in app.routes])"
```

Expected output includes `/health` and `/webhooks/github`.

- [ ] **Step 4: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/api/health.py backend/app/main.py
git commit -m "day-1: FastAPI app factory with health endpoint"
```

---

## Task 8: Webhook signature verification — test-driven

**Files:**
- Create: `backend/tests/conftest.py`
- Create: `backend/tests/test_webhooks.py`
- Create: `backend/app/api/webhooks.py`

- [ ] **Step 1: Write `backend/tests/conftest.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/tests/conftest.py`:

```python
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
```

- [ ] **Step 2: Write failing tests in `backend/tests/test_webhooks.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/tests/test_webhooks.py`:

```python
"""
Tests for GitHub webhook signature verification.

GitHub signs every webhook payload with HMAC-SHA256 using the webhook secret.
The signature is sent in the X-Hub-Signature-256 header as "sha256=<hex>".
We must reject requests with missing or wrong signatures with 401.
"""
import hashlib
import hmac
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app

WEBHOOK_SECRET = "test-webhook-secret-for-pytest"


def _sign(payload: bytes) -> str:
    """Compute the HMAC-SHA256 signature GitHub would send."""
    mac = hmac.new(WEBHOOK_SECRET.encode("utf-8"), payload, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


@pytest.fixture
def async_client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_ping_with_valid_signature(async_client):
    """GitHub sends a 'ping' event when the App is first installed — must return 200."""
    payload = json.dumps({"zen": "Keep it logically awesome."}).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_signature(async_client):
    """Tampered payload must be rejected with 401."""
    payload = json.dumps({"action": "opened"}).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": "sha256=deadbeefdeadbeef",
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 401
    assert "signature" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(async_client):
    """Request with no X-Hub-Signature-256 header must be rejected with 401."""
    payload = json.dumps({"action": "opened"}).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_issues_opened_event_accepted(async_client):
    """A valid 'issues' opened event must be accepted (returns 202 Accepted)."""
    payload = json.dumps({
        "action": "opened",
        "issue": {"number": 42, "title": "Something is broken"},
        "repository": {"id": 1, "full_name": "owner/repo"},
        "installation": {"id": 99},
    }).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "issues",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 202


@pytest.mark.asyncio
async def test_installation_event_accepted(async_client):
    """A valid 'installation' created event must be accepted (returns 202 Accepted)."""
    payload = json.dumps({
        "action": "created",
        "installation": {"id": 99, "account": {"login": "owner"}},
        "repositories": [{"id": 1, "full_name": "owner/repo"}],
    }).encode()
    async with async_client as client:
        response = await client.post(
            "/webhooks/github",
            content=payload,
            headers={
                "X-Hub-Signature-256": _sign(payload),
                "X-GitHub-Event": "installation",
                "Content-Type": "application/json",
            },
        )
    assert response.status_code == 202
```

- [ ] **Step 3: Run tests — expect FAIL (webhooks.py doesn't exist yet)**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
pip install -e ".[dev]" -q
pytest tests/test_webhooks.py -v 2>&1 | head -30
```

Expected: `ImportError` or `ModuleNotFoundError` — `app.api.webhooks` not found. This confirms the tests are wired correctly.

- [ ] **Step 4: Write `backend/app/api/webhooks.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/app/api/webhooks.py`:

```python
"""
GitHub App webhook receiver.

Security: Every request is authenticated via HMAC-SHA256 signature verification
(X-Hub-Signature-256 header). We compare with hmac.compare_digest() to prevent
timing attacks. Requests with missing or invalid signatures are rejected 401.

Event routing: We read X-GitHub-Event and dispatch to the appropriate handler.
Unknown events are acknowledged with 200 so GitHub doesn't retry them.

Async design: Handlers enqueue Celery tasks and return immediately — webhook
requests must respond within 10 seconds or GitHub will retry. The actual
triage work happens in the background worker.
"""
import hashlib
import hmac
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request, Response

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


def _verify_signature(payload: bytes, signature_header: str | None) -> None:
    """
    Verify GitHub's HMAC-SHA256 payload signature.

    Raises HTTPException(401) if the signature is missing or does not match.
    Uses hmac.compare_digest to prevent timing attacks.
    """
    if not signature_header:
        raise HTTPException(status_code=401, detail="Missing X-Hub-Signature-256 header")

    secret = settings.github_webhook_secret
    if not secret:
        # If no webhook secret is configured, reject all requests in production.
        # In local dev without a secret set, this will always reject — set the secret.
        raise HTTPException(status_code=401, detail="Webhook secret not configured")

    mac = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256)
    expected = f"sha256={mac.hexdigest()}"

    if not hmac.compare_digest(expected, signature_header):
        raise HTTPException(status_code=401, detail="Invalid signature — payload may have been tampered")


@router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> Response:
    """
    Receive and dispatch GitHub App webhook events.

    Flow:
    1. Read raw body (must happen before any JSON parsing to preserve bytes for HMAC)
    2. Verify HMAC-SHA256 signature
    3. Parse JSON body
    4. Dispatch to event handler
    5. Return quickly — handlers must not do blocking work here
    """
    # Step 1: Read raw bytes first — signature verification requires the exact bytes GitHub sent
    payload = await request.body()

    # Step 2: Verify signature before touching the payload content
    _verify_signature(payload, x_hub_signature_256)

    # Step 3: Parse body
    try:
        body = json.loads(payload)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event = x_github_event or "unknown"
    logger.info("Received GitHub event: %s", event)

    # Step 4: Dispatch
    if event == "ping":
        return Response(content='{"status":"ok"}', media_type="application/json", status_code=200)

    if event == "installation":
        return await _handle_installation(body)

    if event == "issues":
        return await _handle_issues(body)

    if event in ("pull_request", "push"):
        # Will be wired to index-update tasks in Day 2
        return Response(status_code=202)

    # Unknown events: acknowledge so GitHub stops retrying
    logger.debug("Unhandled event type: %s", event)
    return Response(status_code=200)


async def _handle_installation(body: dict) -> Response:
    """
    Handle GitHub App installation events.

    action=created → new repo installed → enqueue full backfill task (Day 2)
    action=deleted → app uninstalled → mark repo inactive (Day 2)
    """
    action = body.get("action")
    installation_id = body.get("installation", {}).get("id")
    repos = body.get("repositories", [])

    logger.info(
        "Installation event: action=%s installation_id=%s repos=%s",
        action, installation_id, [r.get("full_name") for r in repos]
    )

    # TODO Day 2: enqueue backfill_repo.delay(repo_id) for each repo
    return Response(status_code=202)


async def _handle_issues(body: dict) -> Response:
    """
    Handle GitHub issues events.

    action=opened → new issue → enqueue triage task (Day 5)
    Other actions (edited, closed, etc.) → no-op for now
    """
    action = body.get("action")
    issue_number = body.get("issue", {}).get("number")
    repo_full_name = body.get("repository", {}).get("full_name")

    logger.info(
        "Issues event: action=%s issue=#%s repo=%s",
        action, issue_number, repo_full_name
    )

    if action == "opened":
        # TODO Day 5: enqueue triage_issue.delay(issue_id) after storing the issue
        pass

    return Response(status_code=202)
```

- [ ] **Step 5: Run tests — expect all PASS**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
pytest tests/test_webhooks.py -v
```

Expected:
```
PASSED tests/test_webhooks.py::test_ping_with_valid_signature
PASSED tests/test_webhooks.py::test_webhook_rejects_wrong_signature
PASSED tests/test_webhooks.py::test_webhook_rejects_missing_signature
PASSED tests/test_webhooks.py::test_issues_opened_event_accepted
PASSED tests/test_webhooks.py::test_installation_event_accepted
5 passed in X.XXs
```

- [ ] **Step 6: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/tests/conftest.py backend/tests/test_webhooks.py backend/app/api/webhooks.py
git commit -m "day-1: webhook endpoint with HMAC-SHA256 verification — all 5 tests passing"
```

---

## Task 9: GitHub App auth utilities (stubs for Day 2)

**Files:**
- Create: `backend/app/core/github_auth.py`

- [ ] **Step 1: Write `backend/app/core/github_auth.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/app/core/github_auth.py`:

```python
"""
GitHub App authentication helpers.

GitHub App auth flow:
1. Generate a short-lived JWT signed with the App's RSA private key (valid 10 min)
2. Use the JWT to call POST /app/installations/{installation_id}/access_tokens
3. The response contains an installation access token valid for 1 hour
4. Use the installation token for all API calls scoped to that repo

These tokens are used in Day 2 (backfill) and Day 6 (posting comments).
"""
import time
from functools import lru_cache
from pathlib import Path

import jwt

from app.core.config import settings


def _load_private_key() -> str:
    """Load the GitHub App RSA private key from the configured path."""
    key_path = Path(settings.github_private_key_path)
    if not key_path.exists():
        raise FileNotFoundError(
            f"GitHub App private key not found at {key_path}. "
            "Download it from your GitHub App settings page."
        )
    return key_path.read_text()


def create_github_jwt() -> str:
    """
    Create a JWT for GitHub App authentication.

    Signed with RS256 (RSA + SHA-256) using the App's private key.
    iat is backdated 60 seconds to account for clock drift between servers.
    exp is set 10 minutes from now (GitHub's maximum allowed).
    """
    now = int(time.time())
    private_key = _load_private_key()
    payload = {
        "iat": now - 60,   # Issued 60s ago — tolerate clock skew
        "exp": now + 600,  # Expires in 10 minutes
        "iss": settings.github_app_id,
    }
    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(installation_id: int) -> str:
    """
    Exchange a GitHub App JWT for an installation access token.

    The installation token grants permissions scoped to one installation
    (i.e., one org/user that installed the App). Valid for 1 hour.

    Used in: backfill tasks (Day 2), comment posting (Day 6).
    """
    import httpx

    app_jwt = create_github_jwt()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.github.com/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        return response.json()["token"]
```

- [ ] **Step 2: Verify import**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -c "from app.core.github_auth import create_github_jwt, get_installation_token; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/core/github_auth.py
git commit -m "day-1: GitHub App JWT + installation token helpers"
```

---

## Task 10: Celery app stub

**Files:**
- Create: `backend/app/workers/celery_app.py`

- [ ] **Step 1: Write `backend/app/workers/celery_app.py`**

Create `/Users/samarthchatli/rag pipeline claude/backend/app/workers/celery_app.py`:

```python
"""
Celery application instance.

Tasks are registered in separate modules (ingestion.tasks, triage.tasks)
and autodiscovered here. The broker is Redis; results are also stored in Redis.

Worker concurrency and task routing are configured here. Day 2 will add
actual task definitions for backfill and indexing.
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "triage_copilot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        # Task modules autodiscovered — add as implemented each day
        # "app.workers.ingestion_tasks",  # Day 2
        # "app.workers.triage_tasks",     # Day 5
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # Prevent tasks from silently disappearing if a worker dies mid-task
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)
```

- [ ] **Step 2: Verify import**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
python -c "from app.workers.celery_app import celery_app; print('Broker:', celery_app.conf.broker_url)"
```

Expected: `Broker: redis://localhost:6379/0`

- [ ] **Step 3: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add backend/app/workers/celery_app.py
git commit -m "day-1: Celery app stub with Redis broker"
```

---

## Task 11: README stub with architecture overview

**Files:**
- Create: `README.md`

- [ ] **Step 1: Write `README.md`**

Create `/Users/samarthchatli/rag pipeline claude/README.md`:

````markdown
# TriageCopilot

> Graph-aware RAG GitHub issue triage assistant. Automatically triages new issues with duplicate detection, label suggestions, relevant file identification, and assignee suggestions — all with cited reasoning.

## Architecture

```mermaid
graph TD
    GH[GitHub App Webhook] -->|new issue event| FW[FastAPI /webhooks/github]
    FW -->|enqueue| CW[Celery Worker]
    CW -->|backfill / index| PG[(Postgres)]
    CW -->|embed + upsert| QD[(Qdrant)]
    CW -->|triage pipeline| RP[Retrieval Pipeline]
    RP -->|hybrid search| QD
    RP -->|graph expand| PG
    RP -->|rerank| CR[Cohere Reranker]
    RP --> LLM[Claude Sonnet]
    LLM -->|structured JSON| AC[Action Layer]
    AC -->|post comment| GH2[GitHub Issue Comment]
    AC -->|store result| PG
    FE[Next.js Dashboard] -->|triage history + explainability| PG
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Celery + Redis |
| Database | Postgres 15 + SQLAlchemy 2.0 + Alembic |
| Vector DB | Qdrant (self-hosted) |
| Embeddings | voyage-code-3 / text-embedding-3-large (fallback: bge-large-en) |
| Reranker | Cohere Rerank v3 (fallback: bge-reranker-large) |
| LLM | Claude Sonnet (Anthropic API) |
| Code Parsing | tree-sitter (Python, JS, TS, Go) |
| Frontend | Next.js 14 + Tailwind + shadcn/ui |

## Local Setup

### Prerequisites

- Docker + Docker Compose
- Python 3.11+
- A GitHub App (see registration instructions below)

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/triage-copilot
cd triage-copilot
cp .env.example .env
# Edit .env and fill in GITHUB_APP_ID, GITHUB_WEBHOOK_SECRET, ANTHROPIC_API_KEY
```

### 2. Register the GitHub App

1. Go to **GitHub → Settings → Developer settings → GitHub Apps → New GitHub App**
2. Set the following:
   - **GitHub App name:** `TriageCopilot-dev` (must be unique)
   - **Homepage URL:** `http://localhost:8000`
   - **Webhook URL:** Use your smee.io proxy URL (see step 4)
   - **Webhook secret:** Generate a random secret (`openssl rand -hex 32`) and set it in `.env` as `GITHUB_WEBHOOK_SECRET`
   - **Permissions → Repository permissions:**
     - Issues: Read & Write
     - Pull requests: Read
     - Contents: Read
     - Metadata: Read
   - **Subscribe to events:** Issues, Pull request, Push, Installation
3. Click **Create GitHub App**
4. Note your **App ID** → set as `GITHUB_APP_ID` in `.env`
5. Scroll to **Private keys** → **Generate a private key** → download the `.pem` file
6. Copy it: `mkdir -p certs && cp ~/Downloads/*.pem certs/github-app.pem`
7. Set `GITHUB_PRIVATE_KEY_PATH=./certs/github-app.pem` in `.env`

### 3. Set up smee.io proxy (for local webhook delivery)

```bash
npm install --global smee-client
# Create a new channel at https://smee.io → copy the URL
smee --url https://smee.io/YOUR_CHANNEL_ID --target http://localhost:8000/webhooks/github
```

Set the smee.io URL as the **Webhook URL** in your GitHub App settings.

### 4. Start services

```bash
docker compose up -d postgres redis qdrant
```

### 5. Run database migrations

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
```

### 6. Start the backend

```bash
cd backend
uvicorn app.main:app --reload
```

Or run everything via Docker:

```bash
docker compose up
```

### 7. Install the GitHub App on a test repo

Go to your GitHub App → **Install App** → choose a repository. You should see an `installation` webhook arrive in your smee.io channel and a `202` response from the backend.

## Running Tests

```bash
cd backend
pytest tests/ -v
```

## Evaluation

```bash
# Day 7+: run the eval harness against labeled historical issues
cd eval
python run_eval.py --repo owner/repo --output results.md
```

## Deployment

- **Backend:** Railway (`railway up` from `/backend`)
- **Qdrant:** Hetzner VPS (`docker compose -f docker-compose.prod.yml up -d qdrant`)
- **Frontend:** Vercel (`vercel deploy` from `/frontend`)

## Progress

| Day | Status | Deliverable |
|---|---|---|
| 1 | ✅ | Scaffold, Docker Compose, webhook verification, schema, migrations |
| 2 | ⬜ | Backfill pipeline (issues, PRs, commits, files) |
| 3 | ⬜ | Chunkers (tree-sitter, markdown, discussion) + embeddings |
| 4 | ⬜ | Hybrid retrieval (BM25 + dense + RRF) |
| 5 | ⬜ | Graph expansion + reranker + LLM triage endpoint |
| 6 | ⬜ | End-to-end webhook → comment flow |
| 7 | ⬜ | Eval harness + baseline metrics |
| 8 | ⬜ | Calibration + incremental indexing + semantic cache |
| 9 | ⬜ | Next.js dashboard |
| 10 | ⬜ | Deploy + GitHub App listing + demo video |
````

- [ ] **Step 2: Commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
git add README.md
git commit -m "day-1: README with architecture diagram, setup instructions, GitHub App registration guide"
```

---

## Task 12: End-to-end smoke test

- [ ] **Step 1: Start infrastructure services**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
docker compose up -d postgres redis qdrant
```

Wait ~15 seconds for services to be healthy, then verify:

```bash
docker compose ps
```

Expected: `postgres`, `redis`, `qdrant` all show `healthy`.

- [ ] **Step 2: Install Python dependencies**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
pip install -e ".[dev]"
```

Expected: successful install, no errors.

- [ ] **Step 3: Run Alembic migrations**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
alembic upgrade head
```

Expected output:
```
INFO  [alembic.runtime.migration] Context impl PostgreSQLImpl.
INFO  [alembic.runtime.migration] Will assume transact DDL.
INFO  [alembic.runtime.migration] Running upgrade  -> 001, Initial schema — all 8 tables
```

- [ ] **Step 4: Verify all tables exist in Postgres**

```bash
docker compose exec postgres psql -U triage -d triage -c "\dt"
```

Expected: 8 tables listed — repos, issues, pull_requests, commits, files, chunks, relationships, triage_results.

- [ ] **Step 5: Run full test suite**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
pytest tests/ -v
```

Expected: 5 tests pass, 0 fail.

- [ ] **Step 6: Start the backend and hit /health**

```bash
cd "/Users/samarthchatli/rag pipeline claude/backend"
uvicorn app.main:app --port 8000 &
sleep 2
curl -s http://localhost:8000/health | python -m json.tool
```

Expected:
```json
{
    "status": "ok"
}
```

- [ ] **Step 7: Simulate a ping webhook**

```bash
# Compute valid HMAC signature for the test payload
PAYLOAD='{"zen":"Keep it logically awesome."}'
SECRET="your-webhook-secret-here"  # Replace with your actual GITHUB_WEBHOOK_SECRET from .env
SIG=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$SECRET" | awk '{print "sha256="$2}')

curl -s -X POST http://localhost:8000/webhooks/github \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: ping" \
  -H "X-Hub-Signature-256: $SIG" \
  -d "$PAYLOAD"
```

Expected: `{"status":"ok"}`

- [ ] **Step 8: Final Day 1 commit**

```bash
cd "/Users/samarthchatli/rag pipeline claude"
# Stop background uvicorn
pkill -f "uvicorn app.main:app" || true

git add -A
git commit -m "day-1: scaffold complete — Docker Compose, FastAPI, webhook verification, schema, migrations, 5 tests passing"
```

---

## Self-Review Against Spec

| Spec Requirement | Task | Status |
|---|---|---|
| Repo scaffold | Task 1 | ✅ |
| Docker Compose (postgres, redis, qdrant) | Task 2 | ✅ |
| FastAPI skeleton | Task 7 | ✅ |
| GitHub App registration instructions | Task 11 (README) | ✅ |
| Webhook signature verification | Task 8 | ✅ |
| Alembic migrations for base schema | Task 6 | ✅ |
| SQLAlchemy models (all 8 tables) | Task 5 | ✅ |
| README stub with architecture | Task 11 | ✅ |
| smee.io proxy instructions | Task 11 (README) | ✅ |
| `.env.example` with all placeholders | Task 2 | ✅ |
| Open-source fallback auto-detection | Task 4 (config.py) | ✅ |
| Celery app stub | Task 10 | ✅ |
