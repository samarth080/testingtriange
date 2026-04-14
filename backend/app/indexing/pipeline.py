"""
Indexing pipeline — orchestrates chunk → embed → store for a repo.

Two entry points:
  index_repo_files(session, repo, github_client, embedder, qdrant, default_branch)
    Downloads each file from GitHub, chunks by language, embeds, stores in Qdrant + Postgres.

  index_repo_discussions(session, repo, embedder, qdrant)
    Reads issues and PRs from Postgres, chunks as markdown, embeds, stores.

Both functions are idempotent (upsert on Postgres; stable UUIDs on Qdrant).
"""
import base64
import hashlib
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing.chunkers import ChunkData
from app.indexing.chunkers.code import chunk_code
from app.indexing.chunkers.discussion import chunk_issue, chunk_pull_request
from app.indexing.embedder import Embedder
from app.indexing.qdrant_store import (
    CODE_COLLECTION,
    DISCUSSION_COLLECTION,
    QdrantStore,
    point_id,
)
from app.models.orm import Chunk, File, Issue, PullRequest, Repo

logger = logging.getLogger(__name__)

MAX_FILE_SIZE_BYTES = 500_000


async def _upsert_chunks(
    session: AsyncSession,
    repo_id: int,
    source_type: str,
    source_id: int,
    chunks: list[ChunkData],
    vectors: list[list[float]],
    embedding_model: str,
    qdrant_collection: str,
    qdrant: QdrantStore,
) -> None:
    """Store chunks in Postgres and Qdrant. Called by both indexers."""
    if not chunks:
        return

    qdrant_points = []
    for chunk, vector in zip(chunks, vectors):
        pid = point_id(repo_id, source_type, source_id, chunk.chunk_index)

        stmt = (
            insert(Chunk)
            .values(
                repo_id=repo_id,
                source_type=source_type,
                source_id=source_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                chunk_metadata=chunk.metadata,
                embedding_model=embedding_model,
                qdrant_point_id=pid,
                qdrant_collection=qdrant_collection,
            )
            .on_conflict_do_update(
                constraint="uq_chunks_source",
                set_={
                    "text": chunk.text,
                    "metadata": chunk.metadata,  # DB column name, not ORM attr name
                    "embedding_model": embedding_model,
                    "qdrant_point_id": pid,
                    "qdrant_collection": qdrant_collection,
                },
            )
        )
        await session.execute(stmt)

        qdrant_points.append(
            {
                "id": pid,
                "vector": vector,
                "payload": {
                    "repo_id": repo_id,
                    "source_type": source_type,
                    "source_id": source_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    **chunk.metadata,
                },
            }
        )

    await session.commit()
    await qdrant.upsert_points(qdrant_collection, qdrant_points)


async def index_repo_files(
    session: AsyncSession,
    repo: Repo,
    github_client,
    embedder: Embedder,
    qdrant: QdrantStore,
    default_branch: str = "main",
) -> int:
    """
    Download, chunk, embed, and store all indexable files for a repo.

    Only processes files with a known language (language IS NOT NULL).
    Skips files larger than MAX_FILE_SIZE_BYTES.

    Returns: count of files indexed.
    """
    result = await session.execute(
        select(File).where(File.repo_id == repo.id, File.language.isnot(None))
    )
    files = result.scalars().all()

    indexed = 0
    for file in files:
        try:
            path = f"/repos/{repo.owner}/{repo.name}/contents/{file.path}?ref={default_branch}"
            data = await github_client.get(path)

            size = data.get("size", 0)
            if size > MAX_FILE_SIZE_BYTES:
                logger.debug("Skipping large file %s (%d bytes)", file.path, size)
                continue

            raw_b64 = data.get("content", "").replace("\n", "")
            if not raw_b64:
                continue

            content_bytes = base64.b64decode(raw_b64)
            source = content_bytes.decode("utf-8", errors="replace")
            content_hash = hashlib.sha256(content_bytes).hexdigest()

            chunks = chunk_code(source, language=file.language, file_path=file.path)
            if not chunks:
                continue

            vectors = await embedder.embed_batch([c.text for c in chunks])

            await _upsert_chunks(
                session,
                repo_id=repo.id,
                source_type="file",
                source_id=file.id,
                chunks=chunks,
                vectors=vectors,
                embedding_model=embedder.model,
                qdrant_collection=CODE_COLLECTION,
                qdrant=qdrant,
            )

            file.content_hash = content_hash
            file.last_indexed_at = datetime.now(tz=timezone.utc)
            await session.commit()

            indexed += 1

        except Exception:
            logger.exception(
                "Failed to index file %s for repo %s/%s", file.path, repo.owner, repo.name
            )
            continue

    logger.info("Indexed %d files for %s/%s", indexed, repo.owner, repo.name)
    return indexed


async def index_repo_discussions(
    session: AsyncSession,
    repo: Repo,
    embedder: Embedder,
    qdrant: QdrantStore,
) -> dict:
    """
    Chunk, embed, and store all issues and PRs for a repo.

    Returns: {"issues": count, "pull_requests": count}
    """
    issues_result = await session.execute(
        select(Issue).where(Issue.repo_id == repo.id)
    )
    issues = issues_result.scalars().all()

    issue_count = 0
    for issue in issues:
        try:
            chunks = chunk_issue(
                github_number=issue.github_number,
                title=issue.title,
                body=issue.body,
                labels=issue.labels or [],
                state=issue.state,
            )
            vectors = await embedder.embed_batch([c.text for c in chunks])
            await _upsert_chunks(
                session,
                repo_id=repo.id,
                source_type="issue",
                source_id=issue.id,
                chunks=chunks,
                vectors=vectors,
                embedding_model=embedder.model,
                qdrant_collection=DISCUSSION_COLLECTION,
                qdrant=qdrant,
            )
            issue_count += 1
        except Exception:
            logger.exception("Failed to index issue #%d", issue.github_number)
            continue

    prs_result = await session.execute(
        select(PullRequest).where(PullRequest.repo_id == repo.id)
    )
    prs = prs_result.scalars().all()

    pr_count = 0
    for pr in prs:
        try:
            chunks = chunk_pull_request(
                github_number=pr.github_number,
                title=pr.title,
                body=pr.body,
                state=pr.state,
            )
            vectors = await embedder.embed_batch([c.text for c in chunks])
            await _upsert_chunks(
                session,
                repo_id=repo.id,
                source_type="pull_request",
                source_id=pr.id,
                chunks=chunks,
                vectors=vectors,
                embedding_model=embedder.model,
                qdrant_collection=DISCUSSION_COLLECTION,
                qdrant=qdrant,
            )
            pr_count += 1
        except Exception:
            logger.exception("Failed to index PR #%d", pr.github_number)
            continue

    logger.info(
        "Indexed discussions for %s/%s: %d issues, %d PRs",
        repo.owner, repo.name, issue_count, pr_count,
    )
    return {"issues": issue_count, "pull_requests": pr_count}
