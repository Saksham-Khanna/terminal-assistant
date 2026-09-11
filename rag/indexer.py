"""
Walks the workspace, splits files into chunks, embeds each chunk, and stores
it in the vector database. Run this once (or after big changes) before using
search_codebase.

Chunking strategy here is intentionally simple: fixed-size line windows with
overlap. This is the naive baseline — a good next upgrade is AST-aware
chunking (splitting by function/class using tree-sitter) once this works.
"""

import os
import uuid

from rag.store import embed, get_collection

CHUNK_LINES = 60
CHUNK_OVERLAP = 10

CODE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".java", ".go", ".rs", ".md", ".txt"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "venv", ".venv", "rag_db", ".sessions", ".ruff_cache", ".pytest_cache", "dist", ".vscode", "chroma", "__pycache__"}


def _chunk_file_window(source: str) -> list[str]:
    """
    Pure line-window chunker over a source string. Used as the fallback for
    non-Python files and for files we can't parse into AST units.
    """
    lines = source.splitlines(keepends=True)

    chunks = []
    step = CHUNK_LINES - CHUNK_OVERLAP
    for start in range(0, len(lines), step):
        chunk = "".join(lines[start:start + CHUNK_LINES])
        if chunk.strip():
            chunks.append(chunk)
        if start + CHUNK_LINES >= len(lines):
            break
    return chunks


def _chunk_file(path: str) -> list[str]:
    # utf-8-sig automatically strips a leading UTF-8 BOM (EF BB BF), which
    # would otherwise either corrupt tree-sitter parsing or leak a garbage
    # char into every chunk on Windows' default cp1252 read.
    with open(path, errors="ignore", encoding="utf-8-sig") as f:
        source = f.read()

    # Languages with a tree-sitter binding get AST-aware chunking
    # (function/class/method boundaries). Everything else (and any parse
    # errors) falls back to line windows.
    from rag.ast_chunker import chunk_source, language_for_extension

    language = language_for_extension(path)
    if language:
        try:
            chunks = chunk_source(source, language)
            return [c for c in chunks if c.strip()]
        except Exception:
            pass  # fall through to line-window chunking

    return _chunk_file_window(source)


def index_directory(root: str) -> int:
    """Indexes every code/text file under `root`. Returns number of chunks stored."""
    collection = get_collection()

    ids, documents, metadatas = [], [], []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for filename in filenames:
            if os.path.splitext(filename)[1] not in CODE_EXTENSIONS:
                continue
            full_path = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(full_path, root)

            for chunk in _chunk_file(full_path):
                ids.append(str(uuid.uuid4()))
                documents.append(chunk)
                metadatas.append({"path": rel_path})

    if not documents:
        return 0

    embeddings = embed(documents)
    collection.add(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas,
    )
    return len(documents)


def reset_index():
    """Wipes the collection so you can re-index from scratch."""
    import shutil

    from rag.store import DB_PATH
    shutil.rmtree(DB_PATH, ignore_errors=True)
