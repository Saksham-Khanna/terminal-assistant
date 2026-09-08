"""
AST-aware chunking using tree-sitter.

Instead of the naive fixed-size line window (CHUNK_LINES overlapping chunks),
we split Python source along function/class/method boundaries so each chunk is
a cohesive unit of code. This produces far better retrieval results because
a single semantic unit (a function) isn't split in half or merged with
unrelated code.

We split each top-level function/class/method into its own chunk. If a single
function/class is larger than MAX_NAVYSIZE_LINES, we fall back to line-window
sub-chunks inside it so we never store an oversized document.

Any syntax errors or files we can't parse fall back to the safe line-window
chunker in indexer.py.
"""

from tree_sitter import Language, Parser
from tree_sitter_python import language as python_language

# Node types we treat as a "cohesive unit" worth indexing on its own.
UNIT_NODE_TYPES = {
    "function_definition",
    "class_definition",
    # methods are just function_definition nodes nested inside a class body
}

MAX_UNIT_LINES = 120  # if a unit is bigger than this, sub-chunk it by lines


def _get_parser() -> Parser:
    parser = Parser()
    parser.language = Language(python_language())
    return parser


def _node_range_bytes(source: bytes, node) -> tuple[int, int]:
    """Return (start_byte, end_byte) for a tree-sitter node."""
    return node.start_byte, node.end_byte


def _extract_units(root) -> list:
    """
    Walk the tree and collect:
      - top-level function_definition nodes
      - top-level class_definition nodes (whole class as one chunk)
    Each becomes one cohesive chunk. Methods are kept inside their class chunk,
    which is fine for retrieval because a class is small enough to index whole.
    """
    units = []

    for child in root.children:
        if child.type in UNIT_NODE_TYPES:
            units.append(child)

    return units


def chunk_python(source: str) -> list[str]:
    """
    Split Python source into AST-aware chunks (strings). Falls back to raw
    line windows when the source can't be parsed or has no units.
    """
    # Strip a UTF-8 BOM if present — tree-sitter treats it as an error node,
    # which would bubble the whole file up to the line-window fallback.
    if source.startswith("\ufeff"):
        source = source[1:]

    parser = _get_parser()
    src_bytes = source.encode("utf-8")
    tree = parser.parse(src_bytes)
    root = tree.root_node

    if root.has_error:
        return _line_fallback(source)

    units = _extract_units(root)
    if not units:
        return _line_fallback(source)

    chunks = []
    lines = source.splitlines(keepends=True)

    def bytes_to_chars(b_start, b_end):
        return src_bytes[b_start:b_end].decode("utf-8", errors="replace")

    for unit in units:
        b_start, b_end = _node_range_bytes(src_bytes, unit)
        unit_text = bytes_to_chars(b_start, b_end)
        n_lines = unit_text.count("\n") + 1

        if n_lines <= MAX_UNIT_LINES:
            chunks.append(unit_text)
        else:
            # Huge unit: sub-chunk on line windows to keep documents bounded.
            chunks.extend(_line_chunks_from_lines(unit_text))

    return chunks


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
