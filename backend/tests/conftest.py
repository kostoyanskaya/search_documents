import hashlib
import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.core.ratelimit import limiter
from app.services import embeddings, llm
from app.services.text_utils import tokenize


class FakeEmbedder:

    dim = 256

    def _vec(self, text):
        v = np.zeros(self.dim, dtype=np.float32)
        for t in tokenize(text):
            v[int(hashlib.md5(t.encode()).hexdigest(), 16) % self.dim] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v

    def embed_passages(self, texts):
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text):
        return self._vec(text)


class FakeReranker:

    def score(self, query, passages):
        q = set(tokenize(query))
        return [len(q & set(tokenize(p))) / max(len(q), 1) for p in passages]


class FakeLLM:

    ROLES = [
        ("prepare a search query", "rewrite"),
        ("DIFFERENT search queries", "reformulate"),
        ("write ONE read-only DuckDB", "sql"),
        ("explain the result of a database query", "sql_answer"),
        ("answer questions about the user's documents", "answer"),
    ]

    def __init__(self):
        self.handlers, self.calls = {}, []

    def on(self, role, handler):
        self.handlers[role] = handler
        return self

    def roles(self):
        return [c[0] for c in self.calls]

    def __call__(self, system, user, **kwargs):
        role = next(
            (r for marker, r in self.ROLES if marker in system), "unknown"
        )
        self.calls.append((role, system, user))
        handler = self.handlers.get(role)
        if handler is None:
            default = {
                "rewrite": {
                    "standalone": user.rsplit("Question:", 1)[-1].strip(),
                    "translation": "",
                },
                "reformulate": {"queries": []},
                "sql": {"sql": ""},
                "sql_answer": {"answer": ""},
                "answer": {"answer": "", "found": False, "sources": []},
            }[role]
            return json.dumps(default, ensure_ascii=False)
        out = handler(user) if callable(handler) else handler
        return (
            out
            if isinstance(out, str)
            else json.dumps(out, ensure_ascii=False)
        )


@pytest.fixture(autouse=True)
def _fakes():
    embeddings.set_embedder(FakeEmbedder())
    embeddings.set_reranker(FakeReranker())
    limiter._buckets.clear()
    yield
    embeddings.set_embedder(None)
    embeddings.set_reranker(None)


@pytest.fixture
def fake_llm(monkeypatch):
    script = FakeLLM()
    monkeypatch.setattr(llm, "complete", script)
    return script


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app(), base_url="http://localhost") as c:
        yield c
