from app.services import vector_store as vs
from app.services.file_processing import TextBlock

DOCS = {
    "ru": [
        TextBlock(
            "Договор поставки № 45. Срок действия договора составляет "
            "12 месяцев. Оплата в течение 30 дней.",
            "page 1",
        ),
        TextBlock(
            "Выручка компании за 2023 год составила 1 250 000 рублей.",
            "page 2",
        ),
    ],
    "en": [
        TextBlock(
            "The lease agreement is valid for 24 months. "
            "Monthly rent is 3,400 USD.",
            "page 1",
        ),
        TextBlock(
            "Employee handbook: vacation policy grants 25 days per year.",
            "page 2",
        ),
    ],
}


def _load(sid="s1"):
    vs.delete_session(sid)
    vs.index_document(sid, "ru", "dogovor.pdf", DOCS["ru"])
    vs.index_document(sid, "en", "lease.pdf", DOCS["en"])


def test_russian_query_finds_inflected_forms_in_russian_doc():
    _load()
    hits = vs.search("s1", "какой срок договоров?", 3)
    assert hits[0].doc_id == "ru" and hits[0].lexical


def test_english_query_finds_english_doc():
    _load()
    assert vs.search("s1", "how many vacation days", 2)[0].doc_id == "en"


def test_exact_number_found_lexically_in_both_notations():
    _load()
    assert vs.search("s1", "1250000 рублей", 2)[0].doc_id == "ru"
    assert vs.search("s1", "rent 3,400", 2)[0].doc_id == "en"


def test_sessions_are_isolated():
    _load("a")
    vs.delete_session("b")
    assert vs.search("b", "договор", 5) == []
    vs.delete_session("a")
    assert vs.search("a", "договор", 5) == []


def test_delete_document_removes_chunks_and_stats():
    _load()
    vs.delete_document("s1", "ru")
    assert all(h.doc_id == "en" for h in vs.search("s1", "договор срок", 5))
    assert not vs.has_document("s1", "ru")


def test_allowed_doc_filter():
    _load()
    assert all(
        h.doc_id == "en"
        for h in vs.search("s1", "срок 12 месяцев", 5, allowed_doc_ids={"en"})
    )


def test_table_header_repeated_in_chunks():
    vs.delete_session("t")
    rows = "\n".join(f"Item{i} | {i * 10}" for i in range(200))
    vs.index_document(
        "t",
        "d",
        "t.csv",
        [TextBlock(rows, "rows 2-201", header="Name | Price")],
    )
    idx = vs._indexes["t"]
    assert len(idx.chunks) > 1 and all(
        c.text.startswith("Name | Price") for c in idx.chunks
    )


def test_session_chunk_cap_rejects_oversized_index(monkeypatch):
    import pytest

    from app.core.config import get_settings
    from app.services import vector_store
    from app.services.file_processing import FileProcessingError, TextBlock

    monkeypatch.setattr(get_settings(), "max_chunks_per_session", 2)
    blocks = [TextBlock(f"text number {i}", f"p{i}") for i in range(3)]
    try:
        with pytest.raises(FileProcessingError, match="index"):
            vector_store.index_document("cap-session", "d1", "a.txt", blocks)
    finally:
        vector_store.delete_session("cap-session")
