"""Tenant-scoped hybrid retrieval: BM25 (keyword) + TF-IDF cosine (sparse vector), fused with
Reciprocal Rank Fusion. One in-memory index per organization, built only from that
organization's rows, so a query physically cannot see another tenant's chunks."""
import math
import re
import threading
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer

from app.db import get_conn

_KEEP = {"not", "no", "above", "below", "under", "over", "more", "less", "least", "most", "before", "after"}
STOP = (set(ENGLISH_STOP_WORDS) - _KEEP) | {"policy", "document", "please", "tell", "know", "want", "does", "do"}


def _stem(word: str) -> str:
    for suffix in ("ies", "ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def tokenize(text: str) -> List[str]:
    words = re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", text.lower())
    return [_stem(w) for w in words if w not in STOP and len(w) > 1]


@dataclass
class Hit:
    chunk_id: int
    document_id: int
    filename: str
    page: int
    text: str
    score: float  # fused score
    bm25: float
    cosine: float


@dataclass
class OrgIndex:
    chunk_ids: List[int]
    meta: List[dict]
    tokens: List[List[str]]
    df: Counter
    avgdl: float
    vectorizer: TfidfVectorizer = None
    matrix: object = None
    term_freqs: List[Counter] = field(default_factory=list)


_cache: Dict[int, OrgIndex] = {}
_lock = threading.Lock()


def invalidate(org_id: int) -> None:
    with _lock:
        _cache.pop(org_id, None)


def _build(org_id: int) -> OrgIndex:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT c.id, c.document_id, c.page, c.text, d.filename
               FROM chunks c JOIN documents d ON d.id = c.document_id
               WHERE c.org_id = ? AND d.org_id = ? AND d.status = 'ready'
               ORDER BY c.id""",
            (org_id, org_id),
        ).fetchall()
    meta = [dict(r) for r in rows]
    tokens = [tokenize(r["text"]) for r in meta]
    df = Counter()
    for toks in tokens:
        df.update(set(toks))
    index = OrgIndex(
        chunk_ids=[r["id"] for r in meta],
        meta=meta,
        tokens=tokens,
        df=df,
        avgdl=(sum(len(t) for t in tokens) / len(tokens)) if tokens else 1.0,
        term_freqs=[Counter(t) for t in tokens],
    )
    if meta:
        index.vectorizer = TfidfVectorizer(analyzer=lambda s: _ngrams(tokenize(s)), sublinear_tf=True)
        index.matrix = index.vectorizer.fit_transform([r["text"] for r in meta])
    return index


def _ngrams(tokens: List[str]) -> List[str]:
    return tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]


def get_index(org_id: int) -> OrgIndex:
    with _lock:
        if org_id not in _cache:
            _cache[org_id] = _build(org_id)
        return _cache[org_id]


def _bm25(index: OrgIndex, q_tokens: List[str], k1: float = 1.5, b: float = 0.75) -> np.ndarray:
    n = len(index.tokens)
    scores = np.zeros(n)
    for term in set(q_tokens):
        df = index.df.get(term, 0)
        if not df:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, tf_counter in enumerate(index.term_freqs):
            tf = tf_counter.get(term, 0)
            if tf:
                dl = len(index.tokens[i])
                scores[i] += idf * tf * (k1 + 1) / (tf + k1 * (1 - b + b * dl / index.avgdl))
    return scores


def search(org_id: int, query: str, top_k: int = 5) -> List[Hit]:
    index = get_index(org_id)
    if not index.meta:
        return []
    q_tokens = tokenize(query)
    if not q_tokens:
        return []
    bm25 = _bm25(index, q_tokens)
    cos = (index.matrix @ index.vectorizer.transform([query]).T).toarray().ravel()

    # Reciprocal Rank Fusion (k=60) of the two rankings.
    fused = np.zeros(len(index.meta))
    for scores in (bm25, cos):
        order = np.argsort(-scores)
        for rank, i in enumerate(order):
            if scores[i] > 0:
                fused[i] += 1.0 / (60 + rank + 1)

    order = [i for i in np.argsort(-fused) if fused[i] > 0][:top_k]
    return [
        Hit(
            chunk_id=index.meta[i]["id"],
            document_id=index.meta[i]["document_id"],
            filename=index.meta[i]["filename"],
            page=index.meta[i]["page"],
            text=index.meta[i]["text"],
            score=float(fused[i]),
            bm25=float(bm25[i]),
            cosine=float(cos[i]),
        )
        for i in order
    ]


def query_coverage(query: str, hits: List[Hit]) -> float:
    """Fraction of the question's content words that appear in the top retrieved chunks."""
    q = set(tokenize(query))
    if not q or not hits:
        return 0.0
    seen = set()
    for h in hits[:3]:
        seen.update(tokenize(h.text))
    return len(q & seen) / len(q)


def idf_weighted_coverage(org_id: int, query: str, hits: List[Hit]) -> float:
    """Like query_coverage but rare (informative) words count more than common ones."""
    index = get_index(org_id)
    q = set(tokenize(query))
    if not q or not hits:
        return 0.0
    n = max(len(index.tokens), 1)
    seen = set()
    for h in hits[:3]:
        seen.update(tokenize(h.text))

    def w(t):  # unseen-in-corpus terms get the max idf: they are what makes a question out of scope
        return math.log(1 + n / (index.df.get(t, 0) + 0.5))

    total = sum(w(t) for t in q)
    return sum(w(t) for t in q if t in seen) / total if total else 0.0
