from __future__ import annotations

import itertools
import math
import threading
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np

from app.core.config import get_settings

from . import dense_index
from .chunking import split_text
from .embeddings import get_embedder
from .file_processing import FileProcessingError, TextBlock
from .text_utils import detect_language, tokenize

_RRF_K = 60
_BM25_K1, _BM25_B = 1.5, 0.75


_uid = itertools.count(1)


@dataclass
class Chunk:
    uid: int
    lang: str
    doc_id: str
    filename: str
    location: str
    text: str
    tf: Counter
    length: int


@dataclass
class Hit:
    uid: int
    doc_id: str
    filename: str
    location: str
    text: str
    relevance: float
    dense_sim: float
    lexical: bool


@dataclass
class _Index:
    chunks: list[Chunk] = field(default_factory=list)
    by_uid: dict[int, Chunk] = field(default_factory=dict)
    df: Counter = field(default_factory=Counter)
    total_len: int = 0
    lock: threading.RLock = field(default_factory=threading.RLock)


_indexes: dict[str, _Index] = {}
_registry_lock = threading.Lock()


def _get(session_id: str, create: bool = False) -> _Index | None:
    with _registry_lock:
        idx = _indexes.get(session_id)
        if idx is None and create:
            idx = _indexes[session_id] = _Index()
        return idx


def build_chunks(
    blocks: list[TextBlock], filename: str
) -> list[tuple[str, str]]:
    """-> [(location, text)] with the table header re-attached to every
    table chunk."""
    s = get_settings()
    out: list[tuple[str, str]] = []
    for block in blocks:
        for piece in split_text(block.text, s.chunk_size, s.chunk_overlap):
            text = piece
            if block.header and not piece.startswith(block.header):
                text = f"{block.header}\n{piece}"
            out.append((block.location, text))
    return out


def index_document(
    session_id: str,
    doc_id: str,
    filename: str,
    blocks: list[TextBlock],
    on_progress: Callable[[float], None] | None = None,
) -> int:
    items = build_chunks(blocks, filename)
    if not items:
        return 0
    existing = _get(session_id)
    cap = get_settings().max_chunks_per_session
    if existing is not None:
        with existing.lock:
            current = len(existing.chunks)
    else:
        current = 0
    if current + len(items) > cap:
        raise FileProcessingError(
            "The search index for this session is full. "
            "Delete some documents and try again."
        )
    new_chunks = []
    for loc, text in items:
        toks = tokenize(text)
        new_chunks.append(
            Chunk(
                next(_uid),
                detect_language(text),
                doc_id,
                filename,
                loc,
                text,
                Counter(toks),
                len(toks),
            )
        )
    step = max(1, get_settings().embedding_batch_size * 2)
    stored: list[int] = []
    try:
        for i in range(0, len(new_chunks), step):
            stop = i + step
            part = new_chunks[i:stop]
            dense_index.add(
                session_id,
                [c.uid for c in part],
                [c.doc_id for c in part],
                [c.text for c in part],
            )
            stored.extend(c.uid for c in part)
            if on_progress:
                on_progress(min(1.0, (i + step) / len(new_chunks)))
    except BaseException:
        dense_index.delete_ids(session_id, stored)
        raise
    idx = _get(session_id, create=True)
    with idx.lock:
        idx.chunks.extend(new_chunks)
        for c in new_chunks:
            idx.by_uid[c.uid] = c
            idx.df.update(c.tf.keys())
            idx.total_len += c.length
    return len(new_chunks)


def delete_document(session_id: str, doc_id: str) -> None:
    dense_index.delete_document(session_id, doc_id)
    idx = _get(session_id)
    if idx is None:
        return
    with idx.lock:
        keep = [c for c in idx.chunks if c.doc_id != doc_id]
        if len(keep) == len(idx.chunks):
            return
        for c in idx.chunks:
            if c.doc_id == doc_id:
                idx.df.subtract(c.tf.keys())
                idx.total_len -= c.length
                idx.by_uid.pop(c.uid, None)
        idx.df = +idx.df
        idx.chunks = keep


def delete_session(session_id: str) -> None:
    dense_index.delete_session(session_id)
    with _registry_lock:
        _indexes.pop(session_id, None)


def has_document(session_id: str, doc_id: str) -> bool:
    idx = _get(session_id)
    if idx is None:
        return False
    with idx.lock:
        return any(c.doc_id == doc_id for c in idx.chunks)


def _bm25(idx: _Index, q_tokens: list[str]) -> np.ndarray:
    n = len(idx.chunks)
    scores = np.zeros(n, dtype=np.float32)
    if not n or not q_tokens:
        return scores
    avg = max(idx.total_len / n, 1.0)
    for tok in set(q_tokens):
        df = idx.df.get(tok, 0)
        if df == 0:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, c in enumerate(idx.chunks):
            tf = c.tf.get(tok)
            if tf:
                scores[i] += (
                    idf
                    * tf
                    * (_BM25_K1 + 1)
                    / (
                        tf
                        + _BM25_K1 * (1 - _BM25_B + _BM25_B * c.length / avg)
                    )
                )
    return scores


def _rank(scores: np.ndarray, pool: int, positive_only: bool) -> list[int]:
    order = np.argsort(-scores, kind="stable")[:pool]
    return [
        int(i)
        for i in order
        if np.isfinite(scores[i]) and (not positive_only or scores[i] > 0)
    ]


def language_stats(
    session_id: str, allowed_doc_ids: set[str] | None = None
) -> Counter:
    """Chunk counts per language ('ru' / 'en') among the (allowed)
    documents of a session."""
    idx = _get(session_id)
    if idx is None:
        return Counter()
    with idx.lock:
        return Counter(
            c.lang
            for c in idx.chunks
            if allowed_doc_ids is None or c.doc_id in allowed_doc_ids
        )


def diversify(hits: list[Hit], top_k: int, per_doc: int) -> list[Hit]:
    """At most `per_doc` chunks per document so one file cannot crowd out
    the others."""
    picked: list[Hit] = []
    count: Counter = Counter()
    for h in hits:
        if count[h.doc_id] < per_doc:
            picked.append(h)
            count[h.doc_id] += 1
        if len(picked) >= top_k:
            break
    return picked


def search(
    session_id: str,
    query: str,
    top_k: int | None = None,
    allowed_doc_ids: set[str] | None = None,
    pool: int | None = None,
    apply_diversity: bool = True,
) -> list[Hit]:
    s = get_settings()
    top_k = top_k or s.retrieval_top_k
    pool = pool or s.candidate_pool
    idx = _get(session_id)
    if idx is None:
        return []
    q_vec = get_embedder().embed_query(query)
    q_tokens = tokenize(query)
    with idx.lock:
        if not idx.chunks:
            return []
        mask = np.ones(len(idx.chunks), dtype=bool)
        if allowed_doc_ids is not None:
            mask = np.array([c.doc_id in allowed_doc_ids for c in idx.chunks])
            if not mask.any():
                return []
        dense_ranked = [
            (uid, sim)
            for uid, sim in dense_index.search(
                session_id, q_vec, pool, allowed_doc_ids
            )
            if uid in idx.by_uid
        ]
        lexical = np.where(mask, _bm25(idx, q_tokens), 0.0)
        fused: dict[int, float] = {}
        for rank, (uid, _) in enumerate(dense_ranked):
            fused[uid] = fused.get(uid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        for rank, i in enumerate(_rank(lexical, pool, True)):
            uid = idx.chunks[i].uid
            fused[uid] = fused.get(uid, 0.0) + 1.0 / (_RRF_K + rank + 1)
        ordered = sorted(fused, key=fused.get, reverse=True)

        lexical_uids = {idx.chunks[i].uid for i in np.flatnonzero(lexical > 0)}
        dense_sim = dict(dense_ranked)
        missing = [uid for uid in ordered if uid not in dense_sim]
        for uid, vec in dense_index.vectors_for(session_id, missing).items():
            dense_sim[uid] = float(vec @ q_vec)

        if s.min_dense_similarity > 0:
            ordered = [
                uid
                for uid in ordered
                if uid in lexical_uids
                or dense_sim.get(uid, 0.0) >= s.min_dense_similarity
            ]

        picked = ordered[: top_k * 4 if apply_diversity else top_k]
        best = 2.0 / (_RRF_K + 1)
        hits = [
            Hit(
                uid,
                idx.by_uid[uid].doc_id,
                idx.by_uid[uid].filename,
                idx.by_uid[uid].location,
                idx.by_uid[uid].text,
                min(1.0, fused[uid] / best),
                dense_sim.get(uid, 0.0),
                uid in lexical_uids,
            )
            for uid in picked
        ]
        return (
            diversify(hits, top_k, s.max_chunks_per_doc_in_context)
            if apply_diversity
            else hits
        )
