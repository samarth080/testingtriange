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
