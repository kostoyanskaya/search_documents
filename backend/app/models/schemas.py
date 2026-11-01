from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints


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
    progress: int = 0
    stage: str = ""
    uploaded_at: datetime
    error: Optional[str] = None


class UploadResponse(BaseModel):
    accepted: list[DocumentInfo]
    skipped_duplicates: list[str] = Field(default_factory=list)


class HistoryTurn(BaseModel):
    question: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=1000)
    ]
    answer: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=1500)
    ]


class QueryRequest(BaseModel):
    question: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=2, max_length=2000
        ),
    ]
    top_k: Optional[int] = Field(default=None, ge=1, le=20)
    history: list[HistoryTurn] = Field(default_factory=list, max_length=6)


class SourceHit(BaseModel):
    doc_id: str
    filename: str
    location: str
    excerpt: str
    relevance: float
    quote_verified: bool = False
    kind: Literal["text", "table"] = "text"


class StepInfo(BaseModel):
    node: str
    ms: int
    info: str = ""


class Calculation(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool = False


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceHit]
    found: bool
    language: str
    elapsed_ms: int
    route: str = "text"
    steps: list[StepInfo] = Field(default_factory=list)
    rewritten_query: Optional[str] = None
    calculation: Optional[Calculation] = None
