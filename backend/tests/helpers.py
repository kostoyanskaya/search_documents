import hashlib
import os
from pathlib import Path

import pytest

from app.models.schemas import DocStatus
from app.services import document_registry as registry
from app.services import table_store, vector_store
from app.services.file_processing import extract_document


def load_doc(sid: str, name: str, content: bytes) -> str:
    ext = os.path.splitext(name)[1]
    parsed = extract_document(content, ext, name=os.path.splitext(name)[0])
    item = {
        "filename": name,
        "file_type": ext[1:],
        "size": len(content),
        "hash": hashlib.sha256(content).hexdigest(),
    }
    accepted, _ = registry.register_batch(sid, [item], 100, 10**10)
    doc_id = accepted[0][0].doc_id
    n = vector_store.index_document(sid, doc_id, name, parsed.blocks)
    table_store.add_tables(sid, doc_id, name, parsed.tables)
    registry.update_status(sid, doc_id, DocStatus.READY, chunks=n)
    return doc_id


def cite(label="S1", quote="x", answer="ok"):
    return {
        "answer": answer,
        "found": True,
        "sources": [{"id": label, "quote": quote}],
    }


def nodes(resp):
    return [s.node for s in resp.steps]


SALES_CSV = (
    "Город,Дата,Выручка\n"
    'Москва,2023-01-15,"1 250 000,50"\n'
    'Казань,15.02.2023,"980 000,00"\n'
    'Москва,01.03.2023,"(5 000,25)"\n'
).encode()


_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/tahoma.ttf",
)


def cyrillic_font_path() -> str:
    """Path to a TrueType font with Cyrillic glyphs on this machine.

    Skips the calling test when the system has none, instead of failing
    on a Linux-only hard-coded path.
    """
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    pytest.skip("no TrueType font with Cyrillic glyphs found")
