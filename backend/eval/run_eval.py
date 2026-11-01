"""Quality harness for the REAL models/LLM. Run it before going live and
after any change to models, prompts or chunking.

  python -m eval.run_eval
      # full: retrieval + answers (needs LLM_API_KEY, models)
  python -m eval.run_eval --retrieval-only
      # no LLM calls; only document-hit@k
  python -m eval.run_eval --golden my.jsonl --corpus my_docs/
      # your own documents and questions

Metrics (per language and cross-lingual): document hit@k, answer contains
expected facts, citation verified rate, abstention accuracy on unanswerable
questions, SQL-route accuracy, latency.
Exit code is 1 when a threshold (--min-hit, --min-answer, --min-abstain)
is not met.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
import time
import uuid
from collections import defaultdict

HERE = pathlib.Path(__file__).parent


def load_corpus(sid: str, corpus: pathlib.Path) -> dict[str, str]:
    """Index every file of a directory into one session; returns
    {doc_id: filename}."""
    import hashlib

    from app.models.schemas import DocStatus
    from app.services import document_registry as registry
    from app.services import table_store, vector_store
    from app.services.file_processing import (
        ALLOWED_EXTENSIONS,
        extract_document,
    )

    ids = {}
    for path in sorted(corpus.iterdir()):
        if path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        content = path.read_bytes()
        parsed = extract_document(content, path.suffix.lower(), name=path.stem)
        item = {
            "filename": path.name,
            "file_type": path.suffix[1:],
            "size": len(content),
            "hash": hashlib.sha256(content).hexdigest(),
        }
        info = registry.register_batch(sid, [item], 10_000, 10**12)[0][0][0]
        n = vector_store.index_document(
            sid, info.doc_id, path.name, parsed.blocks
        )
        table_store.add_tables(sid, info.doc_id, path.name, parsed.tables)
        registry.update_status(sid, info.doc_id, DocStatus.READY, chunks=n)
        ids[info.doc_id] = path.name
    return ids


def _norm(s: str) -> str:
    return " ".join(s.lower().replace("\u00a0", " ").split())


def evaluate(
    golden: list[dict],
    corpus: pathlib.Path,
    retrieval_only: bool = False,
    top_k: int = 8,
    hit_k: int = 3,
) -> dict:
    from app.services import vector_store
    from app.services.agent import run_agent
    from app.services.lifecycle import wipe_session

    sid = uuid.uuid4().hex
    ids = load_corpus(sid, corpus)
    by_name = {v: k for k, v in ids.items()}
    rows = []
    try:
        for g in golden:
            t0 = time.perf_counter()
            row = {
                "id": g["id"],
                "lang": g["lang"],
                "cross": bool(g.get("cross_lingual")),
                "kind": g.get("kind", "text"),
                "answerable": g.get("answerable", True),
            }
            expected_ids = {
                by_name[d] for d in g.get("docs", []) if d in by_name
            }
            if retrieval_only:
                if row["answerable"] and row["kind"] == "text":
                    hits = vector_store.search(
                        sid,
                        g["question"],
                        max(top_k, hit_k),
                        apply_diversity=False,
                    )
                    ranked_docs = [h.doc_id for h in hits]
                    first = next(
                        (
                            i
                            for i, d in enumerate(ranked_docs, 1)
                            if d in expected_ids
                        ),
                        None,
                    )
                    row["hit"] = (
                        first is not None and first <= hit_k
                    )  # hit@k (default k=3)
                    row["rr"] = (
                        1.0 / first if first else 0.0
                    )  # reciprocal rank -> MRR
            else:
                resp = run_agent(sid, g["question"], None, top_k)
                row["found"] = resp.found
                row["route"] = resp.route
                row["steps"] = len(resp.steps)
                if row["answerable"]:
                    row["hit"] = bool(
                        {s.doc_id for s in resp.sources} & expected_ids
                    )
                    row["contains"] = (
                        any(
                            _norm(x) in _norm(resp.answer)
                            for x in g.get("contains", [])
                        )
                        if g.get("contains")
                        else None
                    )
                    row["verified"] = bool(resp.sources) and all(
                        s.quote_verified for s in resp.sources
                    )
                    row["route_ok"] = (resp.route == "sql") == (
                        row["kind"] == "sql"
                    )
                else:
                    row["abstained"] = not resp.found
                row["answer"] = resp.answer[:160]
            row["ms"] = int((time.perf_counter() - t0) * 1000)
            rows.append(row)
    finally:
        wipe_session(sid)
    return {"rows": rows, "summary": summarize(rows)}


def _rate(rows, key):
    vals = [r[key] for r in rows if r.get(key) is not None]
    return round(sum(vals) / len(vals), 3) if vals else None


def summarize(rows: list[dict]) -> dict:
    groups = {
        "all": rows,
        "ru": [r for r in rows if r["lang"] == "ru"],
        "en": [r for r in rows if r["lang"] == "en"],
        "cross_lingual": [r for r in rows if r["cross"]],
        "sql": [r for r in rows if r["kind"] == "sql"],
    }
    out = defaultdict(dict)
    for name, rs in groups.items():
        out[name] = {
            "n": len(rs),
            "doc_hit": _rate(rs, "hit"),
            "mrr": _rate(rs, "rr"),
            "answer_contains": _rate(rs, "contains"),
            "citations_verified": _rate(rs, "verified"),
            "abstain_ok": _rate(rs, "abstained"),
            "route_ok": _rate(rs, "route_ok"),
            "latency_ms_p50": int(statistics.median([r["ms"] for r in rs]))
            if rs
            else None,
        }
    return dict(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--golden", type=pathlib.Path, default=HERE / "golden.jsonl"
    )
    ap.add_argument("--corpus", type=pathlib.Path, default=HERE / "corpus")
    ap.add_argument("--retrieval-only", action="store_true")
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument(
        "--hit-k", type=int, default=3, help="k for retrieval-only hit@k"
    )
    ap.add_argument(
        "--json", type=pathlib.Path, help="write the full report here"
    )
    ap.add_argument("--min-hit", type=float, default=0.0)
    ap.add_argument("--min-answer", type=float, default=0.0)
    ap.add_argument("--min-abstain", type=float, default=0.0)
    args = ap.parse_args()

    sys.path.insert(0, str(HERE.parent))
    golden = [
        json.loads(line)
        for line in args.golden.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    report = evaluate(
        golden, args.corpus, args.retrieval_only, args.top_k, args.hit_k
    )
    for r in report["rows"]:
        flags = " ".join(
            f"{k}={v}"
            for k, v in r.items()
            if k in ("hit", "rr", "contains", "verified", "abstained", "route")
            and v is not None
        )
        print(f"{r['id']:<18} {r['ms']:>6} ms  {flags}")
    print("\n" + json.dumps(report["summary"], ensure_ascii=False, indent=2))
    if args.json:
        args.json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    s = report["summary"]["all"]
    failed = [
        name
        for name, key, thr in [
            ("doc_hit", "doc_hit", args.min_hit),
            ("answer_contains", "answer_contains", args.min_answer),
            ("abstain_ok", "abstain_ok", args.min_abstain),
        ]
        if thr and (s[key] is None or s[key] < thr)
    ]
    if failed:
        print("\nTHRESHOLD NOT MET:", ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
