"""
One-hop graph expansion for retrieved chunks.

After the initial RRF retrieval, we walk the relationships table one hop
to pull in related entities (e.g. the PR that closed a retrieved issue,
or the files changed by that PR). This broadens context for the reranker.
"""
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.orm import Chunk, File, Issue, PullRequest, Relationship
from app.retrieval import SearchResult


async def graph_expand(
    session: AsyncSession,
    results: list[SearchResult],
    repo_id: int,
    max_neighbors: int = 20,
) -> list[SearchResult]:
    """
    Expand the result set by one hop in the relationship graph.

    For each unique (source_type, source_id) in results, fetch relationship
    rows from the DB and load chunks for the neighbor entities.
    Deduplicates by chunk_id; neighbors are appended with rrf_score=0.0.
    """
    if not results:
        return results

    seen_chunk_ids = {r.chunk_id for r in results}
    sources = list({(r.source_type, r.source_id) for r in results})

    source_conditions = [
        and_(Relationship.source_type == st, Relationship.source_id == sid)
        for st, sid in sources
    ]
    rel_rows = await session.execute(
        select(Relationship).where(
            Relationship.repo_id == repo_id,
            or_(*source_conditions),
        )
    )
    relationships = rel_rows.scalars().all()

    if not relationships:
        return results

    neighbor_conditions = [
        and_(Chunk.source_type == r.target_type, Chunk.source_id == r.target_id)
        for r in relationships
    ]
    chunk_rows = await session.execute(
        select(Chunk).where(
            Chunk.repo_id == repo_id,
            or_(*neighbor_conditions),
        )
    )
    neighbor_chunks_raw = chunk_rows.scalars().all()

    if not neighbor_chunks_raw:
        return results

    # Only batch-fetch entities for chunks we haven't seen yet
    new_chunks = [c for c in neighbor_chunks_raw if c.id not in seen_chunk_ids]
    file_ids = {c.source_id for c in new_chunks if c.source_type == "file"}
    issue_ids = {c.source_id for c in new_chunks if c.source_type == "issue"}
    pr_ids = {c.source_id for c in new_chunks if c.source_type == "pull_request"}

    files: dict[int, File] = {}
    issues: dict[int, Issue] = {}
    prs: dict[int, PullRequest] = {}

    if file_ids:
        r = await session.execute(select(File).where(File.id.in_(file_ids)))
        files = {f.id: f for f in r.scalars().all()}
    if issue_ids:
        r = await session.execute(select(Issue).where(Issue.id.in_(issue_ids)))
        issues = {i.id: i for i in r.scalars().all()}
    if pr_ids:
        r = await session.execute(select(PullRequest).where(PullRequest.id.in_(pr_ids)))
        prs = {p.id: p for p in r.scalars().all()}

    neighbor_results: list[SearchResult] = []
    for chunk in neighbor_chunks_raw:
        if chunk.id in seen_chunk_ids or len(neighbor_results) >= max_neighbors:
            continue
        seen_chunk_ids.add(chunk.id)

        if chunk.source_type == "file":
            entity = files.get(chunk.source_id)
            title = entity.path if entity else ""
            github_number = None
        elif chunk.source_type == "issue":
            entity = issues.get(chunk.source_id)
            title = entity.title if entity else ""
            github_number = entity.github_number if entity else None
        elif chunk.source_type == "pull_request":
            entity = prs.get(chunk.source_id)
            title = entity.title if entity else ""
            github_number = entity.github_number if entity else None
        else:
            title, github_number = "", None

        neighbor_results.append(
            SearchResult(
                chunk_id=chunk.id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                metadata=chunk.chunk_metadata,
                source_type=chunk.source_type,
                source_id=chunk.source_id,
                rrf_score=0.0,
                source_title=title,
                github_number=github_number,
            )
        )

    return results + neighbor_results
