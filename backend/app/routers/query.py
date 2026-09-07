from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool

from app.core.session import get_session_id
from app.models.schemas import QueryRequest, QueryResponse
from app.services import document_registry as registry
from app.services.rag_agent import answer_question

router = APIRouter(prefix="/api", tags=["query"])


@router.post("/query", response_model=QueryResponse)
async def query(request: QueryRequest, session_id: str = Depends(get_session_id)) -> QueryResponse:
    ready_docs = [d for d in registry.list_documents(session_id) if d.status == "ready"]
    if not ready_docs:
        raise HTTPException(
            400,
            "No indexed documents yet. Upload some files and wait for processing to finish.",
        )

    # answer_question makes a blocking HTTP call to the LLM and a synchronous
    # Chroma search — run it in a thread pool so it doesn't freeze the event
    # loop for every other user.
    return await run_in_threadpool(answer_question, session_id, request.question, request.top_k)
