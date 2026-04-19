#!/usr/bin/env python3
"""
TriageCopilot eval harness.

Usage (from repo root, backend virtualenv active):
    cd eval
    python run_eval.py --repo owner/repo [--limit 50] [--output results.md] [--state closed]

Prerequisites:
    - Backend virtualenv activated:
        cd backend && pip install -e ".[dev]"
    - Postgres + Qdrant running
    - .env in backend/ (or environment variables) with DATABASE_URL, QDRANT_URL,
      ANTHROPIC_API_KEY, and at least one of VOYAGE_API_KEY / OPENAI_API_KEY
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

# ── Path setup: allow importing backend/app without a pip install ──────────
_BACKEND = os.path.join(os.path.dirname(__file__), "..", "backend")
sys.path.insert(0, os.path.abspath(_BACKEND))

# ── eval/ siblings (loader, runner, metrics) ──────────────────────────────
_EVAL = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(_EVAL))

from sqlalchemy import select  # noqa: E402 — after sys.path setup

from app.core.config import settings  # noqa: E402
from app.core.database import AsyncSessionLocal  # noqa: E402
from app.indexing.embedder import embedder_from_settings  # noqa: E402
from app.indexing.qdrant_store import QdrantStore  # noqa: E402
from app.models.orm import Repo  # noqa: E402

from loader import load_eval_issues  # noqa: E402
from metrics import aggregate_metrics, format_report  # noqa: E402
from runner import eval_issue  # noqa: E402


async def _run(repo_slug: str, limit: int, state: str, output: str) -> None:
    try:
        owner, name = repo_slug.split("/", 1)
    except ValueError:
        print(f"ERROR: --repo must be in 'owner/name' format, got: {repo_slug!r}", file=sys.stderr)
        sys.exit(1)

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Repo).where(Repo.owner == owner, Repo.name == name)
        )
        repo = result.scalar_one_or_none()
        if repo is None:
            print(
                f"ERROR: Repo '{repo_slug}' not found in the database.\n"
                "Run the backfill pipeline first (Day 2).",
                file=sys.stderr,
            )
            sys.exit(1)

        issues = await load_eval_issues(session, repo.id, limit=limit, state=state)
        if not issues:
            print(
                f"No labeled {state!r} issues found for {repo_slug}.\n"
                "Try --state all or --limit with a larger number.",
                file=sys.stderr,
            )
            sys.exit(0)

        print(f"Evaluating {len(issues)} issues from {repo_slug} (state={state!r}) ...")

        embedder = embedder_from_settings()
        qdrant = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension, api_key=settings.qdrant_api_key)

        per_issue: list[dict] = []
        for i, issue in enumerate(issues, start=1):
            print(
                f"  [{i:>3}/{len(issues)}] issue #{issue.github_number:<6}",
                end=" ",
                flush=True,
            )
            record = await eval_issue(session, repo.id, issue, embedder, qdrant, settings)
            per_issue.append(record)
            print(
                f"F1={record['f1']:.2f}  conf={record['confidence']:<6}  "
                f"latency={record['latency_ms']}ms"
            )
            if i < len(issues):
                await asyncio.sleep(22)  # Voyage free tier: 3 RPM limit

    agg = aggregate_metrics(per_issue)
    report = format_report(repo_slug, per_issue, agg)

    with open(output, "w", encoding="utf-8") as fh:
        fh.write(report)

    print(f"\nResults written to: {output}")
    print(
        f"Label F1={agg.get('label_f1', 0):.3f}  "
        f"P={agg.get('label_precision', 0):.3f}  "
        f"R={agg.get('label_recall', 0):.3f}  "
        f"avg_latency={agg.get('latency_avg_ms', '—')}ms"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the TriageCopilot eval harness against labeled historical issues.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--repo", required=True, metavar="OWNER/NAME",
                        help="GitHub repo slug to evaluate (must exist in the database)")
    parser.add_argument("--limit", type=int, default=50,
                        help="Maximum number of issues to evaluate")
    parser.add_argument("--output", default="results.md",
                        help="Path to write the markdown results report")
    parser.add_argument("--state", default="closed",
                        choices=["open", "closed", "all"],
                        help="Issue state filter")
    args = parser.parse_args()

    asyncio.run(_run(args.repo, args.limit, args.state, args.output))


if __name__ == "__main__":
    main()
