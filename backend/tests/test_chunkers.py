"""
Unit tests for all three chunkers.
No DB, no network — pure-unit tests.
"""
import pytest
from app.indexing.chunkers import ChunkData
from app.indexing.chunkers.markdown import chunk_markdown


def test_chunk_markdown_single_section():
    text = "# Introduction\n\nThis is the intro."
    chunks = chunk_markdown(text)
    assert len(chunks) == 1
    assert "Introduction" in chunks[0].text
    assert "This is the intro." in chunks[0].text
    assert chunks[0].chunk_index == 0


def test_chunk_markdown_multiple_headings():
    text = "# Setup\n\nInstall deps.\n\n## Config\n\nSet env vars.\n\n# Usage\n\nRun the app."
    chunks = chunk_markdown(text, min_chars=1)
    assert len(chunks) == 3
    assert chunks[0].metadata["heading"] == "Setup"
    assert chunks[1].metadata["heading"] == "Config"
    assert chunks[2].metadata["heading"] == "Usage"
    for i, c in enumerate(chunks):
        assert c.chunk_index == i


def test_chunk_markdown_no_headings():
    text = "Just plain text.\nNo headings here.\nStill one chunk."
    chunks = chunk_markdown(text)
    assert len(chunks) == 1
    assert chunks[0].metadata["heading"] == ""


def test_chunk_markdown_empty():
    chunks = chunk_markdown("")
    assert chunks == []


def test_chunk_markdown_merges_short_sections():
    """Sections shorter than min_chars are merged into the previous chunk."""
    text = "# A\n\nHi.\n\n# B\n\nBye."
    chunks = chunk_markdown(text, min_chars=50)
    # Both sections are < 50 chars each so they merge into one chunk
    assert len(chunks) == 1
    assert "Hi." in chunks[0].text
    assert "Bye." in chunks[0].text


def test_chunk_markdown_returns_chunk_data():
    chunks = chunk_markdown("# Hello\n\nWorld")
    assert all(isinstance(c, ChunkData) for c in chunks)
