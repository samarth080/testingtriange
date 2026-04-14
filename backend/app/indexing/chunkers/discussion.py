"""
Discussion chunker — formats Issue and PR data as markdown, then chunks by heading.

Each entity becomes a markdown document:
  # Issue #42: Fix memory leak
  Labels: bug, performance | State: open

  <body text>

The document is then run through the markdown chunker. Source metadata
(github_number, labels, state) is injected into every resulting ChunkData.
"""
from app.indexing.chunkers import ChunkData
from app.indexing.chunkers.markdown import chunk_markdown


def chunk_issue(
    github_number: int,
    title: str,
    body: str | None,
    labels: list[str],
    state: str,
) -> list[ChunkData]:
    """
    Chunk a GitHub issue into ChunkData objects.

    Returns at least one chunk (even if body is None).
    All chunks carry source_type/github_number/labels/state in metadata.
    """
    header = f"# Issue #{github_number}: {title}\n"
    if labels:
        header += f"Labels: {', '.join(labels)} | "
    header += f"State: {state}\n"

    doc = header + "\n" + (body or "")

    raw_chunks = chunk_markdown(doc)
    if not raw_chunks:
        raw_chunks = [ChunkData(text=doc.strip(), chunk_index=0)]

    base_meta = {
        "source_type": "issue",
        "github_number": github_number,
        "labels": labels,
        "state": state,
        "title": title,
    }

    return [
        ChunkData(
            text=c.text,
            chunk_index=i,
            metadata={**base_meta, "heading": c.metadata.get("heading", "")},
        )
        for i, c in enumerate(raw_chunks)
    ]


def chunk_pull_request(
    github_number: int,
    title: str,
    body: str | None,
    state: str,
) -> list[ChunkData]:
    """
    Chunk a GitHub PR into ChunkData objects.

    Returns at least one chunk (even if body is None).
    All chunks carry source_type/github_number/state in metadata.
    """
    header = f"# PR #{github_number}: {title}\nState: {state}\n"
    doc = header + "\n" + (body or "")

    raw_chunks = chunk_markdown(doc)
    if not raw_chunks:
        raw_chunks = [ChunkData(text=doc.strip(), chunk_index=0)]

    base_meta = {
        "source_type": "pull_request",
        "github_number": github_number,
        "state": state,
        "title": title,
    }

    return [
        ChunkData(
            text=c.text,
            chunk_index=i,
            metadata={**base_meta, "heading": c.metadata.get("heading", "")},
        )
        for i, c in enumerate(raw_chunks)
    ]
