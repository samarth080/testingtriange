# TriageCopilot — System Design

**Date:** 2026-04-12
**Status:** Approved

---

## 1. Goal

A production-grade GitHub App that, when installed on a repository, listens for new issues and posts a structured triage comment containing: likely duplicates (with confidence scores), suggested labels, relevant files from the codebase, a suggested assignee, and reasoning with citations to retrieved chunks.

---

## 2. Non-Negotiables

- Production code quality: fully typed (mypy strict), tested, modular, Dockerized
- Every retrieval and LLM choice justified in code comments
- Evaluation harness with RAGAS + custom precision@k metrics
- No fixed-size chunking — source-aware strategies only
- Graph expansion in retrieval is the core differentiator — must not be skipped

---

## 3. Repository Structure (Monorepo)

```
triage-copilot/
├── backend/
│   ├── app/
│   │   ├── api/               # FastAPI routers: webhooks, retrieve, triage, repos
│   │   ├── workers/           # Celery task definitions (ingestion, triage)
│   │   ├── ingestion/         # GitHub backfill logic, per-type fetchers
│   │   ├── chunking/          # Tree-sitter, markdown, discussion, commit chunkers
│   │   ├── retrieval/         # Hybrid search, graph expansion, reranker
│   │   ├── llm/               # Router prompt, synthesis prompts, JSON validation
│   │   ├── actions/           # GitHub comment formatting and posting
│   │   ├── models/            # SQLAlchemy ORM + Pydantic schemas
│   │   └── core/              # Config, settings, GitHub auth, dependencies
│   ├── alembic/               # Migration scripts
│   ├── tests/                 # Unit + integration tests
│   ├── Dockerfile
│   └── pyproject.toml
├── frontend/
│   ├── app/                   # Next.js 14 app router
│   ├── components/            # shadcn/ui components
│   └── Dockerfile
├── eval/
│   ├── label_issues.py        # Hand-labeling CLI
│   ├── run_eval.py            # RAGAS + precision@k runner
│   └── results.md             # Committed eval report
├── docker-compose.yml
├── .env.example
└── README.md
```

---

## 4. Tech Stack

| Layer | Choice | Fallback |
|---|---|---|
| Backend framework | FastAPI + Uvicorn | — |
| Task queue | Celery + Redis | — |
| Database | Postgres 15 (SQLAlchemy 2 + Alembic) | — |
| Vector DB | Qdrant (self-hosted Docker) | — |
| Code embeddings | voyage-code-3 | bge-large-en (HuggingFace) |
| Text embeddings | text-embedding-3-large | bge-large-en (HuggingFace) |
| Reranker | Cohere Rerank v3 | bge-reranker-large (HuggingFace) |
| LLM | Claude Sonnet via Anthropic API | — |
| Code parsing | tree-sitter (Python, JS, TS, Go) | — |
| Frontend | Next.js 14 + Tailwind + shadcn/ui | — |
| Deploy | Docker Compose (local), Railway (backend), Vercel (frontend), Hetzner (Qdrant) | — |

API keys are optional at startup — the system detects available keys and falls back to open-source models automatically.

---

## 5. Data Model

### Tables

**repos**
- `id`, `github_id`, `owner`, `name`, `installation_id`, `backfill_status`, `created_at`, `updated_at`

**issues**
- `id`, `repo_id`, `github_number`, `title`, `body`, `state`, `author`, `labels` (JSONB), `created_at`, `closed_at`

**pull_requests**
- `id`, `repo_id`, `github_number`, `title`, `body`, `state`, `author`, `merged_at`, `linked_issue_numbers` (JSONB)

**commits**
- `id`, `repo_id`, `sha`, `message`, `author`, `committed_at`, `changed_files` (JSONB)

**files**
- `id`, `repo_id`, `path`, `language`, `content_hash`, `last_indexed_at`

**chunks**
- `id`, `repo_id`, `source_type` (code|discussion|doc|commit), `source_id`, `chunk_index`, `text`, `metadata` (JSONB), `embedding_model`, `qdrant_point_id`, `qdrant_collection`

**relationships** (graph edges)
- `id`, `repo_id`, `source_type`, `source_id`, `target_type`, `target_id`, `edge_type` (issue_pr|pr_file|issue_issue|commit_file)

**triage_results**
- `id`, `repo_id`, `issue_id`, `output` (JSONB), `comment_url`, `latency_ms`, `created_at`

---

## 6. Ingestion Pipeline

Triggered on GitHub App `installation` event (full backfill) and incrementally on `issues`, `pull_request`, `push` events.

Backfill scope: last 2 years of issues, PRs, comments, commits; README, CONTRIBUTING, docs/, top-level source files.

All fetching runs as Celery tasks:
- `tasks.backfill_repo(repo_id)` — fan-out to per-type subtasks
- `tasks.index_issue(issue_id)` — chunk + embed + upsert to Qdrant
- `tasks.index_file(file_id)` — tree-sitter chunk + embed + upsert

---

## 7. Chunking Strategy (source-aware)

| Source | Strategy |
|---|---|
| Code files | tree-sitter AST at function/class granularity. Metadata: file path, language, symbol name, start/end line |
| Issues/PRs | One chunk per conversation thread = title + body + top 5 comments. Metadata: labels, state, author, linked refs |
| Markdown docs | Header-aware splitting (split at H1/H2 boundaries, max 800 tokens). Metadata: heading path |
| Commits | Message + changed files list as one chunk. Metadata: sha, author, date |

No fixed-size fallback — if a source type is unrecognized, it is skipped with a warning, not chunked naively.

---

## 8. Retrieval Pipeline

Three stages, run per query:

**Stage 1 — Hybrid search (per collection)**
- Collections: `code_chunks`, `discussion_chunks`
- Dense: voyage-code-3 / bge-large-en
- Sparse: BM25 via Qdrant sparse vectors
- Fusion: Reciprocal Rank Fusion (RRF) with k=60
- Pre-filters: `repo_id`, optional date range, optional state

**Stage 2 — Graph expansion**
- For each of the top-20 candidates, look up 1-hop neighbors in `relationships` table
- Add neighbors to candidate set (capped at 2× the initial result count)
- Deduplication by `chunk_id`

**Stage 3 — Reranker**
- Cohere Rerank v3 (fallback: bge-reranker-large) over expanded candidate set
- Top-50 candidates → top-8 returned

Exposed as `POST /retrieve` and called internally by `POST /triage`.

---

## 9. LLM Layer

**Router prompt** — classifies incoming issue into: `bug | feature | question | duplicate_candidate`

**Synthesis prompt** — specialized per class, includes retrieved chunks as context with `[chunk_id]` citation markers

**Output schema (enforced JSON)**
```json
{
  "likely_duplicates": [
    {"issue_id": 123, "confidence": 0.87, "reasoning": "string"}
  ],
  "suggested_labels": ["bug", "performance"],
  "relevant_files": [
    {"path": "src/foo.py", "relevance": "string"}
  ],
  "suggested_assignee": {"login": "alice", "reasoning": "string"},
  "reasoning": "string",
  "citations": [
    {"doc_type": "issue", "doc_id": 123, "chunk_id": "abc-001"}
  ]
}
```

Duplicate suggestions with `confidence < threshold` are filtered before the comment is posted. Threshold is tuned in Day 8 from eval data (initial value: 0.75).

Model: `claude-sonnet-4-6`. Structured output via tool-use / JSON mode.

---

## 10. Action Layer

On new issue webhook event:
1. Enqueue `tasks.triage_issue(issue_id)`
2. Worker runs retrieval + LLM synthesis
3. Format result as collapsible GitHub markdown comment
4. Post via GitHub API (`POST /repos/{owner}/{repo}/issues/{number}/comments`)
5. Store `triage_result` row in Postgres

Target latency: < 10 seconds end-to-end (measured from webhook receipt to comment posted).

---

## 11. Frontend (Next.js 14)

Pages:
- `/` — Connect repo flow (GitHub App install link)
- `/repos/[id]` — Triage history list
- `/repos/[id]/issues/[number]` — Per-issue explainability panel (retrieved chunks + reasoning chain)
- `/repos/[id]/metrics` — Eval scores dashboard

Stack: Next.js 14 app router, Tailwind CSS, shadcn/ui, React Query for data fetching.

---

## 12. Evaluation Harness

Target dataset: 40 hand-labeled historical issues from a medium OSS repo (~500 issues total).

Labels per issue:
- True duplicate issue numbers (if any)
- Correct files (ground truth relevant files)
- Correct labels

Metrics:
- `precision@3` for duplicate detection
- `file_suggestion_accuracy@5`
- RAGAS: `faithfulness`, `context_precision`

Output: `/eval/results.md` committed to repo.

---

## 13. Day-by-Day Delivery Schedule

| Day | Deliverable |
|---|---|
| 1 | Repo scaffold, Docker Compose, FastAPI skeleton, webhook + HMAC-SHA256 verification, SQLAlchemy models, Alembic migration, GitHub App registration guide, smee.io proxy setup, README stub |
| 2 | Full backfill pipeline (issues, PRs, commits, files), Celery workers, end-to-end test on one real repo |
| 3 | Tree-sitter chunker (Python/JS/TS/Go), markdown chunker, discussion chunker; unit tests; embeddings in Qdrant |
| 4 | Hybrid retrieval (BM25 + dense + RRF), `/retrieve` endpoint, logging |
| 5 | Graph expansion + Cohere reranker + metadata filters; router prompt + synthesis prompts + JSON validation; `/triage` endpoint |
| 6 | Webhook → triage → GitHub comment end-to-end on sandbox repo |
| 7 | Hand-label 40 issues, eval harness, baseline run, commit `/eval/results.md` |
| 8 | Duplicate confidence calibration, incremental indexing (<10s latency), semantic cache |
| 9 | Next.js dashboard (connect repo, history, explainability, metrics) deployed to Vercel |
| 10 | Full Docker deploy (Railway + Hetzner), GitHub App listing, README with mermaid diagram + demo GIF + metrics table, 90s demo video |

---

## 14. Environment Variables (.env.example)

```
# GitHub App (required for all webhook features)
GITHUB_APP_ID=
GITHUB_PRIVATE_KEY_PATH=./certs/github-app.pem
GITHUB_WEBHOOK_SECRET=

# Postgres
DATABASE_URL=postgresql+asyncpg://triage:triage@localhost:5432/triage

# Redis
REDIS_URL=redis://localhost:6379/0

# Qdrant
QDRANT_URL=http://localhost:6333

# Paid embeddings (optional — falls back to bge-large-en if unset)
VOYAGE_API_KEY=
OPENAI_API_KEY=

# Reranker (optional — falls back to bge-reranker-large if unset)
COHERE_API_KEY=

# LLM (required for triage)
ANTHROPIC_API_KEY=
```
