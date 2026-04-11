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
    # Named chunk_metadata to avoid collision with SQLAlchemy's reserved Base.metadata attribute
    chunk_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
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
