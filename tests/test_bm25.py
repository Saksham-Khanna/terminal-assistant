"""Tests for BM25 keyword retrieval and RRF fusion."""

import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


from rag.bm25 import BM25, rrf_merge, tokenize, top_k_bm25


def test_tokenize_splits_identifiers_and_paths():
    tokens = tokenize("get_collection.py /src/MyFile.CPP get_collection")
    assert "get" in tokens
    assert "collection" in tokens
    assert "py" in tokens
    assert "src" in tokens
    assert "myfile" in tokens
    assert "cpp" in tokens


def test_tokenize_drops_stopwords_and_short():
    tokens = tokenize("the a and of is to remove_files")
    assert "remove" in tokens
    assert "files" in tokens
    assert not any(t in tokens for t in ("the", "a", "and", "of", "is", "to"))


def test_bm25_ranks_matching_doc_higher():
    docs = [
        "def calculate_total(items): return sum(x for x in items)",
        "class Customer: def __init__(self, name): pass",
        "def process_payment(order): return order.status",
    ]
    bm25 = BM25(docs)
    hits = bm25.top_k("calculate_total", k=3)
    assert hits[0][0] == 0  # doc 0 matches the term best


def test_bm25_empty_corpus():
    bm25 = BM25([])
    assert bm25.top_k("anything", k=5) == []


def test_bm25_scoring_total_dominated_by_query_terms():
    docs = [
        "alpha beta gamma delta — many words padding padding padding padding",
        "alpha alpha alpha alpha — query terms repeated here alpha alpha",
    ]
    bm25 = BM25(docs)
    hits = bm25.top_k("alpha alpha", k=2)
    # Doc 1 has alpha repeated far more, so it should rank first.
    assert hits[0][0] == 1


def test_rrf_merge_combines_rankings():
    list_a = [
        {"id": "1", "path": "a.py", "text": "x", "score": 0.9},
        {"id": "2", "path": "b.py", "text": "y", "score": 0.8},
        {"id": "3", "path": "c.py", "text": "z", "score": 0.7},
    ]
    list_b = [
        {"id": "3", "path": "c.py", "text": "z", "score": 0.5},
        {"id": "1", "path": "a.py", "text": "x", "score": 0.4},
        {"id": "9", "path": "new.py", "text": "n", "score": 0.3},
    ]
    fused = rrf_merge(list_a, list_b)

    ids = [item["id"] for item in fused]
    # Doc 1 ranks #1 in list_a and #2 in list_b; doc 3 ranks #1 in list_b
    # and #3 in list_a. Doc 1's combined score is slightly higher because
    # rank-1 in the larger contribution (both lists) outweighs rank-1 in
    # one list for doc 3.
    assert ids[0] == "1"
    assert "3" in ids
    assert "9" in ids  # present in only one list, still included
    assert all(item.get("rrf") is True for item in fused)


def test_top_k_bm25_returns_shaped_results():
    docs_by_id = {
        "id-1": {"id": "id-1", "path": "mod.py", "text": "def setup(): return 1"},
        "id-2": {"id": "id-2", "path": "other.py", "text": "class unrelated pass"},
    }
    corpus = [docs_by_id[key]["text"] for key in docs_by_id]
    bm25 = BM25(corpus)
    results = top_k_bm25(bm25, docs_by_id, "setup", top_k=2)
    assert isinstance(results, list)
    for r in results:
        assert "id" in r and "path" in r and "text" in r and "score" in r
    # The doc mentioning "setup" should be ranked above the unrelated one.
    assert results[0]["path"] == "mod.py"


def test_hybrid_search_fuses_vector_and_keyword(monkeypatch):
    import rag.bm25 as bm25_mod
    import rag.search as search_module
    import rag.store as store_mod

    fake_collection_docs = [
        ("id-1", "def open_connection(host): return connect(host)", {"path": "net.py"}),
        ("id-2", "class settings: timeout = 30", {"path": "cfg.py"}),
    ]

    class FakeCollection:
        def count(self):
            return len(fake_collection_docs)

        def get(self, include=None):
            ids, docs, metas = zip(*fake_collection_docs)
            return {"ids": list(ids), "documents": list(docs), "metadatas": list(metas)}

        def query(self, **kwargs):
            return {
                "ids": [["id-2", "id-1"]],
                "documents": [
                    [
                        "class settings: timeout = 30",
                        "def open_connection(host): return connect(host)",
                    ]
                ],
                "metadatas": [[{"path": "cfg.py"}, {"path": "net.py"}]],
                "distances": [[0.2, 0.8]],
            }

    def fake_embed(texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def fake_bm25_index_for(collection):
        docs_by_id = {}
        documents = []
        for doc_id, text, meta in fake_collection_docs:
            docs_by_id[doc_id] = {"id": doc_id, "path": meta["path"], "text": text}
            documents.append(text)
        from rag.bm25 import BM25
        return BM25(documents), docs_by_id

    # Patch at the source modules so lazy imports inside search() see them.
    monkeypatch.setattr(store_mod, "get_collection", lambda: FakeCollection())
    monkeypatch.setattr(store_mod, "embed", fake_embed)
    monkeypatch.setattr(bm25_mod, "bm25_index_for", fake_bm25_index_for)

    results = search_module.search("open_connection", top_k=5)
    assert results, "hybrid search should return results"
    paths = {r["path"] for r in results}
    assert "net.py" in paths
    assert "cfg.py" in paths
    for r in results:
        assert 0.0 <= r["score"] <= 1.0
