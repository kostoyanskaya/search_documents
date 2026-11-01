import json
import logging
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.core.config import get_settings
from app.models.schemas import QueryRequest, QueryResponse
from app.routers.deps import get_session_id
from app.services import llm
from app.services.agent import run_agent, stream_agent
from app.services.text_utils import normalize_text

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["query"])

_BUSY = (429, "The AI service is busy. Please try again shortly.")
_DOWN = (503, "The AI service is temporarily unavailable. Please try again.")


def _history(body: QueryRequest) -> list[dict]:
    turns = []
    limit = get_settings().max_history_turns
    for t in body.history[-limit:]:
        q, a = normalize_text(t.question), normalize_text(t.answer)
        if q and a:
            turns.append({"question": q, "answer": a})
    return turns


@router.post("/query", response_model=QueryResponse)
def query(body: QueryRequest, session_id: str = Depends(get_session_id)):
    try:
        return run_agent(session_id, body.question, _history(body), body.top_k)
    except llm.LLMBudgetExceeded:
        raise HTTPException(*_BUSY) from None
    except llm.LLMUnavailable:
        raise HTTPException(*_DOWN) from None


def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/query/stream")
def query_stream(
    body: QueryRequest, session_id: str = Depends(get_session_id)
):
    history = _history(body)

    def events() -> Iterator[str]:
        try:
            for kind, payload in stream_agent(
                session_id, body.question, history, body.top_k
            ):
                yield _sse(
                    kind,
                    payload
                    if kind == "step"
                    else json.loads(payload.model_dump_json()),
                )
        except llm.LLMBudgetExceeded:
            yield _sse("error", {"status": _BUSY[0], "message": _BUSY[1]})
        except llm.LLMUnavailable:
            yield _sse("error", {"status": _DOWN[0], "message": _DOWN[1]})
        except Exception:
            logger.exception("agent failed")
            yield _sse("error", {"status": 500, "message": "Internal error."})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
