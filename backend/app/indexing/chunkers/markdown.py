"""
Markdown chunker — splits text on headings (# / ## / etc.).

Strategy:
1. Find all heading positions with regex.
2. Each heading starts a new section; section text = heading + body until next heading.
3. Short sections (< min_chars) are merged into the previous chunk.
4. Returns a list of ChunkData with metadata["heading"] set.
"""
import re
from app.indexing.chunkers import ChunkData

# Matches ATX headings: "# Title" / "## Title" etc.
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)

# Default minimum section size before merging into previous chunk
_DEFAULT_MIN_CHARS = 100


def chunk_markdown(text: str, min_chars: int = _DEFAULT_MIN_CHARS) -> list[ChunkData]:
    """
    Split markdown text into chunks on heading boundaries.

    Args:
        text:      The full markdown string.
        min_chars: Sections shorter than this are merged into the previous chunk.

    Returns:
        List of ChunkData ordered by position. Empty list if text is empty.
    """
    if not text or not text.strip():
        return []

    # Find all heading match positions
    matches = list(_HEADING_RE.finditer(text))

    if not matches:
        # No headings — the whole text is one chunk
        return [ChunkData(text=text.strip(), chunk_index=0, metadata={"heading": ""})]

    # Build raw sections: each section = text from this heading to the next
    sections: list[tuple[str, str]] = []  # (heading_title, section_text)
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        heading_title = match.group(1).strip()
        section_text = text[start:end].strip()
        sections.append((heading_title, section_text))

    # Capture any text before the first heading as a preamble
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.insert(0, ("", preamble))

    # Merge short sections into the previous chunk
    merged: list[tuple[str, str]] = []
    for heading, body in sections:
        if merged and len(body) < min_chars:
            prev_heading, prev_body = merged[-1]
            merged[-1] = (prev_heading, prev_body + "\n\n" + body)
        else:
            merged.append((heading, body))

    return [
        ChunkData(text=body, chunk_index=i, metadata={"heading": heading})
        for i, (heading, body) in enumerate(merged)
    ]
