from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd
from docx import Document as DocxDocument
from pypdf import PdfReader

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".csv", ".xlsx", ".xls"}


@dataclass
class TextBlock:
    text: str
    location: str  # human-readable location: "page 3", "rows 12-36", "sheet 'Sales'"


class UnsupportedFileType(Exception):
    pass


def extract_blocks(content: bytes, ext: str) -> list[TextBlock]:
    """Extracts text straight from in-memory bytes — the file is never written to disk."""
    ext = ext.lower()

    if ext == ".pdf":
        return _extract_pdf(io.BytesIO(content))
    if ext == ".docx":
        return _extract_docx(io.BytesIO(content))
    if ext == ".csv":
        return _extract_csv(io.BytesIO(content))
    if ext in (".xlsx", ".xls"):
        return _extract_excel(io.BytesIO(content))

    raise UnsupportedFileType(f"Unsupported format: {ext}")


def _extract_pdf(buf: io.BytesIO) -> list[TextBlock]:
    reader = PdfReader(buf)
    blocks: list[TextBlock] = []
    for i, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(TextBlock(text=text, location=f"page {i}"))
    return blocks


def _extract_docx(buf: io.BytesIO) -> list[TextBlock]:
    doc = DocxDocument(buf)
    blocks: list[TextBlock] = []

    # Group paragraphs into batches so we don't produce a flood of micro-chunks
    buffer: list[str] = []
    para_start = 1

    def flush(end_idx: int):
        if buffer:
            blocks.append(TextBlock(text="\n".join(buffer), location=f"paragraphs {para_start}-{end_idx}"))

    for idx, para in enumerate(doc.paragraphs, start=1):
        if para.text.strip():
            if not buffer:
                para_start = idx
            buffer.append(para.text.strip())
        if len("\n".join(buffer)) > 800:
            flush(idx)
            buffer = []
    flush(len(doc.paragraphs))

    # Tables get their own blocks
    for t_idx, table in enumerate(doc.tables, start=1):
        rows_text = []
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells]
            if any(cells):
                rows_text.append(" | ".join(cells))
        if rows_text:
            blocks.append(TextBlock(text="\n".join(rows_text), location=f"table {t_idx}"))

    return blocks


def _extract_csv(buf: io.BytesIO) -> list[TextBlock]:
    df = pd.read_csv(buf, dtype=str, keep_default_na=False, on_bad_lines="skip")
    return _dataframe_to_blocks(df, sheet_name=None)


def _extract_excel(buf: io.BytesIO) -> list[TextBlock]:
    sheets = pd.read_excel(buf, sheet_name=None, dtype=str, engine="openpyxl")
    blocks: list[TextBlock] = []
    for sheet_name, df in sheets.items():
        blocks.extend(_dataframe_to_blocks(df.fillna(""), sheet_name=sheet_name))
    return blocks


def _dataframe_to_blocks(df: pd.DataFrame, sheet_name: str | None, rows_per_block: int = 25) -> list[TextBlock]:
    if df.empty:
        return []
    header = " | ".join(str(c) for c in df.columns)
    blocks: list[TextBlock] = []

    for start in range(0, len(df), rows_per_block):
        chunk_df = df.iloc[start: start + rows_per_block]
        lines = [header] + [" | ".join(str(v) for v in row.values) for _, row in chunk_df.iterrows()]
        loc = f"rows {start + 2}-{start + 1 + len(chunk_df)}"
        if sheet_name:
            loc = f"sheet '{sheet_name}', {loc}"
        blocks.append(TextBlock(text="\n".join(lines), location=loc))

    return blocks
