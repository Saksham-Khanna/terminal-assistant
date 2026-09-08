"""
Shared setup for the vector store and embedding model, used by both
indexer.py (writes) and search.py (reads).

Uses a local sentence-transformers model so indexing/searching is free and
works offline — no embedding API calls needed. Swap EMBED_MODEL_NAME for a
hosted embedding API later if you want higher-quality retrieval.
"""

import chromadb
from sentence_transformers import SentenceTransformer

DB_PATH = "./rag_db"
COLLECTION_NAME = "codebase"
EMBED_MODEL_NAME = "all-MiniLM-L6-v2"  # small, fast, good enough to learn on

_embedder = None
_client = None


def get_embedder() -> SentenceTransformer:
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL_NAME)
    return _embedder


def get_collection():
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=DB_PATH)
    return _client.get_or_create_collection(COLLECTION_NAME)


def embed(texts: list[str]) -> list[list[float]]:
    return get_embedder().encode(texts, show_progress_bar=False).tolist()
