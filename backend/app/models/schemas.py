from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class DocStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class DocumentInfo(BaseModel):
    doc_id: str
    filename: str
    file_type: str
    size_bytes: int
    status: DocStatus
    chunks: int = 0
    uploaded_at: datetime
    error: Optional[str] = None


class UploadResponse(BaseModel):
    accepted: list[DocumentInfo]
    skipped_duplicates: list[str] = Field(default_factory=list)


class QueryRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    top_k: Optional[int] = Field(default=None, ge=1, le=50)


class SourceHit(BaseModel):
    doc_id: str
    filename: str
    excerpt: str
    relevance: float


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceHit]
    found: bool
    elapsed_ms: int
