# Day 3: Indexing Pipeline — Chunkers + Embeddings + Qdrant

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full indexing pipeline that chunks code files, issues, and PRs; embeds them with Voyage or OpenAI; and stores vectors in Qdrant with back-pointers in Postgres.

**Architecture:** Three purpose-built chunkers (markdown heading-split, discussion formatter, tree-sitter AST) feed a provider-agnostic Embedder, which batches texts to Voyage/OpenAI. Chunks are stored as Qdrant points and mirrored as `chunks` rows in Postgres for retrieval hydration. A new `index_repo` Celery task orchestrates the pipeline and is chained automatically after `backfill_repo` completes.

**Tech Stack:** tree-sitter 0.23 + language bindings (Python/JS/TS/Go), qdrant-client 1.9 (AsyncQdrantClient), voyageai 0.3, openai 1.x, SQLAlchemy 2.0 async, Celery.

---

## File Structure

```
backend/app/indexing/
├── __init__.py                      (empty package marker)
├── chunkers/
│   ├── __init__.py                  (ChunkData dataclass)
│   ├── markdown.py                  (heading-based splitter)
│   ├── discussion.py                (issue/PR → markdown text → chunks)
│   └── code.py                      (tree-sitter AST chunker)
├── embedder.py                      (Voyage / OpenAI, returns List[List[float]])
├── qdrant_store.py                  (AsyncQdrantClient wrapper: ensure_collections, upsert, delete)
└── pipeline.py                      (orchestrate: files + discussions → chunk → embed → store)

backend/app/workers/
└── indexing_tasks.py                (Celery index_repo task)

backend/app/workers/ingestion_tasks.py   (MODIFY: chain index_repo after backfill)

backend/tests/
├── test_chunkers.py                 (pure-unit, no DB needed)
├── test_embedder.py                 (mocked API)
└── test_indexing_pipeline.py        (mocked embedder + qdrant + real DB session)
```

---

### Task 1: Dependencies + Package Scaffold

**Files:**
- Modify: `backend/pyproject.toml`
- Create: `backend/app/indexing/__init__.py`
- Create: `backend/app/indexing/chunkers/__init__.py`

- [ ] **Step 1: Add new dependencies to pyproject.toml**

Open `backend/pyproject.toml`. In the `dependencies` list, add after the existing entries:

```toml
    # Chunking — AST-based code parsing
    "tree-sitter>=0.23.0",
    "tree-sitter-python>=0.23.0",
    "tree-sitter-javascript>=0.23.0",
    "tree-sitter-typescript>=0.23.0",
    "tree-sitter-go>=0.23.0",
    # Vector DB
    "qdrant-client>=1.9.0",
    # Embeddings
    "voyageai>=0.3.0",
    "openai>=1.30.0",
```

The full `dependencies` block in pyproject.toml should now be:
```toml
dependencies = [
    # Web framework
    "fastapi>=0.111.0",
    "uvicorn[standard]>=0.29.0",
    "python-multipart>=0.0.9",
    # Database — async ORM + driver + migrations
    "sqlalchemy[asyncio]>=2.0.30",
    "asyncpg>=0.29.0",
    "alembic>=1.13.1",
    # Config
    "pydantic-settings>=2.2.1",
    # Task queue
    "celery[redis]>=5.3.6",
    "redis>=5.0.4",
    # GitHub App auth
    "PyJWT>=2.8.0",
    "cryptography>=42.0.5",
    # HTTP client (used in ingestion + tests)
    "httpx>=0.27.0",
    # GitHub REST API wrapper (used in actions layer)
    "PyGithub>=2.3.0",
    # Chunking — AST-based code parsing
    "tree-sitter>=0.23.0",
    "tree-sitter-python>=0.23.0",
    "tree-sitter-javascript>=0.23.0",
    "tree-sitter-typescript>=0.23.0",
    "tree-sitter-go>=0.23.0",
    # Vector DB
    "qdrant-client>=1.9.0",
    # Embeddings
    "voyageai>=0.3.0",
    "openai>=1.30.0",
]
```

- [ ] **Step 2: Install new dependencies**

```bash
cd backend
pip install -e ".[dev]"
```

Expected: Successfully installed tree-sitter, qdrant-client, voyageai, openai (and their transitive deps). No errors.

- [ ] **Step 3: Create package __init__ files**

Create `backend/app/indexing/__init__.py`:
```python
```
(empty file — just a package marker)

Create `backend/app/indexing/chunkers/__init__.py`:
```python
"""
Shared data structure for all chunkers.

ChunkData is the return type of every chunker function.
The pipeline maps these to Postgres Chunk rows and Qdrant points.
"""
from dataclasses import dataclass, field


@dataclass
class ChunkData:
    text: str           # The text to embed
    chunk_index: int    # 0-based index within the source entity
    metadata: dict = field(default_factory=dict)  # source-specific fields
```

- [ ] **Step 4: Verify import works**

```bash
cd backend
python -c "from app.indexing.chunkers import ChunkData; print(ChunkData(text='hi', chunk_index=0))"
```

Expected: `ChunkData(text='hi', chunk_index=0, metadata={})`

- [ ] **Step 5: Commit**

```bash
git add backend/pyproject.toml backend/app/indexing/
git commit -m "feat: add indexing package scaffold and new dependencies"
```

---

### Task 2: Markdown Chunker

**Files:**
- Create: `backend/app/indexing/chunkers/markdown.py`
- Create: `backend/tests/test_chunkers.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_chunkers.py`:
```python
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
    chunks = chunk_markdown(text)
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
    # Each heading section is short — they should all end up merged
    text = "# A\n\nHi.\n\n# B\n\nBye."
    chunks = chunk_markdown(text, min_chars=50)
    # Both sections are < 50 chars each so they merge into one chunk
    assert len(chunks) == 1
    assert "Hi." in chunks[0].text
    assert "Bye." in chunks[0].text


def test_chunk_markdown_returns_chunk_data():
    chunks = chunk_markdown("# Hello\n\nWorld")
    assert all(isinstance(c, ChunkData) for c in chunks)
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_chunkers.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.indexing.chunkers.markdown'`

- [ ] **Step 3: Implement the markdown chunker**

Create `backend/app/indexing/chunkers/markdown.py`:
```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd backend
pytest tests/test_chunkers.py::test_chunk_markdown_single_section tests/test_chunkers.py::test_chunk_markdown_multiple_headings tests/test_chunkers.py::test_chunk_markdown_no_headings tests/test_chunkers.py::test_chunk_markdown_empty tests/test_chunkers.py::test_chunk_markdown_merges_short_sections tests/test_chunkers.py::test_chunk_markdown_returns_chunk_data -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/indexing/chunkers/markdown.py backend/tests/test_chunkers.py
git commit -m "feat: add markdown chunker with heading-based splitting"
```

---

### Task 3: Discussion Chunker

**Files:**
- Create: `backend/app/indexing/chunkers/discussion.py`
- Modify: `backend/tests/test_chunkers.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chunkers.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_chunkers.py::test_chunk_issue_basic tests/test_chunkers.py::test_chunk_issue_none_body tests/test_chunkers.py::test_chunk_pull_request_basic tests/test_chunkers.py::test_chunk_pull_request_chunk_indices_are_sequential -v
```

Expected: `ModuleNotFoundError: No module named 'app.indexing.chunkers.discussion'`

- [ ] **Step 3: Implement the discussion chunker**

Create `backend/app/indexing/chunkers/discussion.py`:
```python
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
```

- [ ] **Step 4: Run all chunker tests so far**

```bash
cd backend
pytest tests/test_chunkers.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/indexing/chunkers/discussion.py backend/tests/test_chunkers.py
git commit -m "feat: add discussion chunker for issues and PRs"
```

---

### Task 4: Code Chunker (tree-sitter)

**Files:**
- Create: `backend/app/indexing/chunkers/code.py`
- Modify: `backend/tests/test_chunkers.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_chunkers.py`:
```python
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
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_chunkers.py::test_chunk_code_python_extracts_functions_and_classes tests/test_chunkers.py::test_chunk_code_javascript_extracts_nodes -v
```

Expected: `ModuleNotFoundError: No module named 'app.indexing.chunkers.code'`

- [ ] **Step 3: Implement the code chunker**

Create `backend/app/indexing/chunkers/code.py`:
```python
"""
Code chunker — extracts top-level AST nodes using tree-sitter.

Strategy:
1. Parse source with the language-specific tree-sitter parser.
2. Walk the root's immediate children, collecting nodes whose type is in
   _TOP_LEVEL_TYPES for that language.
3. Each collected node becomes one ChunkData with the node's source text.
4. If the text exceeds MAX_CHUNK_CHARS, split it into MAX_CHUNK_CHARS windows.
5. If the language has no parser (unknown), fall back to line-window splitting.

Returned metadata per chunk:
  {language, file_path, symbol, start_line, end_line}
"""
import logging
from app.indexing.chunkers import ChunkData

logger = logging.getLogger(__name__)

# Maximum characters per chunk (roughly 1000 tokens @ 4 chars/token)
MAX_CHUNK_CHARS = 4000

# Lines per window when falling back to line-based splitting
LINE_WINDOW = 60

# Top-level node types to extract per language
_TOP_LEVEL_TYPES: dict[str, set[str]] = {
    "python": {
        "function_definition",
        "class_definition",
        "decorated_definition",
    },
    "javascript": {
        "function_declaration",
        "class_declaration",
        "export_statement",
        "lexical_declaration",  # const foo = () => ...
    },
    "typescript": {
        "function_declaration",
        "class_declaration",
        "export_statement",
        "lexical_declaration",
        "interface_declaration",
        "type_alias_declaration",
    },
    "go": {
        "function_declaration",
        "method_declaration",
        "type_declaration",
    },
}


def _get_parser(language: str):
    """Return a (Parser, source_bytes → tree) callable, or None if unsupported."""
    try:
        from tree_sitter import Language, Parser
        if language == "python":
            import tree_sitter_python as tsp
            lang = Language(tsp.language())
        elif language in ("javascript", "jsx"):
            import tree_sitter_javascript as tsj
            lang = Language(tsj.language())
        elif language in ("typescript", "tsx"):
            import tree_sitter_typescript as tst
            if language == "tsx":
                lang = Language(tst.language_tsx())
            else:
                lang = Language(tst.language_typescript())
        elif language == "go":
            import tree_sitter_go as tsg
            lang = Language(tsg.language())
        else:
            return None
        return Parser(lang)
    except Exception as exc:
        logger.warning("Failed to load tree-sitter parser for %s: %s", language, exc)
        return None


def _split_long_text(text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split text into windows of at most max_chars, breaking on newlines."""
    if len(text) <= max_chars:
        return [text]
    parts = []
    while text:
        if len(text) <= max_chars:
            parts.append(text)
            break
        split_at = text.rfind("\n", 0, max_chars)
        if split_at == -1:
            split_at = max_chars
        parts.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return parts


def _line_window_chunks(source: str, language: str, file_path: str) -> list[ChunkData]:
    """Fallback: split source into LINE_WINDOW-line windows."""
    lines = source.splitlines()
    chunks = []
    idx = 0
    for start in range(0, len(lines), LINE_WINDOW):
        window = "\n".join(lines[start : start + LINE_WINDOW])
        if not window.strip():
            continue
        chunks.append(
            ChunkData(
                text=window,
                chunk_index=idx,
                metadata={
                    "language": language,
                    "file_path": file_path,
                    "symbol": "",
                    "start_line": start + 1,
                    "end_line": min(start + LINE_WINDOW, len(lines)),
                },
            )
        )
        idx += 1
    return chunks


def chunk_code(source: str, language: str, file_path: str) -> list[ChunkData]:
    """
    Chunk source code into ChunkData objects using tree-sitter AST parsing.

    Args:
        source:    Raw source code as a string.
        language:  Language name matching the keys in _TOP_LEVEL_TYPES
                   (python, javascript, typescript, go, tsx, jsx).
        file_path: Repo-relative file path — stored in metadata for context.

    Returns:
        List of ChunkData ordered by line position. Empty list for empty source.
    """
    if not source or not source.strip():
        return []

    parser = _get_parser(language)
    if parser is None:
        return _line_window_chunks(source, language, file_path)

    source_bytes = source.encode("utf-8")
    tree = parser.parse(source_bytes)
    root = tree.root_node

    target_types = _TOP_LEVEL_TYPES.get(language, set())
    extracted_nodes = []

    for node in root.children:
        if node.type in target_types:
            extracted_nodes.append(node)

    if not extracted_nodes:
        # No top-level nodes found — fall back to line windows
        return _line_window_chunks(source, language, file_path)

    chunks: list[ChunkData] = []
    idx = 0
    for node in extracted_nodes:
        node_text = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
        # Extract symbol name from the node (first named child that is an identifier)
        symbol = ""
        for child in node.children:
            if child.type in ("identifier", "name"):
                symbol = child.text.decode("utf-8", errors="replace") if child.text else ""
                break

        start_line = node.start_point[0] + 1  # tree-sitter is 0-indexed
        end_line = node.end_point[0] + 1

        for part in _split_long_text(node_text):
            chunks.append(
                ChunkData(
                    text=part,
                    chunk_index=idx,
                    metadata={
                        "language": language,
                        "file_path": file_path,
                        "symbol": symbol,
                        "start_line": start_line,
                        "end_line": end_line,
                    },
                )
            )
            idx += 1

    return chunks
```

- [ ] **Step 4: Run all chunker tests**

```bash
cd backend
pytest tests/test_chunkers.py -v
```

Expected: 16 passed. If any tree-sitter tests fail due to API changes, the error message will say which import failed — re-check `tree_sitter_python.language()` vs `tree_sitter_python.language` (no parens) for the installed version and adjust `_get_parser` accordingly.

- [ ] **Step 5: Commit**

```bash
git add backend/app/indexing/chunkers/code.py backend/tests/test_chunkers.py
git commit -m "feat: add tree-sitter code chunker for Python, JS, TS, Go"
```

---

### Task 5: Embedder

**Files:**
- Create: `backend/app/indexing/embedder.py`
- Create: `backend/tests/test_embedder.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_embedder.py`:
```python
"""
Embedder unit tests — all API calls are mocked.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.indexing.embedder import Embedder, EmbeddingProvider


@pytest.mark.asyncio
async def test_embedder_voyage_calls_api():
    fake_result = MagicMock()
    fake_result.embeddings = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]

    with patch("app.indexing.embedder.voyageai.AsyncClient") as MockClient:
        instance = MockClient.return_value
        instance.embed = AsyncMock(return_value=fake_result)

        embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="test-key")
        result = await embedder.embed_batch(["hello", "world"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    instance.embed.assert_called_once()


@pytest.mark.asyncio
async def test_embedder_openai_calls_api():
    fake_item_1 = MagicMock()
    fake_item_1.embedding = [0.7, 0.8, 0.9]
    fake_item_2 = MagicMock()
    fake_item_2.embedding = [0.1, 0.2, 0.3]

    fake_response = MagicMock()
    fake_response.data = [fake_item_1, fake_item_2]

    with patch("app.indexing.embedder.AsyncOpenAI") as MockOpenAI:
        instance = MockOpenAI.return_value
        instance.embeddings = MagicMock()
        instance.embeddings.create = AsyncMock(return_value=fake_response)

        embedder = Embedder(provider=EmbeddingProvider.OPENAI, api_key="test-key")
        result = await embedder.embed_batch(["hello", "world"])

    assert result == [[0.7, 0.8, 0.9], [0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_embedder_batches_large_input():
    """embed_batch should split texts into batches of BATCH_SIZE."""
    fake_result = MagicMock()
    # Return one embedding per text
    fake_result.embeddings = [[float(i)] for i in range(10)]

    with patch("app.indexing.embedder.voyageai.AsyncClient") as MockClient:
        instance = MockClient.return_value
        # Each call returns 10 embeddings
        instance.embed = AsyncMock(return_value=fake_result)

        embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="test-key")
        # Send 25 texts with batch_size=10 → should make 3 API calls
        texts = [f"text {i}" for i in range(25)]
        await embedder.embed_batch(texts, batch_size=10)

    assert instance.embed.call_count == 3


@pytest.mark.asyncio
async def test_embedder_empty_input_returns_empty():
    embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="key")
    result = await embedder.embed_batch([])
    assert result == []


def test_embedder_dimension_voyage():
    embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="key")
    assert embedder.dimension == 1024


def test_embedder_dimension_openai():
    embedder = Embedder(provider=EmbeddingProvider.OPENAI, api_key="key")
    assert embedder.dimension == 1536
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_embedder.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.indexing.embedder'`

- [ ] **Step 3: Implement the embedder**

Create `backend/app/indexing/embedder.py`:
```python
"""
Provider-agnostic text embedder.

Supported providers:
- VOYAGE: voyage-code-3 (1024-dim), best for code
- OPENAI: text-embedding-3-large (1536-dim), general purpose

Provider is selected at construction time. Call embed_batch() to get vectors.
Large inputs are automatically split into batches to stay within API limits.
"""
import logging
from enum import Enum

import voyageai
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

# Default batch size for API calls (stay well under rate limits)
_DEFAULT_BATCH_SIZE = 100


class EmbeddingProvider(str, Enum):
    VOYAGE = "voyage"
    OPENAI = "openai"


# Model names and output dimensions per provider
_PROVIDER_CONFIG = {
    EmbeddingProvider.VOYAGE: {
        "model": "voyage-code-3",
        "dimension": 1024,
    },
    EmbeddingProvider.OPENAI: {
        "model": "text-embedding-3-large",
        "dimension": 1536,
    },
}


class Embedder:
    """
    Async embedder that calls the configured provider API.

    Usage:
        embedder = Embedder(provider=EmbeddingProvider.VOYAGE, api_key="...")
        vectors = await embedder.embed_batch(["text one", "text two"])
    """

    def __init__(self, provider: EmbeddingProvider, api_key: str) -> None:
        self._provider = provider
        self._config = _PROVIDER_CONFIG[provider]

        if provider == EmbeddingProvider.VOYAGE:
            self._voyage_client = voyageai.AsyncClient(api_key=api_key)
        elif provider == EmbeddingProvider.OPENAI:
            self._openai_client = AsyncOpenAI(api_key=api_key)

    @property
    def dimension(self) -> int:
        """Output vector dimension for this provider."""
        return self._config["dimension"]

    @property
    def model(self) -> str:
        """Model name used for embedding (stored in Postgres chunks.embedding_model)."""
        return self._config["model"]

    async def embed_batch(
        self, texts: list[str], batch_size: int = _DEFAULT_BATCH_SIZE
    ) -> list[list[float]]:
        """
        Embed a list of texts, batching API calls to stay within provider limits.

        Args:
            texts:      List of strings to embed. Empty list returns [].
            batch_size: Max texts per API call.

        Returns:
            List of float vectors, same length and order as input texts.
        """
        if not texts:
            return []

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await self._embed_one_batch(batch)
            all_embeddings.extend(embeddings)
        return all_embeddings

    async def _embed_one_batch(self, texts: list[str]) -> list[list[float]]:
        if self._provider == EmbeddingProvider.VOYAGE:
            result = await self._voyage_client.embed(
                texts,
                model=self._config["model"],
                input_type="document",
            )
            return result.embeddings

        if self._provider == EmbeddingProvider.OPENAI:
            response = await self._openai_client.embeddings.create(
                input=texts,
                model=self._config["model"],
            )
            return [item.embedding for item in response.data]

        raise ValueError(f"Unknown provider: {self._provider}")


def embedder_from_settings() -> Embedder:
    """
    Construct an Embedder from app settings.

    Priority: voyage_api_key → openai_api_key → raises RuntimeError.
    Import this in Celery tasks to get the right embedder without
    passing settings around manually.
    """
    from app.core.config import settings

    if settings.voyage_api_key:
        return Embedder(provider=EmbeddingProvider.VOYAGE, api_key=settings.voyage_api_key)
    if settings.openai_api_key:
        return Embedder(provider=EmbeddingProvider.OPENAI, api_key=settings.openai_api_key)
    raise RuntimeError(
        "No embedding API key configured. Set VOYAGE_API_KEY or OPENAI_API_KEY in .env"
    )
```

- [ ] **Step 4: Run embedder tests**

```bash
cd backend
pytest tests/test_embedder.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/indexing/embedder.py backend/tests/test_embedder.py
git commit -m "feat: add provider-agnostic embedder (voyage / openai)"
```

---

### Task 6: Qdrant Store

**Files:**
- Create: `backend/app/indexing/qdrant_store.py`
- Create: `backend/tests/test_qdrant_store.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_qdrant_store.py`:
```python
"""
Qdrant store unit tests — AsyncQdrantClient is fully mocked.
"""
from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from app.indexing.qdrant_store import QdrantStore, CODE_COLLECTION, DISCUSSION_COLLECTION


@pytest.fixture
def mock_qdrant_client():
    with patch("app.indexing.qdrant_store.AsyncQdrantClient") as MockClient:
        instance = MockClient.return_value
        instance.collection_exists = AsyncMock(return_value=False)
        instance.create_collection = AsyncMock()
        instance.upsert = AsyncMock()
        instance.delete = AsyncMock()
        yield instance


@pytest.mark.asyncio
async def test_ensure_collections_creates_if_missing(mock_qdrant_client):
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    await store.ensure_collections()

    assert mock_qdrant_client.create_collection.call_count == 2
    call_names = [
        call.kwargs["collection_name"]
        for call in mock_qdrant_client.create_collection.call_args_list
    ]
    assert CODE_COLLECTION in call_names
    assert DISCUSSION_COLLECTION in call_names


@pytest.mark.asyncio
async def test_ensure_collections_skips_existing(mock_qdrant_client):
    mock_qdrant_client.collection_exists = AsyncMock(return_value=True)
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    await store.ensure_collections()
    mock_qdrant_client.create_collection.assert_not_called()


@pytest.mark.asyncio
async def test_upsert_chunks_calls_qdrant(mock_qdrant_client):
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    points = [
        {"id": "uuid-1", "vector": [0.1] * 1024, "payload": {"text": "hello"}},
        {"id": "uuid-2", "vector": [0.2] * 1024, "payload": {"text": "world"}},
    ]
    await store.upsert_points(CODE_COLLECTION, points)
    mock_qdrant_client.upsert.assert_called_once()


@pytest.mark.asyncio
async def test_delete_repo_points_calls_qdrant(mock_qdrant_client):
    store = QdrantStore(url="http://localhost:6333", vector_dim=1024)
    await store.delete_repo_points(repo_id=42)
    assert mock_qdrant_client.delete.call_count == 2  # once per collection
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_qdrant_store.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.indexing.qdrant_store'`

- [ ] **Step 3: Implement the Qdrant store**

Create `backend/app/indexing/qdrant_store.py`:
```python
"""
Async Qdrant client wrapper.

Two collections:
  code_chunks       — vectors from source code files
  discussion_chunks — vectors from issues and PRs

Each Qdrant point stores the full chunk text in its payload so retrieval
can hydrate results without a separate Postgres query.

Point IDs are deterministic UUIDs derived from (repo_id, source_type,
source_id, chunk_index) — this makes upserts idempotent across re-index runs.
"""
import logging
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PointStruct,
    VectorParams,
)

logger = logging.getLogger(__name__)

CODE_COLLECTION = "code_chunks"
DISCUSSION_COLLECTION = "discussion_chunks"

# Namespace for deterministic UUIDs (using the URL namespace)
_UUID_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def point_id(repo_id: int, source_type: str, source_id: int, chunk_index: int) -> str:
    """Generate a stable UUID string for a chunk — safe to use as Qdrant point ID."""
    key = f"{repo_id}:{source_type}:{source_id}:{chunk_index}"
    return str(uuid.uuid5(_UUID_NS, key))


class QdrantStore:
    """
    Wraps AsyncQdrantClient with collection management and batch upsert helpers.

    Usage:
        store = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension)
        await store.ensure_collections()
        await store.upsert_points(CODE_COLLECTION, points)
    """

    def __init__(self, url: str, vector_dim: int) -> None:
        self._client = AsyncQdrantClient(url=url)
        self._dim = vector_dim

    async def ensure_collections(self) -> None:
        """Create code_chunks and discussion_chunks if they don't already exist."""
        for name in (CODE_COLLECTION, DISCUSSION_COLLECTION):
            exists = await self._client.collection_exists(collection_name=name)
            if not exists:
                await self._client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
                )
                logger.info("Created Qdrant collection: %s (dim=%d)", name, self._dim)

    async def upsert_points(
        self,
        collection: str,
        points: list[dict],
    ) -> None:
        """
        Upsert a list of point dicts into the given collection.

        Each dict must have:
          id      — string UUID (use point_id() to generate)
          vector  — list[float]
          payload — dict with text + metadata
        """
        if not points:
            return
        structs = [
            PointStruct(id=p["id"], vector=p["vector"], payload=p["payload"])
            for p in points
        ]
        await self._client.upsert(collection_name=collection, points=structs)
        logger.debug("Upserted %d points into %s", len(structs), collection)

    async def delete_repo_points(self, repo_id: int) -> None:
        """Delete all points belonging to a repo from both collections."""
        condition = Filter(
            must=[FieldCondition(key="repo_id", match=MatchValue(value=repo_id))]
        )
        for collection in (CODE_COLLECTION, DISCUSSION_COLLECTION):
            await self._client.delete(
                collection_name=collection,
                points_selector=FilterSelector(filter=condition),
            )
        logger.info("Deleted all Qdrant points for repo_id=%d", repo_id)
```

- [ ] **Step 4: Run Qdrant store tests**

```bash
cd backend
pytest tests/test_qdrant_store.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/indexing/qdrant_store.py backend/tests/test_qdrant_store.py
git commit -m "feat: add Qdrant store wrapper with idempotent collection management"
```

---

### Task 7: Indexing Pipeline

**Files:**
- Create: `backend/app/indexing/pipeline.py`
- Create: `backend/tests/test_indexing_pipeline.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_indexing_pipeline.py`:
```python
"""
Indexing pipeline integration tests.

Uses real Postgres (same NullPool pattern as test_fetchers.py).
Embedder and QdrantStore are mocked — we're testing the chunking + DB logic,
not the external APIs.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.indexing.qdrant_store import CODE_COLLECTION, DISCUSSION_COLLECTION
from app.models.orm import Chunk, File, Issue, PullRequest, Repo

_test_engine = create_async_engine(settings.database_url, poolclass=NullPool)
_TestSessionLocal = async_sessionmaker(_test_engine, expire_on_commit=False)


@pytest_asyncio.fixture
async def db_session():
    async with _TestSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def test_repo(db_session: AsyncSession):
    from sqlalchemy.dialects.postgresql import insert

    stmt = (
        insert(Repo)
        .values(github_id=888888, owner="pipelineowner", name="pipelinerepo", installation_id=222)
        .on_conflict_do_nothing(constraint="uq_repos_github_id")
        .returning(Repo.id)
    )
    result = await db_session.execute(stmt)
    repo_id = result.scalar_one()
    repo = await db_session.get(Repo, repo_id)
    yield repo
    await db_session.execute(delete(Chunk).where(Chunk.repo_id == repo.id))
    await db_session.execute(delete(File).where(File.repo_id == repo.id))
    await db_session.execute(delete(Issue).where(Issue.repo_id == repo.id))
    await db_session.execute(delete(PullRequest).where(PullRequest.repo_id == repo.id))
    await db_session.execute(delete(Repo).where(Repo.id == repo.id))
    await db_session.commit()


@pytest.fixture
def mock_embedder():
    embedder = MagicMock()
    embedder.model = "voyage-code-3"
    embedder.dimension = 1024
    # Always return a 1024-dim vector for each input text
    async def embed_batch(texts, batch_size=100):
        return [[0.1] * 1024 for _ in texts]
    embedder.embed_batch = embed_batch
    return embedder


@pytest.fixture
def mock_qdrant():
    store = MagicMock()
    store.upsert_points = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_index_issues_creates_chunks(db_session, test_repo, mock_embedder, mock_qdrant):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from datetime import datetime, timezone

    # Insert a test issue
    stmt = pg_insert(Issue).values(
        repo_id=test_repo.id,
        github_number=1,
        title="Fix memory leak",
        body="The server leaks on startup.\n\n## Steps\n\nRun it.",
        state="open",
        author="alice",
        labels=["bug"],
        created_at=datetime.now(tz=timezone.utc),
    ).on_conflict_do_nothing(constraint="uq_issues_repo_number")
    await db_session.execute(stmt)
    await db_session.commit()

    from app.indexing.pipeline import index_repo_discussions
    await index_repo_discussions(db_session, test_repo, mock_embedder, mock_qdrant)

    # Chunks should be stored in Postgres
    result = await db_session.execute(
        select(Chunk).where(Chunk.repo_id == test_repo.id, Chunk.source_type == "issue")
    )
    chunks = result.scalars().all()
    assert len(chunks) >= 1
    assert chunks[0].embedding_model == "voyage-code-3"
    assert chunks[0].qdrant_collection == DISCUSSION_COLLECTION
    assert chunks[0].qdrant_point_id is not None

    # Qdrant upsert should have been called
    mock_qdrant.upsert_points.assert_called()


@pytest.mark.asyncio
async def test_index_files_creates_chunks(db_session, test_repo, mock_embedder, mock_qdrant):
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    # Insert a test file stub
    stmt = pg_insert(File).values(
        repo_id=test_repo.id,
        path="src/app.py",
        language="python",
        content_hash=None,
        last_indexed_at=None,
    ).on_conflict_do_nothing(constraint="uq_files_repo_path")
    await db_session.execute(stmt)
    await db_session.commit()

    python_source = "def hello():\n    return 'world'\n"

    # Mock the GitHub client that downloads file content
    mock_github_client = MagicMock()
    mock_github_client.get = AsyncMock(return_value={
        "content": __import__("base64").b64encode(python_source.encode()).decode(),
        "encoding": "base64",
        "size": len(python_source),
    })

    from app.indexing.pipeline import index_repo_files
    await index_repo_files(
        db_session, test_repo, mock_github_client, mock_embedder, mock_qdrant,
        default_branch="main",
    )

    result = await db_session.execute(
        select(Chunk).where(Chunk.repo_id == test_repo.id, Chunk.source_type == "file")
    )
    chunks = result.scalars().all()
    assert len(chunks) >= 1
    assert chunks[0].qdrant_collection == CODE_COLLECTION

    mock_qdrant.upsert_points.assert_called()


@pytest.mark.asyncio
async def test_index_discussions_skips_empty_body(db_session, test_repo, mock_embedder, mock_qdrant):
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    from datetime import datetime, timezone

    stmt = pg_insert(Issue).values(
        repo_id=test_repo.id,
        github_number=2,
        title="No body issue",
        body=None,
        state="open",
        author="bob",
        labels=[],
        created_at=datetime.now(tz=timezone.utc),
    ).on_conflict_do_nothing(constraint="uq_issues_repo_number")
    await db_session.execute(stmt)
    await db_session.commit()

    from app.indexing.pipeline import index_repo_discussions
    await index_repo_discussions(db_session, test_repo, mock_embedder, mock_qdrant)

    result = await db_session.execute(
        select(Chunk).where(Chunk.repo_id == test_repo.id, Chunk.source_type == "issue")
    )
    chunks = result.scalars().all()
    # Even with no body, one chunk should exist (title is always chunked)
    assert len(chunks) >= 1
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd backend
pytest tests/test_indexing_pipeline.py -v
```

Expected: `ModuleNotFoundError: No module named 'app.indexing.pipeline'`

- [ ] **Step 3: Implement the pipeline**

Create `backend/app/indexing/pipeline.py`:
```python
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

# Skip files larger than this (GitHub API returns base64 content in memory)
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
    """Store chunks in Postgres and Qdrant. Called by both file and discussion indexers."""
    if not chunks:
        return

    qdrant_points = []
    for chunk, vector in zip(chunks, vectors):
        pid = point_id(repo_id, source_type, source_id, chunk.chunk_index)

        # Postgres upsert
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
                    "chunk_metadata": chunk.metadata,
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

            # Update file metadata
            file.content_hash = content_hash
            file.last_indexed_at = datetime.now(tz=timezone.utc)
            await session.commit()

            indexed += 1

        except Exception:
            logger.exception("Failed to index file %s for repo %s/%s", file.path, repo.owner, repo.name)
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
```

- [ ] **Step 4: Run pipeline tests**

```bash
cd backend
pytest tests/test_indexing_pipeline.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Run all tests to confirm no regressions**

```bash
cd backend
pytest tests/ -v
```

Expected: all tests pass (previously 24 + 6 new chunker + 4 embedder + 4 qdrant store + 3 pipeline = 41 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/indexing/pipeline.py backend/tests/test_indexing_pipeline.py
git commit -m "feat: add indexing pipeline for files and discussions"
```

---

### Task 8: Celery `index_repo` Task + Wire After Backfill

**Files:**
- Create: `backend/app/workers/indexing_tasks.py`
- Modify: `backend/app/workers/celery_app.py`
- Modify: `backend/app/workers/ingestion_tasks.py`
- Modify: `backend/tests/test_ingestion_tasks.py`

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_ingestion_tasks.py`, the existing test mocks all fetchers. Add one new test at the end of the file:

```python
# Add this import at the top of the existing file:
# from unittest.mock import patch, AsyncMock, MagicMock

def test_backfill_repo_enqueues_index_task(monkeypatch):
    """After a successful backfill, index_repo.delay() should be called."""
    import asyncio
    from app.workers.ingestion_tasks import backfill_repo

    async def fake_async_backfill(repo_id):
        return {"repo_id": repo_id, "issues": 0, "prs": 0, "commits": 0, "files": 0}

    mock_delay = MagicMock()

    monkeypatch.setattr("app.workers.ingestion_tasks._async_backfill_repo", fake_async_backfill)
    monkeypatch.setattr("app.workers.ingestion_tasks.index_repo.delay", mock_delay)

    backfill_repo(99)

    mock_delay.assert_called_once_with(99)
```

- [ ] **Step 2: Run the test to confirm it fails**

```bash
cd backend
pytest tests/test_ingestion_tasks.py::test_backfill_repo_enqueues_index_task -v
```

Expected: `ImportError` or `AttributeError` — `index_repo` does not exist yet.

- [ ] **Step 3: Create the indexing_tasks.py Celery task**

Create `backend/app/workers/indexing_tasks.py`:
```python
"""
Celery task for indexing a repo's chunks into Qdrant.

Called automatically after backfill_repo completes.
Can also be triggered manually for re-indexing.
"""
import asyncio
import logging

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.config import settings
from app.core.github_auth import get_installation_token
from app.indexing.embedder import embedder_from_settings
from app.indexing.pipeline import index_repo_discussions, index_repo_files
from app.indexing.qdrant_store import QdrantStore
from app.ingestion.github_client import GitHubClient
from app.models.orm import Repo
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


async def _async_index_repo(repo_id: int) -> dict:
    embedder = embedder_from_settings()
    qdrant = QdrantStore(url=settings.qdrant_url, vector_dim=embedder.dimension)
    await qdrant.ensure_collections()

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Repo).where(Repo.id == repo_id))
        repo = result.scalar_one_or_none()
        if not repo:
            logger.error("Repo id=%d not found — skipping indexing", repo_id)
            return {"error": "repo_not_found"}

        logger.info("Starting indexing for %s/%s (id=%d)", repo.owner, repo.name, repo_id)

        token = await get_installation_token(repo.installation_id)
        async with GitHubClient(token=token) as client:
            # Get default branch from GitHub
            repo_data = await client.get(f"/repos/{repo.owner}/{repo.name}")
            default_branch = repo_data.get("default_branch", "main")

            files_count = await index_repo_files(
                session, repo, client, embedder, qdrant, default_branch=default_branch
            )

        discussion_counts = await index_repo_discussions(session, repo, embedder, qdrant)

        summary = {
            "repo_id": repo_id,
            "files_indexed": files_count,
            **discussion_counts,
        }
        logger.info("Indexing complete for %s/%s: %s", repo.owner, repo.name, summary)
        return summary


@celery_app.task(name="indexing.index_repo", bind=True, max_retries=3)
def index_repo(self, repo_id: int) -> dict:
    """
    Celery task: chunk, embed, and store all content for a repo.

    Retries up to 3 times on transient errors (API rate limits, network).
    """
    try:
        return asyncio.run(_async_index_repo(repo_id))
    except Exception as exc:
        logger.exception("Indexing failed for repo_id=%d: %s", repo_id, exc)
        raise self.retry(exc=exc, countdown=60)
```

- [ ] **Step 4: Register indexing_tasks in celery_app.py**

Open `backend/app/workers/celery_app.py`. Change `include` to:

```python
include=["app.workers.ingestion_tasks", "app.workers.indexing_tasks"],
```

- [ ] **Step 5: Wire index_repo.delay() after backfill succeeds**

Open `backend/app/workers/ingestion_tasks.py`. Add this import near the top (after existing imports):

```python
from app.workers.indexing_tasks import index_repo
```

Then modify `backfill_repo` to enqueue indexing after success:

```python
@celery_app.task(name="ingestion.backfill_repo", bind=True, max_retries=3)
def backfill_repo(self, repo_id: int) -> dict:
    """
    Celery task: fetch and store all GitHub data for a repo.

    Retries up to 3 times on transient errors (rate limits, network blips).
    On success, enqueues index_repo to chunk and embed the stored data.
    bind=True gives access to self.retry().
    """
    try:
        result = asyncio.run(_async_backfill_repo(repo_id))
        index_repo.delay(repo_id)
        return result
    except Exception as exc:
        logger.exception("Backfill failed for repo_id=%d: %s", repo_id, exc)
        raise self.retry(exc=exc, countdown=60)
```

- [ ] **Step 6: Run the new test**

```bash
cd backend
pytest tests/test_ingestion_tasks.py -v
```

Expected: all tests in that file pass.

- [ ] **Step 7: Run the full test suite**

```bash
cd backend
pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/workers/indexing_tasks.py backend/app/workers/celery_app.py backend/app/workers/ingestion_tasks.py backend/tests/test_ingestion_tasks.py
git commit -m "feat: add index_repo Celery task, wire after backfill completes"
```

---

## Self-Review

### Spec coverage

Day 3 requirements from the 10-day plan:
- ✅ Tree-sitter code chunker (Python/JS/TS/Go) — Task 4
- ✅ Markdown chunker — Task 2
- ✅ Discussion chunker — Task 3
- ✅ Unit tests — Tasks 2–6 all have tests; pipeline has integration tests
- ✅ Embeddings in Qdrant — Tasks 5, 6, 7, 8

### Placeholder scan

No TBD, TODO, or "handle edge cases" placeholders. All code is complete.

### Type consistency

- `ChunkData` defined in `chunkers/__init__.py`, used by all three chunkers and pipeline ✅
- `Embedder.embed_batch(texts: list[str]) -> list[list[float]]` used consistently in pipeline ✅
- `QdrantStore.upsert_points(collection: str, points: list[dict])` matches pipeline call sites ✅
- `index_repo_files` and `index_repo_discussions` signatures match `_async_index_repo` call sites ✅
