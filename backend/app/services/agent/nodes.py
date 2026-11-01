"""LangGraph nodes.

Each node is a small pure-ish step returning a partial state update.
"""

from __future__ import annotations

import functools
import logging
import re
import secrets

from pydantic import BaseModel, ValidationError, field_validator

from app.core.config import get_settings
from app.core.observability import NODE_SECONDS, Timer
from app.models.schemas import SourceHit
from app.services import document_registry as registry
from app.services import embeddings, llm, table_store, vector_store
from app.services.text_utils import (
    clean_for_prompt,
    collapse_for_match,
    detect_language,
    looks_like_injection,
    normalize_text,
)

from . import prompts as P
from .state import AgentState
from .utils import AGGREGATE_RE, data_block, parse_json_object, unique_nonempty

logger = logging.getLogger(__name__)


def traced(name: str):
    """Time the node, publish the latency metric and record a
    human-readable step."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(state: AgentState) -> dict:
            with Timer() as t:
                update = fn(state)
            info = update.pop("_info", "")
            NODE_SECONDS.labels(name).observe(t.seconds)
            update["steps"] = [
                {"node": name, "ms": int(t.seconds * 1000), "info": info}
            ]
            return update

        return wrapper

    return deco


def _json_call(system: str, user: str, max_tokens: int = 400) -> dict | None:
    """Helper calls (rewrite/reformulate) degrade gracefully: the pipeline
    still works without them."""
    try:
        return parse_json_object(
            llm.complete(system, user, max_tokens=max_tokens)
        )
    except (llm.LLMUnavailable, llm.LLMBudgetExceeded):
        return None


def _snippet(text: str, limit: int = 320) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "…"


@traced("analyze")
def analyze(state: AgentState) -> dict:
    sid = state["session_id"]
    q = normalize_text(state["question"])
    lang = detect_language(q)
    if looks_like_injection(q) or any(
        looks_like_injection(h.get("question", ""))
        for h in state.get("history", [])
    ):
        logger.warning(
            "possible prompt-injection text in the question/history"
        )
    ready = registry.ready_doc_ids(sid)
    base = {
        "question": q,
        "lang": lang,
        "ready_ids": ready,
        "reformulations": 0,
        "sql_attempts": 0,
        "sql_tried": False,
        "sql_fallback": False,
    }
    if not ready:
        return {
            **base,
            "route": "none",
            "has_tables": False,
            "langs_in_docs": {},
            "_info": "no ready documents",
        }
    has_tables = table_store.has_tables(sid, ready)
    langs = dict(vector_store.language_stats(sid, ready))
    overlap: list[str] = []
    if has_tables and AGGREGATE_RE.search(q):
        overlap = table_store.schema_overlap(
            q, table_store.tables_for(sid, ready)
        )
    route = "sql" if overlap else "text"
    info = (
        f"route={route}, language={lang}, docs={len(ready)}, "
        f"tables={'yes' if has_tables else 'no'}"
    )
    if overlap:
        info += f", matched: {', '.join(overlap[:4])}"
    return {
        **base,
        "route": route,
        "has_tables": has_tables,
        "langs_in_docs": langs,
        "_info": info,
    }


def _needs_rewrite(state: AgentState) -> bool:
    if state.get("history"):
        return True
    langs = state.get("langs_in_docs", {})
    total = sum(langs.values()) or 1
    other = sum(v for k, v in langs.items() if k != state["lang"])
    return other / total >= 0.15


def route_after_analyze(state: AgentState) -> str:
    if state["route"] == "none":
        return "no_docs"
    if state["route"] == "sql":
        return "sql_plan"
    return "rewrite" if _needs_rewrite(state) else "retrieve"


@traced("rewrite")
def rewrite(state: AgentState) -> dict:
    lang = state["lang"]
    nonce = secrets.token_hex(8)
    system = P.REWRITE_SYSTEM.format(
        lang_name=P.LANG_NAME[lang],
        other_name=P.LANG_NAME[P.OTHER_LANG[lang]],
        nonce=nonce,
    )
    turns = (
        "\n".join(
            data_block(
                "turn",
                nonce,
                f"User: {t['question']}\nAssistant: {t['answer']}",
            )
            for t in state.get("history", [])
        )
        or "(no previous turns)"
    )
    user = f"Previous turns:\n{turns}\n\nQuestion: {state['question']}"
    data = _json_call(system, user, 300) or {}
    standalone = unique_nonempty([str(data.get("standalone", ""))]) or [
        state["question"]
    ]
    translation = unique_nonempty([str(data.get("translation", ""))])
    queries = unique_nonempty(standalone + translation)
    return {
        "standalone": standalone[0],
        "queries": queries,
        "_info": f"{len(queries)} query variant(s)",
    }


@traced("retrieve")
def retrieve(state: AgentState) -> dict:
    s = get_settings()
    sid, ready = state["session_id"], state["ready_ids"]
    queries = state.get("queries") or [state["question"]]
    pool = min(60, s.rerank_candidates * (1 + state.get("reformulations", 0)))
    merged: dict[int, tuple[vector_store.Hit, float]] = {}
    for q in queries:
        for rank, hit in enumerate(
            vector_store.search(
                sid,
                q,
                top_k=pool,
                allowed_doc_ids=ready,
                pool=max(pool, s.candidate_pool),
                apply_diversity=False,
            )
        ):
            prev = merged.get(hit.uid)
            merged[hit.uid] = (
                hit,
                (prev[1] if prev else 0.0) + 1.0 / (60 + rank + 1),
            )
    best = len(queries) * 1.0 / 61 or 1.0
    hits = []
    for hit, score in sorted(merged.values(), key=lambda x: -x[1])[:pool]:
        hit.relevance = min(1.0, score / best)
        hits.append(hit)
    return {
        "hits": hits,
        "_info": (
            f"{len(hits)} candidates from {len(queries)} query "
            f"variant(s), pool={pool}"
        ),
    }


@traced("rerank")
def rerank(state: AgentState) -> dict:
    s = get_settings()
    hits = list(state.get("hits", []))
    top_k = state.get("top_k") or s.retrieval_top_k
    reranker = embeddings.get_reranker() if hits else None
    if reranker is not None:
        try:
            variants = unique_nonempty(
                [
                    state.get("standalone") or state["question"],
                    *state.get("queries", []),
                ]
            )[:3]
            best_per_hit = [0.0] * len(hits)
            for variant in variants:
                for i, sc in enumerate(
                    reranker.score(variant, [h.text for h in hits])
                ):
                    best_per_hit[i] = max(best_per_hit[i], sc)
                if max(best_per_hit) >= s.rerank_confident_score:
                    break
            for h, sc in zip(hits, best_per_hit, strict=True):
                h.relevance = sc
            hits.sort(key=lambda h: -h.relevance)
        except Exception:
            logger.exception("reranker failed; keeping the fused ranking")
            reranker = None
    best = hits[0].relevance if hits else 0.0
    sufficient = bool(hits) and (
        best >= s.rerank_min_score if reranker is not None else True
    )
    final = vector_store.diversify(
        hits, top_k, s.max_chunks_per_doc_in_context
    )
    if reranker is not None:
        final = [
            h for h in final if h.relevance >= s.rerank_min_score
        ] or final[:1]
    info = (
        f"top score {best:.2f}"
        if reranker is not None
        else "no reranker (fused ranking)"
    )
    return {
        "hits": final,
        "best_score": best,
        "sufficient": sufficient,
        "_info": f"{len(final)} passages kept, {info}",
    }


def route_after_rerank(state: AgentState) -> str:
    if state.get("sufficient"):
        return "generate"
    if (
        state.get("reformulations", 0)
        < get_settings().agent_max_reformulations
    ):
        return "reformulate"
    if state.get("has_tables") and not state.get("sql_tried"):
        return "sql_plan"
    return "not_found"


@traced("reformulate")
def reformulate(state: AgentState) -> dict:
    lang = state["lang"]
    system = P.REFORMULATE_SYSTEM.format(
        other_name=P.LANG_NAME[P.OTHER_LANG[lang]]
    )
    tried = "; ".join(state.get("queries", []))
    data = (
        _json_call(
            system,
            f"Question ({P.LANG_NAME[lang]}): {state['question']}\n"
            f"Earlier queries: {tried}",
            300,
        )
        or {}
    )
    raw = data.get("queries")
    new = unique_nonempty(
        [x for x in raw if isinstance(x, str)] if isinstance(raw, list) else []
    )[:3]
    n = state.get("reformulations", 0) + 1
    return {
        "queries": new or [state.get("standalone") or state["question"]],
        "reformulations": n,
        "_info": f"attempt {n}: {len(new)} new query variant(s)",
    }


class _Source(BaseModel):
    id: str = ""
    quote: str = ""

    @field_validator("id", "quote", mode="before")
    @classmethod
    def _str(cls, v):
        return v if isinstance(v, str) else ""


class _LLMAnswer(BaseModel):
    answer: str = ""
    found: bool = False
    sources: list[_Source] = []

    @field_validator("answer", mode="before")
    @classmethod
    def _answer(cls, v):
        return v if isinstance(v, str) else ""

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, v):
        return (
            [x for x in v if isinstance(x, dict)]
            if isinstance(v, list)
            else []
        )


@traced("generate")
def generate(state: AgentState) -> dict:
    lang = state["lang"]
    nonce = secrets.token_hex(8)
    blocks, labels = [], {}
    for n, h in enumerate(state["hits"], start=1):
        label = f"S{n}"
        labels[label] = h
        if looks_like_injection(h.text):
            logger.warning(
                "possible prompt-injection text in a retrieved chunk"
            )
        blocks.append(
            data_block(
                "ctx",
                nonce,
                h.text,
                id=label,
                document=clean_for_prompt(h.filename),
                location=clean_for_prompt(h.location),
            )
        )
    system = P.ANSWER_SYSTEM.format(nonce=nonce, lang_name=P.LANG_NAME[lang])
    question = state.get("standalone") or state["question"]
    user = (
        "Context blocks:\n\n"
        + "\n\n".join(blocks)
        + f"\n\nQuestion ({P.LANG_NAME[lang]}): {question}"
    )
    data = parse_json_object(llm.complete(system, user))
    parsed = None
    if data is not None:
        try:
            parsed = _LLMAnswer.model_validate(data)
        except ValidationError:
            parsed = None
    return {
        "llm_answer": parsed,
        "labels": labels,
        "_info": f"{len(blocks)} context blocks",
    }


@traced("verify")
def verify(state: AgentState) -> dict:
    parsed: _LLMAnswer | None = state.get("llm_answer")
    labels = state.get("labels", {})
    if parsed is None:
        logger.warning("LLM returned unparsable output")
        return {
            "grounded": False,
            "result": {},
            "_info": "unparsable model output",
        }
    sources: list[SourceHit] = []
    seen: set[str] = set()
    verified_count = 0
    for src in parsed.sources:
        label = src.id.strip().upper()
        hit = labels.get(label)
        if hit is None or label in seen:
            continue
        seen.add(label)
        quote = src.quote.strip()
        ok = bool(quote) and collapse_for_match(quote) in collapse_for_match(
            hit.text
        )
        verified_count += ok
        sources.append(
            SourceHit(
                doc_id=hit.doc_id,
                filename=hit.filename,
                location=hit.location,
                excerpt=quote[:300] if ok else _snippet(hit.text),
                relevance=round(hit.relevance, 3),
                quote_verified=ok,
            )
        )
    if parsed.found and sources:
        return {
            "grounded": True,
            "_info": (
                f"{len(sources)} source(s), {verified_count} quote(s) verified"
            ),
            "result": {
                "answer": parsed.answer.strip(),
                "found": True,
                "sources": sources,
                "calculation": None,
            },
        }
    explanation = "" if parsed.found else parsed.answer.strip()
    return {
        "grounded": False,
        "result": {"explanation": explanation},
        "_info": "model found no answer"
        if not parsed.found
        else "answer had no valid citation",
    }


def route_after_verify(state: AgentState) -> str:
    if state.get("grounded"):
        return "done"
    if (
        state.get("reformulations", 0)
        < get_settings().agent_max_reformulations
    ):
        return "reformulate"
    return "not_found"


@traced("sql_plan")
def sql_plan(state: AgentState) -> dict:
    sid, lang = state["session_id"], state["lang"]
    tables = table_store.tables_for(sid, state["ready_ids"])
    attempts = state.get("sql_attempts", 0) + 1
    if not tables:
        return {
            "sql": "",
            "sql_attempts": attempts,
            "sql_tried": True,
            "sql_error": "no tables",
            "_info": "no tables",
        }
    nonce = secrets.token_hex(8)
    hint = ""
    previous = ""
    if state.get("sql_error") and state.get("sql"):
        hint = P.SQL_RETRY_HINT
        previous = "\n\n" + data_block(
            "schema",
            nonce,
            f"Previous query:\n{state['sql']}\n"
            f"Problem: {clean_for_prompt(state['sql_error'], 300)}",
            kind="previous-attempt",
        )
    system = P.SQL_SYSTEM.format(nonce=nonce, error_hint=hint)
    schema = data_block("schema", nonce, table_store.schema_prompt(tables))
    question = state.get("standalone") or state["question"]
    user = f"{schema}{previous}\n\nQuestion ({P.LANG_NAME[lang]}): {question}"
    data = _json_call(system, user, 500) or {}
    sql = str(data.get("sql", "")).strip()
    return {
        "sql": sql,
        "sql_attempts": attempts,
        "sql_tried": True,
        "_info": f"attempt {attempts}",
    }


@traced("sql_exec")
def sql_exec(state: AgentState) -> dict:
    sql = state.get("sql", "")
    if not sql:
        return {
            "sql_error": "the model could not write a query for this question",
            "sql_result": None,
            "_info": "no query produced",
        }
    try:
        res = table_store.execute(state["session_id"], sql, state["ready_ids"])
    except (
        table_store.SQLValidationError,
        table_store.SQLExecutionError,
    ) as exc:
        return {
            "sql_error": str(exc),
            "sql_result": None,
            "_info": f"rejected: {str(exc)[:80]}",
        }
    if res.row_count == 0:
        return {
            "sql_error": (
                "the query returned 0 rows - "
                "check the spelling of filter values"
            ),
            "sql_result": None,
            "_info": "0 rows",
        }
    return {
        "sql_error": "",
        "sql_result": res,
        "_info": f"{res.row_count} row(s)",
    }


def route_after_sql_exec(state: AgentState) -> str:
    if state.get("sql_result") is not None:
        return "sql_answer"
    if state.get(
        "sql_attempts", 0
    ) < get_settings().agent_sql_max_attempts and state.get("sql"):
        return "sql_plan"
    return "text_fallback"


@traced("sql_fallback")
def sql_fallback(state: AgentState) -> dict:
    return {
        "sql_fallback": True,
        "_info": (
            "SQL branch gave no usable result - "
            "falling back to document search"
        ),
    }


_NUM = re.compile(r"\d[\d\s\u00a0\u202f.,]*\d|\d")


def _candidates(token: str) -> list[float]:
    """All plausible numeric readings of a formatted number (separators
    are ambiguous: 1,234 / 1.234)."""
    s = re.sub(r"[\s\u00a0\u202f]", "", token)
    out: list[float] = []
    for decimal in (".", ","):
        thousands = "," if decimal == "." else "."
        if s.count(decimal) > 1:
            continue
        t = s.replace(thousands, "").replace(decimal, ".")
        try:
            out.append(float(t))
        except ValueError:
            continue
    return out


def _numbers_in(text: str) -> list[list[float]]:
    return [c for c in (_candidates(m) for m in _NUM.findall(text)) if c]


def _numbers_grounded(
    answer: str, res: table_store.QueryResult, question: str
) -> bool:
    allowed: set[float] = {float(res.row_count)}
    for cands in _numbers_in(question):
        allowed.update(cands)
    for row in res.rows:
        for v in row:
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                allowed.add(float(v))
            elif isinstance(v, str):
                for cands in _numbers_in(v):
                    allowed.update(cands)
    for cands in _numbers_in(answer):
        if any(n == int(n) and abs(n) <= 31 for n in cands):
            continue
        if not any(
            abs(n - a) <= max(0.0051, abs(a) * 1e-9)
            for n in cands
            for a in allowed
        ):
            return False
    return True


def _fmt(v) -> str:
    if isinstance(v, float):
        return (
            f"{v:,.2f}".replace(",", " ").rstrip("0").rstrip(".")
            if abs(v) >= 1000
            else f"{v:g}"
        )
    return "" if v is None else str(v)


def _deterministic_answer(res: table_store.QueryResult, lang: str) -> str:
    if len(res.rows) == 1 and len(res.columns) == 1:
        return f"{res.columns[0]}: {_fmt(res.rows[0][0])}"
    head = "Результат:" if lang == "ru" else "Result:"
    lines = [
        " | ".join(
            f"{c}: {_fmt(v)}" for c, v in zip(res.columns, row, strict=False)
        )
        for row in res.rows[:10]
    ]
    more = f"\n… ({res.row_count}+)" if res.truncated else ""
    return head + "\n" + "\n".join(lines) + more


@traced("sql_answer")
def sql_answer(state: AgentState) -> dict:
    res: table_store.QueryResult = state["sql_result"]
    lang = state["lang"]
    nonce = secrets.token_hex(8)
    preview = "\n".join(
        " | ".join(_fmt(v) for v in row) for row in res.rows[:20]
    )
    columns = " | ".join(clean_for_prompt(c, 60) for c in res.columns)
    body = f"columns: {columns}\n{preview}"
    user = (
        f"{data_block('result', nonce, body)}\n\n"
        f"Question ({P.LANG_NAME[lang]}): {state['question']}"
    )
    data = (
        _json_call(
            P.SQL_ANSWER_SYSTEM.format(
                nonce=nonce, lang_name=P.LANG_NAME[lang]
            ),
            user,
            400,
        )
        or {}
    )
    answer = str(data.get("answer", "")).strip()
    grounded = bool(answer) and _numbers_grounded(
        answer, res, state["question"]
    )
    if not grounded:
        answer = _deterministic_answer(res, lang)
    sources = [
        SourceHit(
            doc_id=t.doc_id,
            filename=t.filename,
            location=f"{t.sheet}, {t.n_rows} rows"
            if t.sheet
            else f"{t.n_rows} rows",
            excerpt=_snippet(
                f"SQL → {res.row_count} row(s): " + " | ".join(res.columns)
            ),
            relevance=1.0,
            quote_verified=True,
            kind="table",
        )
        for t in res.tables
    ]
    calc = {
        "sql": state["sql"],
        "columns": res.columns,
        "rows": res.rows[:10],
        "row_count": res.row_count,
        "truncated": res.truncated,
    }
    return {
        "result": {
            "answer": answer,
            "found": True,
            "sources": sources,
            "calculation": calc,
        },
        "_info": "LLM answer"
        if grounded
        else "deterministic answer (numbers did not match the result)",
    }


@traced("no_docs")
def no_docs(state: AgentState) -> dict:
    return {
        "result": {
            "answer": P.NO_DOCS[state["lang"]],
            "found": False,
            "sources": [],
            "calculation": None,
        }
    }


@traced("not_found")
def not_found(state: AgentState) -> dict:
    explanation = (state.get("result") or {}).get("explanation", "")
    return {
        "result": {
            "answer": explanation or P.NOT_FOUND[state["lang"]],
            "found": False,
            "sources": [],
            "calculation": None,
        }
    }
