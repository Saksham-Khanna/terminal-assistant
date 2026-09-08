"""
Keyword (BM25) retrieval + Reciprocal Rank Fusion (RRF).

Pure-Python implementation with no extra dependencies, so it works alongside
the vector search to give hybrid retrieval: the vector index captures semantic
similarity, BM25 captures exact keyword matches (function names, variables,
error strings), and RRF merges both ranked lists.

RRF formula used:
    RRF(d) = sum over each ranked list L of  1 / (k + rank_L(d))
with k = 60 (standard value from Cormack et al.).

Works directly on the documents already stored in Chroma, so no schema
migration or re-indexing is required.
"""

import math
import re
import threading

# Token regex: alphanumeric runs, lowercase (code identifiers like
# "get_collection" become ["get", "collection"]; paths split on "/" and ".").
_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = {
    "the", "and", "this", "that", "with", "from", "for", "are", "was",
    "will", "have", "has", "had", "its", "not", "but", "can", "you", "your",
    "a", "an", "is", "in", "on", "of", "to", "it", "as", "by", "at", "or",
}

# BM25 parameters (standard Okapi values).
K1 = 1.5
B = 0.75
# RRF constant.
RRF_K = 60


def tokenize(text: str) -> list[str]:
    """Lowercase + split a string into word tokens, dropping stopwords."""
    return [
        token
        for token in _TOKEN_RE.findall(text.lower())
        if token not in _STOPWORDS and len(token) > 1
    ]


class BM25:
    """Okapi BM25 over an in-memory corpus of tokenized documents."""

    def __init__(self, documents: list[str]):
        self._corpus_size = len(documents)
        self._doc_len = []
        self._avg_doc_len = 0.0
        self._postings: dict[str, dict[int, int]] = {}

        for doc_id, doc in enumerate(documents):
            tokens = tokenize(doc)
            self._doc_len.append(len(tokens))
            freqs: dict[str, int] = {}
            for token in tokens:
                freqs[token] = freqs.get(token, 0) + 1
            for token, count in freqs.items():
                self._postings.setdefault(token, {})[doc_id] = count

        if documents:
            self._avg_doc_len = sum(self._doc_len) / self._corpus_size

    def _idf(self, term: str) -> float:
        """IDF for a term: higher for rarer terms."""
        df = len(self._postings.get(term, {}))
        # +1 smoothing keeps IDF finite for terms that appear in every doc.
        return math.log(1 + (self._corpus_size - df + 0.5) / (df + 0.5))

    def score(self, query: str) -> list[float]:
        """Return a BM25 score for every document for the given query."""
        scores = [0.0] * self._corpus_size
        for term in tokenize(query):
            idf = self._idf(term)
            if idf <= 0:
                continue
            for doc_id, freq in self._postings.get(term, {}).items():
                dl = self._doc_len[doc_id]
                denom = freq + K1 * (1 - B + B * (dl / self._avg_doc_len))
                scores[doc_id] += idf * (freq * (K1 + 1)) / denom
        return scores

    def top_k(self, query: str, k: int = 5) -> list[tuple[int, float]]:
        """Return up to `k` (doc_index, score) pairs, highest score first."""
        scores = self.score(query)
        ranked = sorted(range(self._corpus_size), key=lambda i: scores[i], reverse=True)
        return [(i, scores[i]) for i in ranked[:k] if scores[i] > 0]


# ---------------------------------------------------------------------------
# RRF merge
# ---------------------------------------------------------------------------

def _rank_map(ranked: list[dict]) -> dict[str, int]:
    """Map each item's key (= chroma id) to its 1-based rank (only top k items ranked)."""
    return {item["id"]: idx + 1 for idx, item in enumerate(ranked)}


def rrf_merge(*ranked_lists: list[dict], k: int = RRF_K) -> list[dict]:
    """
    Merge ranked result lists (dicts each having an "id" key, in rank order)
    into a single fused ranking. Scores are the sum of 1/(k + rank) across
    lists. Items present in only some lists still participate via the lists
    they do appear in — the others simply contribute 0. Items not ranked in any
    list are excluded.
    """
    id_to_item: dict[str, dict] = {}
    fused: dict[str, float] = {}

    for ranked in ranked_lists:
        for idx, item in enumerate(ranked):
            rank = idx + 1
            fused[item["id"]] = fused.get(item["id"], 0.0) + 1.0 / (k + rank)
            id_to_item.setdefault(item["id"], item)

    ordered = sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
    return [
        {**id_to_item[item_id], "score": score, "rrf": True}
        for item_id, score in ordered
    ]


def top_k_bm25(bm25: BM25, docs_by_id: dict[str, dict], query: str, top_k: int = 5) -> list[dict]:
    """
    Run BM25 against the corpus and return results shaped like the vector
    search output (each item has id/path/text/score), ready for RRF fusion.

    ``docs_by_id`` maps chroma id -> {"id", "path", "text"} so BM25's internal
    integer indices can be resolved back to chroma ids.
    """
    ordered = list(docs_by_id.items())  # stable: index == position in corpus
    hits = bm25.top_k(query, k=top_k)
    results = []
    for idx, score in hits:
        doc_id, meta = ordered[idx]
        results.append({
            "id": doc_id,
            "path": meta.get("path", ""),
            "text": meta.get("text", ""),
            "score": score,
        })
    return results


# ---------------------------------------------------------------------------
# Shared hybrid search over the chroma collection
# ---------------------------------------------------------------------------

_hybrid_lock = threading.Lock()
_bm25_cache = {"count": -1, "bm25": None, "docs": None}


def bm25_index_for(collection) -> tuple[BM25, dict[str, dict]]:
    """
    Build (or return cached) BM25 over everything in the collection.

    The cache is invalidated whenever the collection's item count changes, so
    a fresh ``index`` command automatically picks up the new corpus.
    """
    count = collection.count()
    with _hybrid_lock:
        cached_count = _bm25_cache["count"]
        if cached_count == count and _bm25_cache["bm25"] is not None:
            return _bm25_cache["bm25"], _bm25_cache["docs"]

        fetched = collection.get(include=["documents", "metadatas"])
        docs: dict[str, dict] = {}
        documents: list[str] = []
        for doc_id, text, meta in zip(
            fetched["ids"], fetched["documents"], fetched["metadatas"]
        ):
            docs[doc_id] = {"path": meta.get("path", ""), "text": text, "id": doc_id}
            documents.append(text or "")

        bm25 = BM25(documents)
        _bm25_cache.update({"count": count, "bm25": bm25, "docs": docs})
        return bm25, docs
