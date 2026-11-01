import io
import zipfile

import pytest

from app.services.file_processing import (
    FileProcessingError,
    Limits,
    extract_blocks,
)
from tests.helpers import cyrillic_font_path


def _text(blocks):
    return "\n".join(b.text for b in blocks)


def test_csv_cp1251_semicolon_keeps_all_rows():
    data = (
        "Название;Выручка\nООО Ромашка;1000\nИП Иванов;2 500,50\n"
        "широко;1;2;3;4\n"
    ).encode("cp1251")
    blocks = extract_blocks(data, ".csv")
    t = _text(blocks)
    assert "Ромашка" in t and "2 500,50" in t and "широко" in t
    assert blocks[0].header == "Название | Выручка"


def test_csv_utf8_bom_and_utf16():
    assert "Привет" in _text(
        extract_blocks("a,b\nПривет,мир\n".encode("utf-8-sig"), ".csv")
    )
    assert "Привет" in _text(
        extract_blocks("a,b\nПривет,мир\n".encode("utf-16"), ".csv")
    )


def test_real_xls_and_xlsx_with_russian():
    import xlwt
    from openpyxl import Workbook

    wb = xlwt.Workbook()
    ws = wb.add_sheet("Лист1")
    for r, row in enumerate([["Товар", "Цена"], ["Яблоко", 12.5]]):
        for c, v in enumerate(row):
            ws.write(r, c, v)
    buf = io.BytesIO()
    wb.save(buf)
    b = extract_blocks(buf.getvalue(), ".xls")
    assert "Яблоко" in _text(b) and "Лист1" in b[0].location

    wb2 = Workbook()
    s2 = wb2.active
    s2.title = "Sales"
    s2.append(["Product", "Qty"])
    s2.append(["Apple", 3])
    s2.append(["Груша", 4.0])
    buf2 = io.BytesIO()
    wb2.save(buf2)
    for ext in (".xlsx", ".xls"):
        b = extract_blocks(buf2.getvalue(), ext)
        assert "Груша | 4" in _text(b) and "Sales" in b[0].location


def test_docx_order_headings_tables_and_merged_cells():
    from docx import Document

    d = Document()
    d.add_heading("Договор поставки", 1)
    d.add_paragraph("Срок действия: 12 месяцев.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text = "Item"
    t.cell(0, 1).text = "Price"
    t.cell(1, 0).merge(t.cell(1, 1))
    t.cell(1, 0).text = "Merged"
    d.add_heading("Terms", 1)
    d.add_paragraph("Payment within 30 days.")
    buf = io.BytesIO()
    d.save(buf)
    blocks = extract_blocks(buf.getvalue(), ".docx")
    t_ = _text(blocks)
    assert (
        "Срок действия" in t_
        and "Payment within 30 days" in t_
        and t_.count("Merged") == 1
    )
    assert any("Договор поставки" in b.location for b in blocks)


def test_pdf_english_and_cyrillic():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    pdfmetrics.registerFont(TTFont("CyrFont", cyrillic_font_path()))
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.setFont("CyrFont", 12)
    c.drawString(72, 750, "Annual revenue was 1200 USD.")
    c.showPage()
    c.setFont("CyrFont", 12)
    c.drawString(72, 750, "Годовая выручка составила 1200 рублей.")
    c.save()
    blocks = extract_blocks(buf.getvalue(), ".pdf")
    assert blocks[0].location == "page 1" and "revenue" in blocks[0].text
    assert "Годовая выручка" in blocks[1].text


def test_rejects_wrong_content_and_empty():
    with pytest.raises(FileProcessingError):
        extract_blocks(b"MZ\x90\x00 not a pdf", ".pdf")
    with pytest.raises(FileProcessingError):
        extract_blocks(b"%PDF-1.4 garbage", ".pdf")
    with pytest.raises(FileProcessingError):
        extract_blocks(b"", ".csv")


def test_zip_bomb_rejected():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "<w/>")
        z.writestr("big.bin", b"0" * (60 * 1024 * 1024))
    assert len(buf.getvalue()) < 200_000
    with pytest.raises(FileProcessingError, match="unreasonable"):
        extract_blocks(
            buf.getvalue(),
            ".docx",
            Limits(max_uncompressed_bytes=50 * 1024 * 1024),
        )


def test_text_budget_enforced():
    rows = "a,b\n" + "x" * 50 + ",y\n" * 1
    big = "a,b\n" + "\n".join(f"{'x' * 100},{i}" for i in range(500))
    with pytest.raises(FileProcessingError, match="too much text"):
        extract_blocks(big.encode(), ".csv", Limits(max_text_chars=10_000))
    assert extract_blocks(rows.encode(), ".csv")


def scanned_pdf(
    lines_per_page=(
        ("Годовая выручка компании", "составила 1250000 рублей."),
        ("Annual revenue of the company", "was 1200 USD in 2023."),
    ),
) -> bytes:
    """An image-only PDF (no text layer), like a scanner produces."""
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    font = ImageFont.truetype(cyrillic_font_path(), 34)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(620, 400))
    for lines in lines_per_page:
        img = Image.new("RGB", (1240, 800), "white")
        d = ImageDraw.Draw(img)
        for i, line in enumerate(lines):
            d.text((60, 60 + i * 70), line, fill="black", font=font)
        b = io.BytesIO()
        img.save(b, "PNG")
        b.seek(0)
        c.drawImage(ImageReader(b), 0, 0, 620, 400)
        c.showPage()
    c.save()
    return buf.getvalue()


needs_tesseract = pytest.mark.skipif(
    __import__("shutil").which("tesseract") is None,
    reason="tesseract not installed",
)


@needs_tesseract
def test_ocr_reads_russian_and_english_scans():
    blocks = extract_blocks(scanned_pdf(), ".pdf")
    assert (
        blocks[0].location == "page 1 (OCR)"
        and "выручка" in blocks[0].text.lower()
        and "1250000" in blocks[0].text
    )
    assert (
        blocks[1].location == "page 2 (OCR)"
        and "revenue" in blocks[1].text.lower()
        and "1200" in blocks[1].text
    )


def test_scanned_pdf_without_ocr_gives_a_clear_message():
    with pytest.raises(FileProcessingError, match="OCR|scanned|readable"):
        extract_blocks(scanned_pdf(), ".pdf", Limits(ocr_enabled=False))


def test_digital_pdf_with_a_blank_page_is_not_ocrd(monkeypatch):
    from reportlab.pdfgen import canvas

    from app.services import file_processing as fp

    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for i in range(3):
        c.drawString(
            72,
            750,
            f"Page {i} has plenty of real extractable text content here.",
        )
        c.showPage()
    c.showPage()
    c.save()
    monkeypatch.setattr(
        fp,
        "_ocr_pages",
        lambda *a, **k: pytest.fail(
            "OCR must not run for mostly-digital PDFs"
        ),
    )
    assert len(extract_blocks(buf.getvalue(), ".pdf")) == 3


@needs_tesseract
def test_ocr_progress_is_reported_from_the_child_process(monkeypatch):
    from app.core.config import get_settings
    from app.services.parsing import parse_document

    monkeypatch.setattr(get_settings(), "parse_in_subprocess", True)
    seen = []
    doc = parse_document(
        scanned_pdf(),
        ".pdf",
        on_progress=lambda f, st: seen.append((round(f, 2), st)),
    )
    assert (
        doc.blocks
        and ("ocr" in {st for _, st in seen})
        and max(f for f, _ in seen) == 1.0
    )


def test_tables_are_extracted_for_sql_from_csv_and_xlsx():
    from openpyxl import Workbook

    from app.services.file_processing import extract_document

    d = extract_document(
        "Город;Сумма\nМосква;1 000,5\nКазань;2\n".encode("cp1251"),
        ".csv",
        name="sales",
    )
    assert (
        d.tables[0].name == "sales"
        and d.tables[0].header == ["Город", "Сумма"]
        and len(d.tables[0].rows) == 2
    )
    wb = Workbook()
    ws = wb.active
    ws.title = "Q1"
    ws.append(["a", "a", ""])
    ws.append([1, 2, 3])
    buf = io.BytesIO()
    wb.save(buf)
    t = extract_document(buf.getvalue(), ".xlsx").tables[0]
    assert t.name == "Q1" and t.header == [
        "a",
        "a_2",
        "col_3",
    ]


def test_oversized_tables_stay_text_only():
    from app.services.file_processing import extract_document

    big = "a,b\n" + "\n".join(f"{i},{i}" for i in range(100))
    d = extract_document(big.encode(), ".csv", Limits(max_table_cells=50))
    assert d.tables == [] and d.blocks
