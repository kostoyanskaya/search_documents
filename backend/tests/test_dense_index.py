import os

import numpy as np
import pytest

from app.core.config import get_settings
from app.services import dense_index
from app.services import vector_store as vs
from app.services.chunking import split_text
from app.services.embeddings import get_embedder
from app.services.file_processing import FileProcessingError, TextBlock

SID = "chroma-session"

RU = [
    TextBlock("Срок действия договора составляет 12 месяцев.", "page 1"),
    TextBlock("Выручка за 2023 год составила 1 250 000 рублей.", "page 2"),
]
EN = [
    TextBlock("The lease is valid for 24 months. Rent is 3400 USD.", "p1"),
    TextBlock("Vacation policy grants 25 days per year.", "p2"),
]


@pytest.fixture(autouse=True)
def _clean():
    vs.delete_session(SID)
    yield
    vs.delete_session(SID)


def _load():
    vs.index_document(SID, "ru", "dogovor.pdf", RU)
    vs.index_document(SID, "en", "lease.pdf", EN)


def test_chunks_are_stored_in_chroma_and_in_the_bm25_index():
    _load()
    assert dense_index.count(SID) == len(vs._indexes[SID].chunks) == 4


def test_dense_similarity_equals_exact_cosine():
    _load()
    query = "срок договора"
    q_vec = get_embedder().embed_query(query)
    hits = vs.search(SID, query, 4, apply_diversity=False)
    assert hits
    for hit in hits:
        vec = get_embedder().embed_passages([hit.text])[0]
        assert hit.dense_sim == pytest.approx(float(vec @ q_vec), abs=1e-4)


def test_lexical_only_hits_still_get_a_dense_similarity(monkeypatch):
    _load()
    monkeypatch.setattr(dense_index, "search", lambda *a, **k: [])
    hits = vs.search(SID, "vacation policy", 2)
    assert hits and hits[0].lexical and hits[0].dense_sim > 0


def test_document_filter_is_applied_inside_chroma():
    _load()
    hits = vs.search(SID, "месяцев", 8, allowed_doc_ids={"en"})
    assert all(h.doc_id == "en" for h in hits)
    assert vs.search(SID, "месяцев", 8, allowed_doc_ids=set()) == []


def test_delete_document_removes_vectors_and_bm25_entries():
    _load()
    vs.delete_document(SID, "ru")
    assert dense_index.count(SID) == 2
    assert all(h.doc_id == "en" for h in vs.search(SID, "договор", 8))
    assert not vs.has_document(SID, "ru")


def test_delete_session_drops_the_collection():
    _load()
    vs.delete_session(SID)
    assert dense_index.count(SID) == 0 and vs.search(SID, "договор") == []
    _load()
    assert dense_index.count(SID) == 4


def test_sessions_do_not_see_each_others_vectors():
    _load()
    vs.index_document("other", "x", "x.pdf", [TextBlock("Secret", "p1")])
    try:
        assert all(h.doc_id != "x" for h in vs.search(SID, "secret", 8))
    finally:
        vs.delete_session("other")


def test_failed_embedding_leaves_no_partial_vectors(monkeypatch):
    vs.index_document(SID, "ru", "dogovor.pdf", RU)
    before = dense_index.count(SID)
    calls = {"n": 0}
    real = dense_index.add

    def flaky(session_id, ids, doc_ids, texts):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("embedder crashed")
        real(session_id, ids, doc_ids, texts)

    monkeypatch.setattr(dense_index, "add", flaky)
    monkeypatch.setattr(get_settings(), "embedding_batch_size", 1)
    many = [
        TextBlock(f"Paragraph number {i} " * 40, f"p{i}") for i in range(6)
    ]
    with pytest.raises(RuntimeError):
        vs.index_document(SID, "big", "big.pdf", many)
    assert dense_index.count(SID) == before
    assert not vs.has_document(SID, "big")


def test_chunk_cap_is_enforced(monkeypatch):
    monkeypatch.setattr(get_settings(), "max_chunks_per_session", 2)
    blocks = [TextBlock(f"text number {i}", f"p{i}") for i in range(3)]
    with pytest.raises(FileProcessingError, match="index"):
        vs.index_document(SID, "d", "a.txt", blocks)


def test_chroma_keeps_everything_in_memory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _load()
    vs.search(SID, "договор")
    assert os.listdir(tmp_path) == []


def test_langchain_splitter_overlaps_and_respects_size():
    text = " ".join(f"Sentence number {i} is here." for i in range(120))
    parts = split_text(text, 300, 60)
    assert len(parts) > 3 and all(len(p) <= 300 for p in parts)
    tail = parts[0][-30:].strip()
    assert any(word in parts[1] for word in tail.split()[-2:])


def test_langchain_adapter_uses_the_application_embedder():
    adapter = dense_index.EmbedderAdapter()
    docs = adapter.embed_documents(["один", "two"])
    query = adapter.embed_query("один")
    assert len(docs) == 2 and len(query) == len(docs[0])
    assert np.allclose(docs[0], query)
