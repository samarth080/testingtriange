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
        "lexical_declaration",
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
    """Return a Parser instance for the given language, or None if unsupported."""
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
        language:  Language name (python, javascript, typescript, go, tsx, jsx).
        file_path: Repo-relative file path stored in metadata.

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

    # Normalize jsx→javascript, tsx→typescript for _TOP_LEVEL_TYPES lookup
    _lang_key = {"jsx": "javascript", "tsx": "typescript"}.get(language, language)
    target_types = _TOP_LEVEL_TYPES.get(_lang_key, set())
    extracted_nodes = []

    for node in root.children:
        if node.type in target_types:
            extracted_nodes.append(node)

    if not extracted_nodes:
        return _line_window_chunks(source, language, file_path)

    chunks: list[ChunkData] = []
    idx = 0
    for node in extracted_nodes:
        node_text = source_bytes[node.start_byte : node.end_byte].decode("utf-8", errors="replace")
        # Extract symbol name: first named child that is an identifier
        # For decorated definitions, unwrap to find the actual function/class node
        target_node = node
        if node.type == "decorated_definition":
            for child in node.children:
                if child.type in ("function_definition", "class_definition", "async_function_definition"):
                    target_node = child
                    break

        symbol = ""
        for child in target_node.children:
            if child.type in ("identifier", "name"):
                symbol = source_bytes[child.start_byte : child.end_byte].decode("utf-8", errors="replace")
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
