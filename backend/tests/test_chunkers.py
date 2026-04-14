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
    # min_chars=1: the test bodies ("Install deps.", "Set env vars.", "Run the app.")
    # are each < 100 chars and would merge under the production default.
    # We pass min_chars=1 to keep the three sections separate for this structural test.
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


from app.indexing.chunkers.discussion import chunk_issue, chunk_pull_request


def test_chunk_issue_basic():
    chunks = chunk_issue(
        github_number=42,
        title="Fix memory leak",
        body="The server leaks on every request.\n\n## Reproduction\n\n`curl localhost`",
        labels=["bug", "performance"],
        state="open",
    )
    assert len(chunks) >= 1
    # First chunk must contain the title
    assert "Fix memory leak" in chunks[0].text
    assert chunks[0].metadata["source_type"] == "issue"
    assert chunks[0].metadata["github_number"] == 42
    assert chunks[0].metadata["labels"] == ["bug", "performance"]


def test_chunk_issue_none_body():
    chunks = chunk_issue(
        github_number=1,
        title="Empty issue",
        body=None,
        labels=[],
        state="open",
    )
    assert len(chunks) == 1
    assert "Empty issue" in chunks[0].text


def test_chunk_pull_request_basic():
    chunks = chunk_pull_request(
        github_number=10,
        title="Add rate limiting",
        body="## Summary\n\nAdds rate limiting.\n\n## Testing\n\nRan load tests.",
        state="merged",
    )
    assert len(chunks) >= 1
    assert "Add rate limiting" in chunks[0].text
    assert chunks[0].metadata["source_type"] == "pull_request"
    assert chunks[0].metadata["github_number"] == 10


def test_chunk_pull_request_chunk_indices_are_sequential():
    long_body = "\n\n".join([f"## Section {i}\n\n" + "Content. " * 30 for i in range(5)])
    chunks = chunk_pull_request(
        github_number=5,
        title="Big PR",
        body=long_body,
        state="open",
    )
    for i, c in enumerate(chunks):
        assert c.chunk_index == i


from app.indexing.chunkers.code import chunk_code


PYTHON_SOURCE = '''\
def add(a, b):
    """Add two numbers."""
    return a + b


class Calculator:
    """Simple calculator."""

    def multiply(self, x, y):
        return x * y

    def divide(self, x, y):
        if y == 0:
            raise ValueError("Cannot divide by zero")
        return x / y
'''

JS_SOURCE = '''\
function greet(name) {
    return `Hello, ${name}!`;
}

class Greeter {
    constructor(prefix) {
        this.prefix = prefix;
    }

    greet(name) {
        return `${this.prefix} ${name}`;
    }
}
'''


def test_chunk_code_python_extracts_functions_and_classes():
    chunks = chunk_code(PYTHON_SOURCE, language="python", file_path="math.py")
    texts = [c.text for c in chunks]
    # Should have at least the top-level function and class
    assert any("def add" in t for t in texts)
    assert any("class Calculator" in t for t in texts)
    for c in chunks:
        assert c.metadata["language"] == "python"
        assert c.metadata["file_path"] == "math.py"
        assert "symbol" in c.metadata


def test_chunk_code_javascript_extracts_nodes():
    chunks = chunk_code(JS_SOURCE, language="javascript", file_path="greet.js")
    texts = [c.text for c in chunks]
    assert any("function greet" in t for t in texts)
    assert any("class Greeter" in t for t in texts)


def test_chunk_code_chunk_indices_are_sequential():
    chunks = chunk_code(PYTHON_SOURCE, language="python", file_path="math.py")
    for i, c in enumerate(chunks):
        assert c.chunk_index == i


def test_chunk_code_unknown_language_falls_back_to_line_windows():
    source = "line\n" * 20
    chunks = chunk_code(source, language="cobol", file_path="old.cbl")
    assert len(chunks) >= 1
    for c in chunks:
        assert c.metadata["language"] == "cobol"


def test_chunk_code_empty_source():
    chunks = chunk_code("", language="python", file_path="empty.py")
    assert chunks == []


def test_chunk_code_go_extracts_functions():
    go_source = '''\
package main

import "fmt"

func hello(name string) string {
    return fmt.Sprintf("Hello, %s!", name)
}

type Greeter struct {
    Prefix string
}

func (g Greeter) Greet(name string) string {
    return g.Prefix + " " + name
}
'''
    chunks = chunk_code(go_source, language="go", file_path="main.go")
    texts = [c.text for c in chunks]
    assert any("func hello" in t for t in texts)
