from app.services.chunking import split_text
from app.services.text_utils import detect_language, normalize_text, tokenize


def test_russian_morphology_matches():
    forms = ["договор", "договоры", "договоров", "договором"]
    assert len({tuple(tokenize(f)) for f in forms}) == 1
    assert tokenize("выручка") == tokenize("выручки") == tokenize("выручку")


def test_english_stemming_and_yo():
    assert tokenize("contracts")[0] == tokenize("contract")[0]
    assert tokenize("Берёза") == tokenize("береза")


def test_numbers_with_thousand_separators_and_decimal_comma():
    assert tokenize("1 234,5") == ["1234.5"]
    assert tokenize("1\u00a0234\u00a0567") == ["1234567"]
    assert "2023" in tokenize("в 2023 году") and "100" in tokenize("2023 100")


def test_normalize_cleans_pdf_artifacts():
    assert normalize_text("пере-\nнос слова") == "перенос слова"
    assert normalize_text("a\u200bb\x00c  d") == "ab c d"
    assert normalize_text("и\u0306") == "й"


def test_language_detection():
    assert detect_language("Какая выручка за 2023 год?") == "ru"
    assert detect_language("What is the revenue in 2023?") == "en"
    assert detect_language("Revenue за 2023 год по отчёту") == "ru"


def test_chunking_respects_size_and_overlap():
    text = ". ".join(
        f"Sentence number {i} about something" for i in range(200)
    )
    parts = split_text(text, 300, 40)
    assert len(parts) > 3 and all(len(p) <= 300 + 45 for p in parts)
    assert split_text("short", 300, 40) == ["short"]


def test_empty_model_revision_means_none(monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("EMBEDDING_REVISION", "")
    monkeypatch.setenv("RERANKER_REVISION", "")
    cfg = Settings()
    assert cfg.embedding_revision is None and cfg.reranker_revision is None
