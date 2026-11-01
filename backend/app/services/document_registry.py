from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.models.schemas import DocStatus, DocumentInfo


class QuotaExceeded(Exception):
    pass


@dataclass
class _Entry:
    info: DocumentInfo
    content_hash: str


_lock = threading.RLock()
_docs: dict[str, dict[str, _Entry]] = {}


def register_batch(
    session_id: str, items: list[dict], max_docs: int, max_bytes: int
) -> tuple[list[tuple[DocumentInfo, dict]], list[str]]:
    """All-or-nothing: checks quotas for the whole batch, then registers it.
    items: {filename, file_type, size, hash}.
    Returns (accepted, skipped_duplicate_names)."""
    with _lock:
        existing = _docs.setdefault(session_id, {})
        known = {e.content_hash for e in existing.values()}
        fresh, skipped = [], []
        for it in items:
            if it["hash"] in known:
                skipped.append(it["filename"])
                continue
            known.add(it["hash"])
            fresh.append(it)
        if len(existing) + len(fresh) > max_docs:
            raise QuotaExceeded(
                f"Document limit per session reached ({max_docs})."
            )
        used = sum(e.info.size_bytes for e in existing.values())
        if used + sum(i["size"] for i in fresh) > max_bytes:
            raise QuotaExceeded(
                "Total upload size limit for this session reached."
            )
        accepted = []
        for it in fresh:
            info = DocumentInfo(
                doc_id=uuid.uuid4().hex,
                filename=it["filename"],
                file_type=it["file_type"],
                size_bytes=it["size"],
                status=DocStatus.QUEUED,
                uploaded_at=datetime.now(UTC),
            )
            existing[info.doc_id] = _Entry(info, it["hash"])
            accepted.append((info.model_copy(), it))
        return accepted, skipped


def get(session_id: str, doc_id: str) -> DocumentInfo | None:
    with _lock:
        e = _docs.get(session_id, {}).get(doc_id)
        return e.info.model_copy() if e else None


def list_documents(session_id: str) -> list[DocumentInfo]:
    with _lock:
        return sorted(
            (e.info.model_copy() for e in _docs.get(session_id, {}).values()),
            key=lambda d: d.uploaded_at,
        )


def update_status(
    session_id: str,
    doc_id: str,
    status: DocStatus,
    chunks: int | None = None,
    error: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
) -> None:
    with _lock:
        e = _docs.get(session_id, {}).get(doc_id)
        if not e:
            return
        e.info.status = status
        if chunks is not None:
            e.info.chunks = chunks
        if error is not None:
            e.info.error = error
        if progress is not None:
            e.info.progress = max(0, min(100, progress))
        if stage is not None:
            e.info.stage = stage
        if status == DocStatus.READY:
            e.info.progress, e.info.stage = 100, "done"


def remove(session_id: str, doc_id: str) -> bool:
    with _lock:
        return _docs.get(session_id, {}).pop(doc_id, None) is not None


def remove_session(session_id: str) -> None:
    with _lock:
        _docs.pop(session_id, None)


def ready_doc_ids(session_id: str) -> set[str]:
    with _lock:
        return {
            i
            for i, e in _docs.get(session_id, {}).items()
            if e.info.status == DocStatus.READY
        }


def inflight_bytes() -> int:
    with _lock:
        return sum(
            e.info.size_bytes
            for docs in _docs.values()
            for e in docs.values()
            if e.info.status in (DocStatus.QUEUED, DocStatus.PROCESSING)
        )
