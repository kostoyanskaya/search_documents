import json
import pathlib
import re

from eval.run_eval import evaluate, summarize

GOLDEN = [
    json.loads(line)
    for line in (pathlib.Path("eval/golden.jsonl"))
    .read_text(encoding="utf-8")
    .splitlines()
    if line
]
CORPUS = pathlib.Path("eval/corpus")


def test_golden_set_is_well_formed_and_bilingual():
    corpus = {p.name for p in CORPUS.iterdir()}
    assert len(GOLDEN) >= 20 and len({g["id"] for g in GOLDEN}) == len(GOLDEN)
    for g in GOLDEN:
        assert set(g["docs"]) <= corpus and g["lang"] in ("ru", "en")
        assert g.get("answerable", True) is False or g["contains"]
    assert (
        sum(g["lang"] == "ru" for g in GOLDEN) >= 8
        and sum(g["lang"] == "en" for g in GOLDEN) >= 8
    )
    assert (
        sum(bool(g.get("cross_lingual")) for g in GOLDEN) >= 4
        and sum(g.get("answerable") is False for g in GOLDEN) >= 3
    )


def test_retrieval_only_harness_runs_on_the_committed_corpus():
    report = evaluate(GOLDEN, CORPUS, retrieval_only=True)
    same_lang = [r for r in report["rows"] if "hit" in r and not r["cross"]]
    assert (
        same_lang and sum(r["hit"] for r in same_lang) / len(same_lang) >= 0.85
    )
    assert report["summary"]["all"]["n"] == len(GOLDEN)


def test_full_harness_plumbing_with_a_scripted_llm(fake_llm):
    def answer(user):
        block = re.search(
            r'<ctx-\w+ id="S1"[^>]*>\n(.*?)\n</ctx-', user, re.S
        ).group(1)
        return {
            "answer": block,
            "found": True,
            "sources": [{"id": "S1", "quote": block[:60]}],
        }

    fake_llm.on("answer", answer)
    report = evaluate([g for g in GOLDEN if g["kind"] == "text"], CORPUS)
    assert report["summary"]["all"]["citations_verified"] == 1.0
    summary = report["summary"]["all"]
    assert (
        summary["abstain_ok"] is not None
        and 0.0 <= summary["abstain_ok"] <= 1.0
    )
    assert (
        summary["doc_hit"] is not None
        and summary["answer_contains"] is not None
    )


def test_summarize_handles_empty_groups():
    s = summarize(
        [{"id": "a", "lang": "ru", "cross": False, "kind": "text", "ms": 5}]
    )
    assert s["en"]["n"] == 0 and s["en"]["latency_ms_p50"] is None
