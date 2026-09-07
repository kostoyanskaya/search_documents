from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from app.models.schemas import DocumentInfo, DocStatus

_lock = threading.Lock()
_documents: dict[str, dict[str, Any]] = {}  # doc_id -> record (includes session_id)


def file_hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:16]


def find_by_hash(session_id: str, content_hash: str) -> Optional[dict]:
    with _lock:
        for entry in _documents.values():
            if entry["session_id"] == session_id and entry["content_hash"] == content_hash:
                return entry
    return None


def register(
    session_id: str, doc_id: str, filename: str, file_type: str,
    size_bytes: int, content_hash: str,
) -> DocumentInfo:
    with _lock:
        entry = {
            "doc_id": doc_id,
            "session_id": session_id,
            "filename": filename,
            "file_type": file_type,
            "size_bytes": size_bytes,
            "status": DocStatus.QUEUED.value,
            "chunks": 0,
            "uploaded_at": datetime.now(timezone.utc).isoformat(),
            "content_hash": content_hash,
            "error": None,
        }
        _documents[doc_id] = entry
        return _to_info(entry)


def update_status(
    session_id: str, doc_id: str, status: DocStatus,
    chunks: int | None = None, error: str | None = None,
) -> None:
    with _lock:
        entry = _documents.get(doc_id)
        if not entry or entry["session_id"] != session_id:
            return
        entry["status"] = status.value
        if chunks is not None:
            entry["chunks"] = chunks
        if error is not None:
            entry["error"] = error


def remove(session_id: str, doc_id: str) -> None:
    with _lock:
        entry = _documents.get(doc_id)
        if entry and entry["session_id"] == session_id:
            _documents.pop(doc_id, None)


def remove_session(session_id: str) -> None:
    with _lock:
        for doc_id in [k for k, v in _documents.items() if v["session_id"] == session_id]:
            _documents.pop(doc_id, None)


def list_documents(session_id: str) -> list[DocumentInfo]:
    with _lock:
        items = [_to_info(e) for e in _documents.values() if e["session_id"] == session_id]
    return sorted(items, key=lambda d: d.uploaded_at, reverse=True)


def get(session_id: str, doc_id: str) -> Optional[DocumentInfo]:
    with _lock:
        entry = _documents.get(doc_id)
    if not entry or entry["session_id"] != session_id:
        return None
    return _to_info(entry)


def _to_info(entry: dict) -> DocumentInfo:
    return DocumentInfo(**{k: v for k, v in entry.items() if k != "session_id"})
