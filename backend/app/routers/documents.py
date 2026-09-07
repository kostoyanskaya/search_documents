import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.session import get_session_id
from app.models.schemas import DocStatus, DocumentInfo, UploadResponse
from app.services import document_registry as registry
from app.services import vector_store
from app.services.file_processing import SUPPORTED_EXTENSIONS, extract_blocks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])


def _process_document(session_id: str, doc_id: str, content: bytes, ext: str) -> None:
    registry.update_status(session_id, doc_id, DocStatus.PROCESSING)
    try:
        blocks = extract_blocks(content, ext)
        if not blocks:
            registry.update_status(
                session_id, doc_id, DocStatus.FAILED, error="Could not extract any text from the file"
            )
            return
        doc = registry.get(session_id, doc_id)
        chunks = vector_store.index_document(session_id, doc_id, doc.filename, blocks)
        registry.update_status(session_id, doc_id, DocStatus.READY, chunks=chunks)
    except Exception:
        logger.exception("Failed to process document %s (session %s)", doc_id, session_id)
        registry.update_status(session_id, doc_id, DocStatus.FAILED, error="Internal processing error")


async def _read_with_limit(file: UploadFile, max_bytes: int) -> bytes:
    """Reads the upload in chunks and aborts as soon as the size limit is
    exceeded, instead of buffering an arbitrarily large file into memory
    first and only checking its size afterwards."""
    chunk_size = 1024 * 1024
    data = bytearray()
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(
                400, f"{file.filename} exceeds the {max_bytes // (1024 * 1024)} MB limit"
            )
    return bytes(data)


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    session_id: str = Depends(get_session_id),
) -> UploadResponse:
    settings = get_settings()

    if len(files) > settings.max_files_per_upload:
        raise HTTPException(
            400, f"Too many files in one request (max {settings.max_files_per_upload})"
        )

    accepted: list[DocumentInfo] = []
    skipped: list[str] = []
    max_bytes = settings.max_upload_mb * 1024 * 1024

    for file in files:
        ext = Path(file.filename or "").suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported format '{ext}': {file.filename}")

        content = await _read_with_limit(file, max_bytes)

        content_hash = registry.file_hash(content)
        if registry.find_by_hash(session_id, content_hash):
            skipped.append(file.filename or content_hash)
            continue

        doc_id = uuid.uuid4().hex[:12]
        info = registry.register(
            session_id=session_id, doc_id=doc_id,
            filename=file.filename or f"{doc_id}{ext}",
            file_type=ext.lstrip("."), size_bytes=len(content),
            content_hash=content_hash,
        )
        accepted.append(info)
        # not a single byte of the file ever touches disk
        background_tasks.add_task(_process_document, session_id, doc_id, content, ext)

    return UploadResponse(accepted=accepted, skipped_duplicates=skipped)


@router.get("", response_model=list[DocumentInfo])
async def list_documents(session_id: str = Depends(get_session_id)) -> list[DocumentInfo]:
    return registry.list_documents(session_id)


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, session_id: str = Depends(get_session_id)) -> dict:
    doc = registry.get(session_id, doc_id)
    if not doc:
        raise HTTPException(404, "Document not found")

    vector_store.delete_document(session_id, doc_id)
    registry.remove(session_id, doc_id)
    return {"ok": True}
