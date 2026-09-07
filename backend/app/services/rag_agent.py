from __future__ import annotations

import json
import logging
import time
from typing import Any, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from app.core.config import get_settings
from app.models.schemas import QueryResponse, SourceHit
from app.services import vector_store
from app.services.llm import get_llm

logger = logging.getLogger(__name__)

RELEVANCE_FLOOR = 0.12  # chunks below this similarity are treated as noise

SYSTEM_PROMPT = (
    "You are an AI agent that answers questions using documents uploaded by "
    "the user (Word, PDF, CSV, Excel). You're given a question and a set of "
    "text chunks, each tagged [Document: <doc_id> | <filename> | <location>].\n\n"
    "Rules:\n"
    "1. Answer ONLY based on the provided chunks. Never make anything up.\n"
    "2. Answer concisely and to the point, in English.\n"
    "3. Only use chunks that ACTUALLY answer the question. If a chunk is only "
    "topically related but doesn't answer it, don't use it.\n"
    "4. Respond STRICTLY as JSON, with no markdown or extra text around it:\n"
    '{"answer": "...", "found": true/false, "used_doc_ids": ["id1", "id2"]}\n'
    "If no chunk answers the question, set found=false, used_doc_ids=[], and "
    "have answer explain that the information wasn't found."
)


class AgentState(TypedDict, total=False):
    session_id: str
    question: str
    top_k: int
    hits: list[dict[str, Any]]
    answer: str
    found: bool
    sources: list[SourceHit]


def _retrieve_node(state: AgentState) -> AgentState:
    hits = vector_store.search(state["session_id"], state["question"], top_k=state["top_k"])
    hits = [h for h in hits if h["relevance"] >= RELEVANCE_FLOOR]
    return {"hits": hits}


def _generate_node(state: AgentState) -> AgentState:
    hits = state.get("hits", [])
    if not hits:
        return {
            "answer": "No relevant information was found in the uploaded documents for this question.",
            "found": False,
            "sources": [],
        }

    context = "\n\n".join(
        f"[Document: {h['doc_id']} | {h['filename']} | {h['location']}]\n{h['text']}"
        for h in hits
    )

    llm = get_llm()
    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=f"Question: {state['question']}\n\nDocument chunks:\n\n{context}"),
    ]
    response = llm.invoke(messages)
    raw = response.content.strip()
    # in case the model wraps the JSON in ```json ... ```
    raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(raw)
        answer = parsed.get("answer", "")
        found = bool(parsed.get("found", False))
        used_ids = set(parsed.get("used_doc_ids", []))
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON output, falling back to raw text")
        answer, found, used_ids = raw, True, {h["doc_id"] for h in hits}

    sources: list[SourceHit] = []
    if found and used_ids:
        seen_docs: set[str] = set()
        for h in sorted(hits, key=lambda x: x["relevance"], reverse=True):
            if h["doc_id"] not in used_ids or h["doc_id"] in seen_docs:
                continue
            seen_docs.add(h["doc_id"])
            sources.append(SourceHit(
                doc_id=h["doc_id"],
                filename=h["filename"],
                excerpt=(h["text"][:280] + "…") if len(h["text"]) > 280 else h["text"],
                relevance=h["relevance"],
            ))

    return {"answer": answer, "found": found, "sources": sources}


def _build_graph():
    graph = StateGraph(AgentState)
    graph.add_node("retrieve", _retrieve_node)
    graph.add_node("generate", _generate_node)
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    return graph.compile()


_agent = _build_graph()


def answer_question(session_id: str, question: str, top_k: int | None = None) -> QueryResponse:
    settings = get_settings()
    start = time.perf_counter()

    result = _agent.invoke({
        "session_id": session_id,
        "question": question,
        "top_k": top_k or settings.retrieval_top_k,
    })

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    return QueryResponse(
        answer=result["answer"],
        sources=result["sources"],
        found=result["found"],
        elapsed_ms=elapsed_ms,
    )
