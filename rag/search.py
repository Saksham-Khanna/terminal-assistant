"""
Semantic search over whatever indexer.py has stored. This is what the
agent's search_codebase tool calls under the hood.
"""

from rag.store import embed, get_collection


def search(query: str, top_k: int = 5) -> list[dict]:
    collection = get_collection()
    if collection.count() == 0:
        return []

    query_embedding = embed([query])[0]
    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
    )

    output = []
    docs = results["documents"][0]
    metas = results["metadatas"][0]
    distances = results["distances"][0]

    for doc, meta, dist in zip(docs, metas, distances):
        # Chroma returns a distance (lower = more similar); convert to a
        # 0-1 "similarity-ish" score just for readability in output.
        score = 1 / (1 + dist)
        output.append({"path": meta["path"], "text": doc, "score": score})

    return output
