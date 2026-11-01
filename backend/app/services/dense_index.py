from __future__ import annotations

import contextlib
import hashlib
import threading

import chromadb
import numpy as np
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from .embeddings import get_embedder


class EmbedderAdapter(Embeddings):
    """Exposes the app's embedder through LangChain's Embeddings interface
    (passages and queries get the model's own prefixes)."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return get_embedder().embed_passages(texts).tolist()

    def embed_query(self, text: str) -> list[float]:
        return get_embedder().embed_query(text).tolist()


_lock = threading.Lock()
_client: chromadb.ClientAPI | None = None
_stores: dict[str, Chroma] = {}


def _get_client() -> chromadb.ClientAPI:
    global _client
    with _lock:
        if _client is None:
            _client = chromadb.EphemeralClient(
                settings=ChromaSettings(anonymized_telemetry=False)
            )
        return _client


def _collection_name(session_id: str) -> str:
    digest = hashlib.sha256(session_id.encode()).hexdigest()[:40]
    return f"s-{digest}"


def _store(session_id: str) -> Chroma:
    client = _get_client()
    with _lock:
        store = _stores.get(session_id)
        if store is None:
            store = Chroma(
                collection_name=_collection_name(session_id),
                embedding_function=EmbedderAdapter(),
                client=client,
                collection_configuration={"hnsw": {"space": "cosine"}},
            )
            _stores[session_id] = store
        return store


def _collection(session_id: str):
    return _get_client().get_collection(_collection_name(session_id))


def add(
    session_id: str,
    ids: list[int],
    doc_ids: list[str],
    texts: list[str],
) -> None:
    documents = [
        Document(page_content=text, metadata={"uid": uid, "doc_id": doc_id})
        for uid, doc_id, text in zip(ids, doc_ids, texts, strict=True)
    ]
    _store(session_id).add_documents(documents, ids=[str(uid) for uid in ids])


def count(session_id: str) -> int:
    if session_id not in _stores:
        return 0
    return _collection(session_id).count()


def search(
    session_id: str,
    vector: np.ndarray,
    k: int,
    allowed_doc_ids: set[str] | None = None,
) -> list[tuple[int, float]]:
    """-> [(chunk uid, cosine similarity)], best first.

    Chroma reports cosine distance, which is 1 - similarity."""
    if session_id not in _stores:
        return []
    total = count(session_id)
    if total == 0 or k <= 0:
        return []
    where = None
    if allowed_doc_ids is not None:
        if not allowed_doc_ids:
            return []
        where = {"doc_id": {"$in": sorted(allowed_doc_ids)}}
    store = _store(session_id)
    found = store.similarity_search_by_vector_with_relevance_scores(
        vector.tolist(), k=min(k, total), filter=where
    )
    return [
        (int(doc.metadata["uid"]), 1.0 - float(distance))
        for doc, distance in found
    ]


def vectors_for(session_id: str, uids: list[int]) -> dict[int, np.ndarray]:
    if not uids or session_id not in _stores:
        return {}
    got = _collection(session_id).get(
        ids=[str(u) for u in uids], include=["embeddings"]
    )
    return {
        int(uid): np.asarray(vec, dtype=np.float32)
        for uid, vec in zip(got["ids"], got["embeddings"], strict=True)
    }


def delete_document(session_id: str, doc_id: str) -> None:
    if session_id in _stores:
        _collection(session_id).delete(where={"doc_id": doc_id})


def delete_ids(session_id: str, ids: list[int]) -> None:
    if ids and session_id in _stores:
        _collection(session_id).delete(ids=[str(u) for u in ids])


def delete_session(session_id: str) -> None:
    with _lock:
        existed = _stores.pop(session_id, None) is not None
    if existed:
        with contextlib.suppress(Exception):
            _get_client().delete_collection(_collection_name(session_id))
