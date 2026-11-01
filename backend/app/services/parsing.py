from __future__ import annotations

import logging
import multiprocessing as mp
import time
from collections.abc import Callable

from app.core.config import get_settings

from .file_processing import (
    FileProcessingError,
    Limits,
    ParsedDocument,
    extract_document,
)

logger = logging.getLogger(__name__)


def _worker(
    conn, content: bytes, ext: str, limits: Limits, memory_mb: int, name: str
) -> None:
    try:
        try:
            import resource

            cap = memory_mb * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
        except (ImportError, ValueError, OSError):
            pass

        def progress(fraction: float, stage: str) -> None:
            conn.send(("progress", (fraction, stage)))

        conn.send(
            ("ok", extract_document(content, ext, limits, progress, name))
        )
    except FileProcessingError as exc:
        conn.send(("err", str(exc)))
    except MemoryError:
        conn.send(("err", "The document is too large to process."))
    except Exception:
        conn.send(
            (
                "err",
                "The document could not be processed "
                "(unsupported or corrupted content).",
            )
        )
    finally:
        conn.close()


def _limits() -> Limits:
    s = get_settings()
    return Limits(
        max_pdf_pages=s.max_pdf_pages,
        max_text_chars=s.max_text_chars_per_doc,
        max_uncompressed_bytes=s.max_uncompressed_mb * 1024 * 1024,
        block_chars=s.chunk_size,
        max_table_cells=s.max_table_cells_per_doc,
        ocr_enabled=s.ocr_enabled,
        ocr_languages=s.ocr_languages,
        ocr_max_pages=s.ocr_max_pages,
        ocr_dpi=s.ocr_dpi,
    )


def parse_document(
    content: bytes,
    ext: str,
    name: str = "data",
    on_progress: Callable[[float, str], None] | None = None,
) -> ParsedDocument:
    s = get_settings()
    limits = _limits()
    if not s.parse_in_subprocess:
        return extract_document(content, ext, limits, on_progress, name)

    timeout = (
        s.ocr_timeout_s
        if (ext == ".pdf" and s.ocr_enabled)
        else s.parse_timeout_s
    )
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    proc = ctx.Process(
        target=_worker,
        args=(child, content, ext, limits, s.parse_memory_mb, name),
        daemon=True,
    )
    proc.start()
    child.close()
    deadline = time.monotonic() + timeout
    try:
        while True:
            if not parent.poll(max(0.0, deadline - time.monotonic())):
                raise FileProcessingError(
                    "Processing took too long and was cancelled."
                )
            try:
                status, payload = parent.recv()
            except (EOFError, OSError) as exc:
                raise FileProcessingError(
                    "The document could not be processed "
                    "(it may be too large or corrupted)."
                ) from exc
            if status == "progress":
                if on_progress:
                    on_progress(*payload)
                continue
            break
    finally:
        parent.close()
        if proc.is_alive():
            proc.terminate()
        proc.join(5)
    if status == "err":
        raise FileProcessingError(payload)
    return payload
