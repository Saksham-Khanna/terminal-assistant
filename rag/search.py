"""
Hybrid search: keyword (BM25) + semantic (vector) fused with RRF.

BM25 covers exact keyword matches (function names, variable names, error
strings) while the vector store covers semantic similarity. Both ranked lists
are merged with Reciprocal Rank Fusion so the agent gets robust retrieval.
"""


def search(query: str, top_k: int = 5) -> list[dict]:
    from rag.bm25 import bm25_index_for, rrf_merge, top_k_bm25
    from rag.store import embed, get_collection

    collection = get_collection()
    if collection.count() == 0:
        return []

    # --- Semantic (vector) ranking ---
    query_embedding = embed([query])[0]
    vec_results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
    )

    vec_ranked: list[dict] = []
    docs = vec_results["documents"][0]
    metas = vec_results["metadatas"][0]
    distances = vec_results["distances"][0]
    ids = vec_results["ids"][0]

    for doc_id, doc, meta, dist in zip(ids, docs, metas, distances):
        score = 1 / (1 + dist)
        text = doc if isinstance(doc, str) else " ".join(doc)
        meta = meta or {}
        vec_ranked.append({
            "id": doc_id,
            "path": meta.get("path", ""),
            "text": text,
            "score": score,
        })

    # --- Keyword (BM25) ranking ---
    bm25, docs_by_id = bm25_index_for(collection)
    kw = top_k_bm25(bm25, docs_by_id, query, top_k=top_k)

    # --- Fuse with RRF ---
    fused = rrf_merge(vec_ranked, kw)

    # Normalize the fused score to 0..1 relative to the best hit for display.
    if fused:
        max_score = fused[0]["score"]
        for item in fused:
            item["score"] = item["score"] / max_score if max_score > 0 else 0.0

    return fused


def search_keyword_only(query: str, top_k: int = 5) -> list[dict]:
    """Pure BM25 search (no vector call). Useful for debugging / tests."""
    from rag.bm25 import bm25_index_for, top_k_bm25
    from rag.store import get_collection

    collection = get_collection()
    if collection.count() == 0:
        return []
    bm25, docs_by_id = bm25_index_for(collection)
    return top_k_bm25(bm25, docs_by_id, query, top_k=top_k)
