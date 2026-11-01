"""The agent as a LangGraph state machine.

Why a graph (and not a straight pipeline)? The control flow genuinely
branches and loops:
  * routing      - aggregate questions over spreadsheets go to a SQL
                   branch, the rest to document RAG;
  * conditional  - a rewrite/translation step runs only for follow-ups or
                   cross-language corpora;
  * cycles       - retrieval is graded and retried with reformulated
                   queries (corrective RAG), SQL errors are fed back to
                   the model for repair, answers without valid citations
                   trigger a retry;
  * fallbacks    - SQL -> text search when no usable result, text -> SQL
                   when nothing relevant is found.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.core.observability import AGENT_ROUTES
from app.models.schemas import Calculation, QueryResponse, StepInfo

from . import nodes as N
from .state import AgentState


@lru_cache
def build_graph():
    g = StateGraph(AgentState)
    for name, fn in [
        ("analyze", N.analyze),
        ("rewrite", N.rewrite),
        ("retrieve", N.retrieve),
        ("rerank", N.rerank),
        ("reformulate", N.reformulate),
        ("generate", N.generate),
        ("verify", N.verify),
        ("sql_plan", N.sql_plan),
        ("sql_exec", N.sql_exec),
        ("sql_answer", N.sql_answer),
        ("sql_fallback", N.sql_fallback),
        ("no_docs", N.no_docs),
        ("not_found", N.not_found),
    ]:
        g.add_node(name, fn)

    g.add_edge(START, "analyze")
    g.add_conditional_edges(
        "analyze",
        N.route_after_analyze,
        {
            "no_docs": "no_docs",
            "sql_plan": "sql_plan",
            "rewrite": "rewrite",
            "retrieve": "retrieve",
        },
    )
    g.add_edge("rewrite", "retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_conditional_edges(
        "rerank",
        N.route_after_rerank,
        {
            "generate": "generate",
            "reformulate": "reformulate",
            "sql_plan": "sql_plan",
            "not_found": "not_found",
        },
    )
    g.add_edge("reformulate", "retrieve")
    g.add_edge("generate", "verify")
    g.add_conditional_edges(
        "verify",
        N.route_after_verify,
        {"done": END, "reformulate": "reformulate", "not_found": "not_found"},
    )

    g.add_edge("sql_plan", "sql_exec")
    g.add_conditional_edges(
        "sql_exec",
        N.route_after_sql_exec,
        {
            "sql_answer": "sql_answer",
            "sql_plan": "sql_plan",
            "text_fallback": "sql_fallback",
        },
    )
    g.add_edge("sql_fallback", "retrieve")
    g.add_edge("sql_answer", END)
    g.add_edge("no_docs", END)
    g.add_edge("not_found", END)
    return g.compile()


def _initial(
    session_id: str,
    question: str,
    history: list[dict] | None,
    top_k: int | None,
) -> AgentState:
    return {
        "session_id": session_id,
        "question": question,
        "history": history or [],
        "top_k": top_k or 0,
        "steps": [],
    }


def _response(state: AgentState, started: float) -> QueryResponse:
    result = state.get("result") or {}
    calc = result.get("calculation")
    route = (
        "none" if state.get("route") == "none" else ("sql" if calc else "text")
    )
    outcome = "found" if result.get("found") else "not_found"
    AGENT_ROUTES.labels(route, outcome).inc()
    return QueryResponse(
        answer=(result.get("answer") or "")[:4000],
        sources=result.get("sources", []),
        found=bool(result.get("found")),
        language=state.get("lang", "en"),
        elapsed_ms=int((time.monotonic() - started) * 1000),
        route=route,
        steps=[StepInfo(**s) for s in state.get("steps", [])],
        rewritten_query=state.get("standalone")
        if state.get("standalone") != state.get("question")
        else None,
        calculation=Calculation(**calc) if calc else None,
    )


def run_agent(
    session_id: str,
    question: str,
    history: list[dict] | None = None,
    top_k: int | None = None,
) -> QueryResponse:
    started = time.monotonic()
    final = build_graph().invoke(
        _initial(session_id, question, history, top_k), {"recursion_limit": 60}
    )
    return _response(final, started)


def stream_agent(
    session_id: str,
    question: str,
    history: list[dict] | None = None,
    top_k: int | None = None,
) -> Iterator[tuple[str, object]]:
    """Yields ("step", {node, ms, info}) as each node finishes, then
    ("result", QueryResponse)."""
    started = time.monotonic()
    final: AgentState = {}
    for mode, chunk in build_graph().stream(
        _initial(session_id, question, history, top_k),
        {"recursion_limit": 60},
        stream_mode=["updates", "values"],
    ):
        if mode == "updates":
            for _node, update in chunk.items():
                for step in (update or {}).get("steps", []):
                    yield "step", step
        else:
            final = chunk
    yield "result", _response(final, started)
