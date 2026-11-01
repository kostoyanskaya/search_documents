from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from app.core.config import get_settings


class Embedder(Protocol):
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    def __init__(
        self, model_name: str, batch_size: int, revision: str | None = None
    ):
        from sentence_transformers import (
            SentenceTransformer,
        )

        self._model = SentenceTransformer(model_name, revision=revision)
        self._model.max_seq_length = min(
            512, self._model.max_seq_length or 512
        )
        self._batch = batch_size
        self._lock = threading.Lock()
        name = model_name.lower()
        self._qp, self._pp = (
            ("query: ", "passage: ") if "e5" in name else ("", "")
        )

    def _encode(self, texts: list[str]) -> np.ndarray:
        with self._lock:
            vecs = self._model.encode(
                texts,
                batch_size=self._batch,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return np.asarray(vecs, dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([self._pp + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._encode([self._qp + text])[0]


_embedder: Embedder | None = None
_init_lock = threading.Lock()


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        with _init_lock:
            if _embedder is None:
                s = get_settings()
                _embedder = SentenceTransformerEmbedder(
                    s.embedding_model,
                    s.embedding_batch_size,
                    s.embedding_revision,
                )
    return _embedder


def set_embedder(embedder: Embedder | None) -> None:
    """Dependency-injection hook (used by tests)."""
    global _embedder
    _embedder = embedder


class Reranker(Protocol):
    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance in [0, 1] for each passage (higher = more relevant)."""


class CrossEncoderReranker:
    def __init__(self, model_name: str, revision: str | None = None):
        from sentence_transformers import (
            CrossEncoder,
        )

        self._model = CrossEncoder(
            model_name, max_length=512, revision=revision
        )
        self._lock = threading.Lock()

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        pairs = [(query, p[:1500]) for p in passages]
        with self._lock:
            out = np.asarray(
                self._model.predict(
                    pairs, batch_size=8, show_progress_bar=False
                ),
                dtype=np.float64,
            )
        out = out.reshape(len(passages), -1)[:, -1] if out.ndim > 1 else out
        if out.min() < 0.0 or out.max() > 1.0:
            out = 1.0 / (1.0 + np.exp(-np.clip(out, -30, 30)))
        return [float(x) for x in out]


_reranker: Reranker | None = None
_reranker_disabled = False


def get_reranker() -> Reranker | None:
    global _reranker
    if _reranker is None and not _reranker_disabled:
        with _init_lock:
            if _reranker is None and not _reranker_disabled:
                s = get_settings()
                if not s.reranker_model:
                    return None
                _reranker = CrossEncoderReranker(
                    s.reranker_model, s.reranker_revision
                )
    return _reranker


def set_reranker(reranker: Reranker | None, disabled: bool = False) -> None:
    global _reranker, _reranker_disabled
    _reranker, _reranker_disabled = reranker, disabled
