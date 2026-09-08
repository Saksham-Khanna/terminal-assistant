"""
AST-aware chunking using tree-sitter, for multiple languages.

Instead of the naive fixed-size line window (CHUNK_LINES overlapping chunks),
we split source along function/class/method boundaries so each chunk is a
cohesive unit of code. This produces far better retrieval results because a
single semantic unit (a function) isn't split in half or merged with unrelated
code.

Supported languages and their unit node types:

  * Python     -> function_definition, class_definition
  * JavaScript -> function_declaration, class_declaration, method_definition
  * Java       -> class_declaration, interface_declaration, method_declaration
  * Go         -> function_declaration, type_declaration
  * Rust       -> function_item, struct_item, enum_item, impl_item

Each top-level unit becomes its own chunk. If a single unit is larger than
MAX_UNIT_LINES, we fall back to line-window sub-chunks inside it so we never
store an oversized document.

Any syntax errors or files we can't parse fall back to the safe line-window
chunker in indexer.py.
"""

from tree_sitter import Language, Parser

# Language -> tree-sitter binding module name -> unit node types.
# Unit node types are the tree-sitter nodes we treat as a cohesive unit.
_LANGUAGES = {
    "python": "tree_sitter_python",
    "javascript": "tree_sitter_javascript",
    "java": "tree_sitter_java",
    "go": "tree_sitter_go",
    "rust": "tree_sitter_rust",
}

UNIT_NODE_TYPES = {
    "python": {"function_definition", "class_definition"},
    "javascript": {"function_declaration", "class_declaration", "method_definition"},
    "java": {"class_declaration", "interface_declaration", "method_declaration"},
    "go": {"function_declaration", "type_declaration"},
    "rust": {"function_item", "struct_item", "enum_item", "impl_item"},
}

# Extension -> language name mapping (used by indexer).
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "javascript",
    ".tsx": "javascript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
}

MAX_UNIT_LINES = 120  # if a unit is bigger than this, sub-chunk it by lines

_parser_cache: dict[str, Parser] = {}


def language_for_extension(path: str) -> str | None:
    """Return the chunking language name for a file path, or None."""
    import os

    ext = os.path.splitext(path)[1].lower()
    return EXTENSION_TO_LANGUAGE.get(ext)


def _get_parser(language: str) -> Parser | None:
    """Get (and cache) a parser for the given language, or None if unavailable."""
    if language in _parser_cache:
        return _parser_cache[language]
    mod_name = _LANGUAGES.get(language)
    if not mod_name:
        return None
    try:
        lang_mod = __import__(mod_name, fromlist=["language"])
        parser = Parser()
        parser.language = Language(lang_mod.language())
    except Exception:
        # Language binding missing or errored — let indexer fall back.
        return None
    _parser_cache[language] = parser
    return parser


def _node_range_bytes(node) -> tuple[int, int]:
    """Return (start_byte, end_byte) for a tree-sitter node."""
    return node.start_byte, node.end_byte


def _extract_units(root, unit_types: set) -> list:
    """
    Collect top-level unit nodes (functions / classes / structs / enums) that
    are direct children of the file's module/program root. Methods inside a
    class are kept within their class chunk, which is fine for retrieval
    because a typical class is small enough to index whole.
    """
    units = []
    for child in root.children:
        if child.type in unit_types:
            units.append(child)
    return units


def chunk_source(source: str, language: str) -> list[str]:
    """
    Split source into AST-aware chunks (strings). Falls back to line windows
    when the language isn't supported, the source can't be parsed, or it has
    no parseable top-level units.
    """
    parser = _get_parser(language)
    if parser is None:
        return _line_fallback(source)

    # Strip a UTF-8 BOM if present — tree-sitter treats it as an error node,
    # which would bubble the whole file up to the line-window fallback.
    if source.startswith("\ufeff"):
        source = source[1:]

    src_bytes = source.encode("utf-8")
    tree = parser.parse(src_bytes)
    root = tree.root_node

    if root.has_error:
        return _line_fallback(source)

    unit_types = UNIT_NODE_TYPES.get(language, set())
    units = _extract_units(root, unit_types)
    if not units:
        return _line_fallback(source)

    def bytes_to_chars(b_start, b_end):
        return src_bytes[b_start:b_end].decode("utf-8", errors="replace")

    chunks = []
    for unit in units:
        b_start, b_end = _node_range_bytes(unit)
        unit_text = bytes_to_chars(b_start, b_end)
        n_lines = unit_text.count("\n") + 1

        if n_lines <= MAX_UNIT_LINES:
            chunks.append(unit_text)
        else:
            # Huge unit: sub-chunk on line windows to keep documents bounded.
            chunks.extend(_line_chunks_from_lines(unit_text))

    return [c for c in chunks if c.strip()]


def chunk_python(source: str) -> list[str]:
    """Backward-compatible wrapper for the Python chunker."""
    return chunk_source(source, "python")


def _line_chunks_from_lines(text: str) -> list[str]:
    """Line-window sub-chunking (same heuristic as indexer's fallback)."""
    from rag.indexer import CHUNK_LINES, CHUNK_OVERLAP

    lines = text.splitlines(keepends=True)
    out = []
    step = CHUNK_LINES - CHUNK_OVERLAP
    for start in range(0, len(lines), step):
        chunk = "".join(lines[start:start + CHUNK_LINES])
        if chunk.strip():
            out.append(chunk)
        if start + CHUNK_LINES >= len(lines):
            break
    return out


def _line_fallback(source: str) -> list[str]:
    from rag.indexer import _chunk_file_window

    return _chunk_file_window(source)
