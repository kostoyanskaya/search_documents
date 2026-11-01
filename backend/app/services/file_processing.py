from __future__ import annotations

import csv
import datetime as dt
import io
import re
import shutil
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field

from charset_normalizer import from_bytes

csv.field_size_limit(1 << 24)

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".xls", ".csv"}
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

Progress = Callable[[float, str], None]


class FileProcessingError(Exception):
    """Raised with a message that is safe to show to the end user."""


@dataclass
class Limits:
    max_pdf_pages: int = 2000
    max_text_chars: int = 5_000_000
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    block_chars: int = 900
    max_table_cells: int = 3_000_000
    ocr_enabled: bool = True
    ocr_languages: str = "rus+eng"
    ocr_max_pages: int = 100
    ocr_dpi: int = 200


@dataclass
class TextBlock:
    text: str
    location: str
    header: str = ""


@dataclass
class RawTable:
    name: str
    header: list[str]
    rows: list[list[str]]


@dataclass
class ParsedDocument:
    blocks: list[TextBlock]
    tables: list[RawTable] = field(default_factory=list)


def detect_kind(content: bytes, ext: str) -> str:
    """Decide the real format from the bytes (the extension is only a hint)."""
    head = content[:2048]
    if b"%PDF-" in head:
        return "pdf"
    if content[:8] == _OLE_MAGIC:
        return "xls"
    if content[:4] == b"PK\x03\x04":
        try:
            names = set(zipfile.ZipFile(io.BytesIO(content)).namelist())
        except zipfile.BadZipFile as exc:
            raise FileProcessingError(
                "The file is corrupted (invalid ZIP container)."
            ) from exc
        if "word/document.xml" in names:
            return "docx"
        if "xl/workbook.xml" in names:
            return "xlsx"
        raise FileProcessingError(
            "Unsupported Office file (expected .docx or .xlsx)."
        )
    if ext == ".csv" and (
        b"\x00" not in content[:4096]
        or content[:2] in (b"\xff\xfe", b"\xfe\xff")
    ):
        return "csv"
    raise FileProcessingError(
        "The file content does not look like a valid "
        f"{ext or 'supported'} document."
    )


def _check_zip(content: bytes, limits: Limits) -> None:
    try:
        infos = zipfile.ZipFile(io.BytesIO(content)).infolist()
    except zipfile.BadZipFile as exc:
        raise FileProcessingError(
            "The file is corrupted (invalid ZIP container)."
        ) from exc
    if (
        len(infos) > 10_000
        or sum(i.file_size for i in infos) > limits.max_uncompressed_bytes
    ):
        raise FileProcessingError(
            "The file expands to an unreasonable size and was rejected."
        )


class _Budget:
    def __init__(self, limit: int):
        self.left = limit

    def spend(self, n: int) -> None:
        self.left -= n
        if self.left < 0:
            raise FileProcessingError(
                "The document contains too much text to process."
            )


def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.datetime):
        return (
            value.date().isoformat()
            if value.time() == dt.time(0)
            else value.isoformat(sep=" ")
        )
    if isinstance(value, dt.date):
        return value.isoformat()
    return re.sub(r"\s+", " ", str(value)).strip()


def _materialize(
    rows: Iterable[tuple[int, list[str]]], budget: _Budget
) -> list[tuple[int, list[str]]]:
    out = []
    for row_no, cells in rows:
        if not any(cells):
            continue
        budget.spend(sum(len(c) for c in cells) + len(cells))
        out.append((row_no, cells))
    return out


def _rows_to_blocks(
    rows: list[tuple[int, list[str]]], sheet: str | None, limits: Limits
) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    if not rows:
        return blocks
    header_row, header_cells = rows[0]
    header = " | ".join(header_cells)
    prefix = f"[{sheet}] " if sheet else ""
    cur: list[str] = []
    first = last = 0
    size = 0

    def flush() -> None:
        nonlocal cur, size
        if cur:
            loc = (
                f"{prefix}rows {first}-{last}"
                if first != last
                else f"{prefix}row {first}"
            )
            blocks.append(TextBlock("\n".join(cur), loc.strip(), header))
        cur, size = [], 0

    for row_no, cells in rows[1:]:
        cells = list(cells) + [""] * (len(header_cells) - len(cells))
        line = " | ".join(cells)
        if cur and size + len(line) > limits.block_chars:
            flush()
        if not cur:
            first = row_no
        cur.append(line)
        last = row_no
        size += len(line) + 1
    flush()
    if not blocks:
        blocks.append(TextBlock(header, f"{prefix}row {header_row}".strip()))
    return blocks


def _unique_header(cells: list[str]) -> list[str]:
    out, seen = [], {}
    for i, c in enumerate(cells, start=1):
        name = c.strip() or f"col_{i}"
        seen[name] = seen.get(name, 0) + 1
        out.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return out


def _to_table(
    rows: list[tuple[int, list[str]]],
    name: str,
    limits: Limits,
    cells_used: list[int],
) -> RawTable | None:
    if len(rows) < 2:
        return None
    header = _unique_header(rows[0][1])
    n = len(header)
    if n > 200 or n == 0:
        return None
    cells = (len(rows) - 1) * n
    if (
        cells > limits.max_table_cells
        or cells_used[0] + cells > limits.max_table_cells
    ):
        return None
    cells_used[0] += cells
    body = [(r + [""] * (n - len(r)))[:n] for _, r in rows[1:]]
    return RawTable(name=name, header=header, rows=body)


def ocr_available(languages: str) -> tuple[bool, str]:
    """-> (usable, languages to use). Falls back to whichever requested
    packs are installed."""
    if shutil.which("tesseract") is None:
        return False, ""
    try:
        import pytesseract

        installed = set(pytesseract.get_languages(config=""))
    except Exception:
        return False, ""
    wanted = [lang for lang in languages.split("+") if lang in installed]
    return (True, "+".join(wanted)) if wanted else (False, "")


def _ocr_pages(
    content: bytes, pages: list[int], limits: Limits, progress: Progress | None
) -> dict[int, str]:
    ok, langs = ocr_available(limits.ocr_languages)
    if not ok:
        return {}
    import pypdfium2 as pdfium
    import pytesseract

    out: dict[int, str] = {}
    pdf = pdfium.PdfDocument(content)
    try:
        todo = pages[: limits.ocr_max_pages]
        for i, number in enumerate(todo, start=1):
            if progress:
                progress(i / len(todo), "ocr")
            try:
                image = (
                    pdf[number - 1].render(scale=limits.ocr_dpi / 72).to_pil()
                )
                text = pytesseract.image_to_string(
                    image, lang=langs, config="--psm 3", timeout=90
                )
            except Exception:
                continue
            if text.strip():
                out[number] = text
    finally:
        pdf.close()
    return out


def _garbled(text: str) -> bool:
    n = len(text)
    return n > 0 and (text.count("\ufffd") + text.count("(cid:") * 6) / n > 0.2


def _extract_pdf(
    content: bytes, limits: Limits, progress: Progress | None
) -> list[TextBlock]:
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError

    try:
        reader = PdfReader(io.BytesIO(content), strict=False)
        if reader.is_encrypted and not reader.decrypt(""):
            raise FileProcessingError("The PDF is password-protected.")
        total_pages = len(reader.pages)
    except FileProcessingError:
        raise
    except (PyPdfError, ValueError, KeyError, OSError, RecursionError) as exc:
        raise FileProcessingError(
            "The PDF is corrupted or unreadable."
        ) from exc
    if total_pages > limits.max_pdf_pages:
        raise FileProcessingError(
            f"The PDF has too many pages (limit {limits.max_pdf_pages})."
        )

    budget = _Budget(limits.max_text_chars)
    texts: dict[int, str] = {}
    needs_ocr: list[int] = []
    for number, page in enumerate(reader.pages, start=1):
        if progress and number % 25 == 0:
            progress(
                number / total_pages * (0.3 if limits.ocr_enabled else 1.0),
                "parsing",
            )
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        if len(text.strip()) < 20 or _garbled(text):
            needs_ocr.append(number)
            continue
        budget.spend(len(text))
        texts[number] = text

    ocr_used = False
    if needs_ocr and limits.ocr_enabled and len(texts) < 0.5 * total_pages:
        for number, text in _ocr_pages(
            content, needs_ocr, limits, progress
        ).items():
            budget.spend(len(text))
            texts[number] = text
            ocr_used = True
    if not texts:
        if (
            needs_ocr
            and limits.ocr_enabled
            and not ocr_available(limits.ocr_languages)[0]
        ):
            raise FileProcessingError(
                "This looks like a scanned PDF, but OCR (tesseract) is not "
                "installed on the server."
            )
        if needs_ocr:
            raise FileProcessingError(
                "No readable text found in the PDF "
                "(scanned or unrecognisable pages)."
            )
        raise FileProcessingError("No text found in the PDF.")
    ocr_pages = set(needs_ocr) if ocr_used else set()
    return [
        TextBlock(
            texts[n], f"page {n} (OCR)" if n in ocr_pages else f"page {n}"
        )
        for n in sorted(texts)
    ]


def _extract_docx(content: bytes, limits: Limits) -> list[TextBlock]:
    from docx import Document
    from docx.oxml.ns import qn
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    _check_zip(content, limits)
    try:
        doc = Document(io.BytesIO(content))
    except Exception as exc:
        raise FileProcessingError(
            "The Word document is corrupted or unreadable."
        ) from exc

    budget = _Budget(limits.max_text_chars)
    blocks: list[TextBlock] = []
    buf: list[str] = []
    start = para_no = 0
    heading = ""

    def flush() -> None:
        nonlocal buf
        if buf:
            where = f"paragraphs {start}-{para_no}"
            blocks.append(
                TextBlock(
                    "\n".join(buf),
                    f"{where} (section: {heading})" if heading else where,
                )
            )
        buf = []

    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            para = Paragraph(child, doc)
            text = para.text.strip()
            if not text:
                continue
            para_no += 1
            budget.spend(len(text))
            style = (para.style.name if para.style is not None else "") or ""
            heading_styles = ("heading", "заголовок", "title")
            if style.lower().startswith(heading_styles):
                flush()
                heading = text[:80]
            if not buf:
                start = para_no
            buf.append(text)
            if sum(len(x) for x in buf) > limits.block_chars:
                flush()
        elif child.tag == qn("w:tbl"):
            flush()
            table = Table(child, doc)
            rows: list[tuple[int, list[str]]] = []
            for idx, row in enumerate(table.rows, start=1):
                seen: set[int] = set()
                cells: list[str] = []
                for cell in row.cells:
                    if id(cell._tc) in seen:
                        continue
                    seen.add(id(cell._tc))
                    cells.append(cell.text.strip().replace("\n", " "))
                rows.append((idx, cells))
            for blk in _rows_to_blocks(
                _materialize(rows, budget), None, limits
            ):
                blk.location = f"table, {blk.location}" + (
                    f" (section: {heading})" if heading else ""
                )
                blocks.append(blk)
    flush()
    if not blocks:
        raise FileProcessingError("The Word document contains no text.")
    return blocks


def _extract_xlsx(
    content: bytes, limits: Limits
) -> tuple[list[TextBlock], list[RawTable]]:
    from openpyxl import load_workbook

    _check_zip(content, limits)
    budget = _Budget(limits.max_text_chars)
    blocks: list[TextBlock] = []
    tables: list[RawTable] = []
    used = [0]
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        for ws in wb.worksheets:
            if ws.sheet_state != "visible":
                continue
            rows = _materialize(
                (
                    (i, [_cell(v) for v in r])
                    for i, r in enumerate(
                        ws.iter_rows(values_only=True), start=1
                    )
                ),
                budget,
            )
            blocks += _rows_to_blocks(rows, ws.title, limits)
            table = _to_table(rows, ws.title, limits, used)
            if table:
                tables.append(table)
    except FileProcessingError:
        raise
    except Exception as exc:
        raise FileProcessingError(
            "The Excel file is corrupted or unreadable."
        ) from exc
    if not blocks:
        raise FileProcessingError("The spreadsheet contains no data.")
    return blocks, tables


def _extract_xls(
    content: bytes, limits: Limits
) -> tuple[list[TextBlock], list[RawTable]]:
    import xlrd

    budget = _Budget(limits.max_text_chars)
    blocks: list[TextBlock] = []
    tables: list[RawTable] = []
    used = [0]
    try:
        wb = xlrd.open_workbook(file_contents=content, on_demand=True)
        for sheet in wb.sheets():
            if sheet.visibility != 0:
                continue

            def rows(sh=sheet, book=wb) -> Iterator[tuple[int, list[str]]]:
                for r in range(sh.nrows):
                    cells = []
                    for c in range(sh.ncols):
                        cell = sh.cell(r, c)
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            try:
                                cells.append(
                                    _cell(
                                        xlrd.xldate.xldate_as_datetime(
                                            cell.value, book.datemode
                                        )
                                    )
                                )
                                continue
                            except Exception:
                                pass
                        cells.append(_cell(cell.value))
                    yield r + 1, cells

            mat = _materialize(rows(), budget)
            blocks += _rows_to_blocks(mat, sheet.name, limits)
            table = _to_table(mat, sheet.name, limits, used)
            if table:
                tables.append(table)
    except FileProcessingError:
        raise
    except Exception as exc:
        raise FileProcessingError(
            "The .xls file is corrupted or unreadable."
        ) from exc
    if not blocks:
        raise FileProcessingError("The spreadsheet contains no data.")
    return blocks, tables


def decode_text(content: bytes) -> str:
    """UTF-8 (with/without BOM) -> UTF-16 (BOM) -> detected (cp1251, cp866,
    koi8-r, ...)."""
    if content[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return content.decode("utf-16")
    try:
        return content.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    best = from_bytes(content[:2_000_000]).best()
    if best is not None:
        return content.decode(best.encoding, errors="replace")
    return content.decode("cp1251", errors="replace")


def _extract_csv(
    content: bytes, limits: Limits, name: str
) -> tuple[list[TextBlock], list[RawTable]]:
    text = decode_text(content)
    sample = text[:65536]
    try:
        delimiter = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","
    budget = _Budget(limits.max_text_chars)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    try:
        rows = _materialize(
            (
                (i, [re.sub(r"\s+", " ", c).strip() for c in r])
                for i, r in enumerate(reader, start=1)
            ),
            budget,
        )
    except csv.Error as exc:
        raise FileProcessingError("The CSV file is malformed.") from exc
    blocks = _rows_to_blocks(rows, None, limits)
    if not blocks:
        raise FileProcessingError("The CSV file contains no data.")
    table = _to_table(rows, name, limits, [0])
    return blocks, [table] if table else []


def extract_document(
    content: bytes,
    ext: str,
    limits: Limits | None = None,
    progress: Progress | None = None,
    name: str = "data",
) -> ParsedDocument:
    from .text_utils import (
        normalize_text,
    )

    limits = limits or Limits()
    kind = detect_kind(content, ext.lower())
    tables: list[RawTable] = []
    if kind == "pdf":
        blocks = _extract_pdf(content, limits, progress)
    elif kind == "docx":
        blocks = _extract_docx(content, limits)
    elif kind == "xlsx":
        blocks, tables = _extract_xlsx(content, limits)
    elif kind == "xls":
        blocks, tables = _extract_xls(content, limits)
    else:
        blocks, tables = _extract_csv(content, limits, name)
    out = []
    for b in blocks:
        text = normalize_text(b.text)
        if text:
            out.append(TextBlock(text, b.location, normalize_text(b.header)))
    if not out:
        raise FileProcessingError("No readable text found in the document.")
    return ParsedDocument(out, tables)


def extract_blocks(
    content: bytes, ext: str, limits: Limits | None = None
) -> list[TextBlock]:
    return extract_document(content, ext, limits).blocks
