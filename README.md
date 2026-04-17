# TriageCopilot

[![License: Proprietary](https://img.shields.io/badge/License-Proprietary-red.svg)](LICENSE)

> Graph-aware RAG GitHub issue triage assistant. Automatically triages new GitHub issues with duplicate detection, label suggestions, relevant file identification, and assignee suggestions — all with cited reasoning posted as a comment directly on the issue.

## What It Does

When a new issue is opened on a repo where TriageCopilot is installed:

1. GitHub sends a webhook to the FastAPI backend
2. A Celery worker picks it up and embeds the issue title + body using Voyage AI
3. Hybrid search (BM25 + dense vector) retrieves similar past issues and relevant code files from Qdrant
4. 1-hop graph expansion enriches the context (linked PRs, touched files)
5. A reranker (Cohere or HuggingFace fallback) scores and filters results
6. An LLM (Groq/Llama 3.3, Anthropic Claude, or Gemini) generates structured triage output
7. A comment is posted back to the GitHub issue with confidence, labels, reasoning, and related issues

## Architecture

```mermaid
graph TD
    GH[GitHub App Webhook] -->|new issue event| FW[FastAPI /webhooks/github]
    FW -->|enqueue| CW[Celery Worker]
    CW -->|backfill / index| PG[(Postgres)]
    CW -->|embed + upsert| QD[(Qdrant)]
    CW -->|triage pipeline| RP[Retrieval Pipeline]
    RP -->|hybrid search BM25 + dense| QD
    RP -->|graph expand 1-hop| PG
    RP -->|rerank| CR[Cohere / HuggingFace Reranker]
    RP --> LLM[LLM: Groq / Claude / Gemini]
    LLM -->|structured JSON| AC[Action Layer]
    AC -->|post comment| GH2[GitHub Issue Comment]
    AC -->|store result + comment_url| PG
    FE[Next.js Dashboard] -->|triage history + explainability| PG
```

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + Celery + Redis |
| Database | Postgres 15 + SQLAlchemy 2.0 (async) + Alembic |
| Vector DB | Qdrant v1.13 (self-hosted) |
| Embeddings | Voyage AI `voyage-code-3` (fallback: OpenAI `text-embedding-3-large`, then `bge-large-en`) |
| Reranker | Cohere Rerank v3 (fallback: `bge-reranker-large`) |
| LLM | Groq `llama-3.3-70b-versatile` / Anthropic Claude Sonnet / Google Gemini |
| Code Parsing | tree-sitter (Python, JS, TS, Go, Rust, Java) |
| Retrieval | Hybrid BM25 + dense + RRF fusion + 1-hop graph expansion |
| Semantic Cache | Redis-backed cache keyed on embedding similarity |
| Frontend | Next.js 14 (App Router) + Tailwind CSS + shadcn/ui |
| Containerization | Docker Compose (6 services: postgres, redis, qdrant, backend, worker, frontend) |

## What Was Built (Day by Day)

### Day 1 — Foundation
- FastAPI app scaffold with health endpoint
- Docker Compose stack: Postgres, Redis, Qdrant, backend, Celery worker
- HMAC-SHA256 webhook signature verification (timing-safe)
- SQLAlchemy ORM models: `Repo`, `Issue`, `PullRequest`, `Commit`, `File`, `GraphEdge`, `Chunk`, `TriageResult`
- Alembic migrations with all indexes and constraints

### Day 2 — Backfill Pipeline
- Async GitHub API client with Link-header pagination and rate-limit retry (403/429 + `Retry-After`)
- Fetchers for issues, PRs, commits, and full file trees — all upserted idempotently
- Graph edges: `issue_pr` (PR body regex for `closes/fixes/resolves #N`) and `pr_file`
- Celery task `ingestion.backfill_repo` with 3× retry on transient failure

### Day 3 — Chunking + Indexing
- Tree-sitter chunkers for Python, JS/TS, Go — extracts functions and classes as individual chunks
- Markdown chunker (header-aware), discussion chunker for issues and PRs
- Voyage AI embedding with OpenAI fallback and local `bge-large-en` last resort
- Celery task `indexing.index_repo` — embeds all chunks and upserts into Qdrant with stable deterministic UUIDs

### Day 4 — Hybrid Retrieval
- BM25 sparse search over Postgres full-text (`tsvector` + `ts_rank`)
- Dense vector search via Qdrant `query_points` filtered by `repo_id`
- Reciprocal Rank Fusion (RRF) to merge both ranked lists
- Chunk deduplication for graph-expanded context
- `GET /search` endpoint for manual retrieval testing

### Day 5 — Graph Expansion + Reranker + Triage Endpoint
- 1-hop graph expansion: given retrieved chunks, fetches linked PRs and files from `graph_edges`
- Cohere Rerank v3 reranker with `bge-reranker-large` HuggingFace fallback
- LLM triage call returning structured JSON: `confidence`, `labels`, `reasoning`, `related_issues`, `suggested_files`, `suggested_assignees`
- `POST /triage` REST endpoint wired to full pipeline

### Day 6 — Webhook → Comment Flow
- `issues` webhook handler: upserts issue to Postgres then enqueues `triage.triage_issue`
- `push` webhook handler: triggers incremental re-index on new commits
- GitHub App comment posting with JWT authentication and installation access token
- Celery task `triage.triage_issue` saves result to `triage_results` and posts comment on GitHub

### Day 7 — Eval Harness
- Eval dataset of labeled historical issues
- Precision/recall/F1 metrics on label prediction and duplicate detection
- Baseline metrics report

### Day 8 — Calibration + Incremental Indexing + Semantic Cache
- Confidence calibration: `min_confidence` setting gates whether a comment is posted
- Incremental indexing task triggered on `push` events (avoids full re-backfill)
- Redis semantic cache: embedding-similarity key lookup with configurable TTL — skips LLM call on cache hit

### Day 9 — Next.js Dashboard
- App Router with repo list, per-repo issue view, triage result detail
- Server components fetching from FastAPI backend
- Shows confidence, labels, reasoning, related issues, suggested files per triage result

### Day 10 — Final Polish + Full-Stack Docker
- `pytest` marker system: integration tests skip by default, run with `pytest -m integration`
- FastAPI `CORSMiddleware` with wildcard-aware credential handling
- Next.js `output: 'standalone'` for lean Docker image with non-root user
- `docker-compose.yml` frontend service + Qdrant TCP healthcheck
- `scripts/smoke_test.sh` — 8-check curl smoke test covering all major endpoints
- Multi-provider LLM support: Groq (free, default) → Anthropic Claude → Google Gemini
- `NullPool` for Celery worker DB sessions to avoid asyncio event loop conflicts across forks

## Local Setup

### Prerequisites

- Docker + Docker Compose
- A GitHub App (instructions below)
- One of: Groq API key (free), Anthropic API key, or Google Gemini API key
- Voyage AI API key (free tier: 200M tokens)

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/triage-copilot
cd triage-copilot
cp .env.example .env
```

Edit `.env`:

```env
# GitHub App
GITHUB_APP_ID=your_app_id
GITHUB_WEBHOOK_SECRET=your_webhook_secret
GITHUB_PRIVATE_KEY_PATH=./certs/github-app.pem

# Database (default works with docker compose)
DATABASE_URL=postgresql+asyncpg://triage:triage@postgres:5432/triage
REDIS_URL=redis://redis:6379/0
QDRANT_URL=http://qdrant:6333

# Embeddings (pick one)
VOYAGE_API_KEY=your_voyage_key

# LLM (pick one — Groq is free)
GROQ_API_KEY=your_groq_key        # free at console.groq.com
# ANTHROPIC_API_KEY=your_key      # paid
# GEMINI_API_KEY=your_key         # free tier limited

# Optional
MIN_CONFIDENCE=low                 # low|medium|high — gates comment posting
CORS_ORIGINS=http://localhost:3000
```

### 2. Register the GitHub App

1. Go to **github.com/settings/apps → New GitHub App**
2. Set:
   - **Homepage URL:** `http://localhost:8000`
   - **Webhook URL:** your smee.io URL (see step 3)
   - **Webhook secret:** `openssl rand -hex 32`
   - **Permissions:** Issues (RW), Pull requests (R), Contents (R), Metadata (R)
   - **Events:** Issues, Pull request, Push, Installation
3. Click **Create GitHub App**, note the **App ID**
4. Scroll to **Private keys → Generate a private key** → download `.pem`
5. `mkdir -p certs && cp ~/Downloads/*.pem certs/github-app.pem`

### 3. Set up webhook proxy (local dev)

```bash
npm install --global smee-client
# Create channel at https://smee.io, copy URL
smee --url https://smee.io/YOUR_CHANNEL --target http://localhost:8000/webhooks/github
```

### 4. Start everything

```bash
docker compose up
```

This starts all 6 services. Run migrations on first boot:

```bash
docker compose exec backend sh -c "PYTHONPATH=/app alembic upgrade head"
```

### 5. Install the GitHub App on a repo

Go to your GitHub App → **Install App** → pick a repo. This triggers an `installation` webhook which auto-enqueues backfill + indexing.

### 6. Test it

Create a new issue on the installed repo. Within ~10 seconds, TriageCopilot posts a triage comment.

## Running Tests

```bash
cd backend
pytest tests/ -v                    # unit tests only (fast)
pytest tests/ -m integration -v     # requires live Postgres + Qdrant
```

## Smoke Test

```bash
./scripts/smoke_test.sh             # requires docker compose up
```

## Manual Backfill

```bash
docker compose exec worker python -c "
from app.workers.ingestion_tasks import backfill_repo
backfill_repo.delay(1)  # repo_id from the repos table
"
```

## Running the Full Stack

```
Backend API:   http://localhost:8000
Frontend:      http://localhost:3000
API docs:      http://localhost:8000/docs
Qdrant UI:     http://localhost:6333/dashboard
```

## Deployment

| Service | Platform |
|---|---|
| Backend + Worker | Railway / Render / Fly.io |
| Qdrant | Hetzner VPS or Qdrant Cloud |
| Frontend | Vercel |
| Redis | Upstash |
| Postgres | Supabase / Railway |

## Progress

| Day | Deliverable |
|---|---|
| 1 | Scaffold, Docker Compose, webhook verification, ORM schema, Alembic migrations |
| 2 | Backfill pipeline: issues, PRs, commits, files, graph edges |
| 3 | Tree-sitter chunkers, Voyage AI embeddings, `index_repo` Celery task |
| 4 | Hybrid retrieval: BM25 + dense + RRF, `/search` endpoint |
| 5 | 1-hop graph expansion, Cohere reranker, LLM triage, `/triage` endpoint |
| 6 | Webhook → Celery → GitHub comment end-to-end, `push` incremental index |
| 7 | Eval harness, precision/recall metrics, baseline report |
| 8 | Confidence calibration, incremental indexing, Redis semantic cache |
| 9 | Next.js 14 App Router dashboard: repo list, issue view, triage detail |
| 10 | Test suite cleanup, CORS, full Docker stack, smoke tests, multi-LLM support |
