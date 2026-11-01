import hashlib
import logging
import os
import re
import threading

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.concurrency import run_in_threadpool

from app.core import session as sessions
from app.core.config import get_settings
from app.core.observability import DOCS_PROCESSED
from app.models.schemas import DocStatus, DocumentInfo, UploadResponse
from app.routers.deps import ensure_session, get_session_id
from app.services import document_registry as registry
from app.services import table_store, vector_store
from app.services.file_processing import (
    ALLOWED_EXTENSIONS,
    FileProcessingError,
    detect_kind,
)
from app.services.parsing import parse_document

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["documents"])

_sem: threading.BoundedSemaphore | None = None
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def _semaphore() -> threading.BoundedSemaphore:
    global _sem
    if _sem is None:
        _sem = threading.BoundedSemaphore(
            get_settings().max_parallel_processing
        )
    return _sem


def _clean_filename(name: str) -> str:
    name = _CTRL.sub("", name or "").replace("\\", "/").split("/")[-1].strip()
    return name[:200] or "document"


def _inspect(content: bytes, ext: str) -> tuple[str, str]:
    kind = detect_kind(content, ext)
    return kind, hashlib.sha256(content).hexdigest()


def _discard(session_id: str, doc_id: str) -> None:
    vector_store.delete_document(session_id, doc_id)
    table_store.remove_document(session_id, doc_id)
    if not sessions.exists(session_id):
        vector_store.delete_session(session_id)
        table_store.remove_session(session_id)


def _process_document(
    session_id: str, doc_id: str, ext: str, content: bytes
) -> None:
    doc = registry.get(session_id, doc_id)
    if doc is None:
        return

    def progress(pct: int, stage: str) -> None:
        registry.update_status(
            session_id, doc_id, DocStatus.PROCESSING, progress=pct, stage=stage
        )

    with _semaphore():
        if registry.get(session_id, doc_id) is None:
            return
        progress(2, "parsing")
        try:
            parsed = parse_document(
                content,
                ext,
                name=os.path.splitext(doc.filename)[0],
                on_progress=lambda frac, stage: progress(
                    2 + int(frac * 38), stage
                ),
            )
            progress(40, "indexing")
            count = vector_store.index_document(
                session_id,
                doc_id,
                doc.filename,
                parsed.blocks,
                on_progress=lambda f: progress(40 + int(f * 58), "indexing"),
            )
            if parsed.tables:
                table_store.add_tables(
                    session_id, doc_id, doc.filename, parsed.tables
                )
            if registry.get(session_id, doc_id) is None:
                _discard(session_id, doc_id)
                return
            registry.update_status(
                session_id, doc_id, DocStatus.READY, chunks=count
            )
            DOCS_PROCESSED.labels("ready").inc()
        except FileProcessingError as exc:
            registry.update_status(
                session_id, doc_id, DocStatus.FAILED, error=str(exc), stage=""
            )
            DOCS_PROCESSED.labels("failed").inc()
        except Exception:
            logger.exception(
                "processing failed (session=%s doc=%s)",
                sessions.sid_hash(session_id),
                doc_id,
            )
            registry.update_status(
                session_id,
                doc_id,
                DocStatus.FAILED,
                error="Internal processing error.",
                stage="",
            )
            DOCS_PROCESSED.labels("error").inc()


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    request: Request,
    background: BackgroundTasks,
    files: list[UploadFile] = File(...),
):
    s = get_settings()
    if not files:
        raise HTTPException(400, "No files provided.")
    if len(files) > s.max_files_per_upload:
        raise HTTPException(
            400, f"Too many files (limit {s.max_files_per_upload} per upload)."
        )

    prepared: list[dict] = []
    for f in files:
        name = _clean_filename(f.filename or "")
        ext = os.path.splitext(name)[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(
                400, f"Unsupported format '{ext or name}': {name}"
            )
        content = await f.read(s.max_upload_mb * 1024 * 1024 + 1)
        if len(content) > s.max_upload_mb * 1024 * 1024:
            raise HTTPException(
                413, f"File is too large (limit {s.max_upload_mb} MB): {name}"
            )
        if not content:
            raise HTTPException(400, f"File is empty: {name}")
        try:
            kind, digest = await run_in_threadpool(_inspect, content, ext)
        except FileProcessingError as exc:
            raise HTTPException(400, f"{name}: {exc}") from exc
        prepared.append(
            {
                "filename": name,
                "file_type": kind,
                "size": len(content),
                "hash": digest,
                "ext": ext,
                "content": content,
            }
        )

    if (
        registry.inflight_bytes() + sum(p["size"] for p in prepared)
        > s.max_inflight_upload_mb * 1024 * 1024
    ):
        raise HTTPException(
            503,
            "The server is processing a lot of files right now. "
            "Try again in a minute.",
        )

    session_id = ensure_session(request)
    try:
        accepted, skipped = registry.register_batch(
            session_id,
            prepared,
            s.max_docs_per_session,
            s.max_session_total_mb * 1024 * 1024,
        )
    except registry.QuotaExceeded as exc:
        raise HTTPException(413, str(exc)) from exc
    for info, item in accepted:
        background.add_task(
            _process_document,
            session_id,
            info.doc_id,
            item["ext"],
            item["content"],
        )
    return UploadResponse(
        accepted=[i for i, _ in accepted], skipped_duplicates=skipped
    )


@router.get("", response_model=list[DocumentInfo])
def list_documents(session_id: str = Depends(get_session_id)):
    return registry.list_documents(session_id)


@router.delete("/{doc_id}")
def delete_document(doc_id: str, session_id: str = Depends(get_session_id)):
    if not registry.remove(session_id, doc_id):
        raise HTTPException(404, "Document not found.")
    vector_store.delete_document(session_id, doc_id)
    table_store.remove_document(session_id, doc_id)
    return {"ok": True}
