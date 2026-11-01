import time

import pytest

from app.core import session as sessions
from app.services import document_registry as registry
from app.services import llm


def _csv(name="a.csv", body="Товар,Цена\nЯблоко,10\n"):
    return ("files", (name, body.encode("utf-8"), "text/csv"))


def _wait_ready(client, n=1, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        docs = client.get("/api/documents").json()
        if len(docs) >= n and all(
            d["status"] in ("ready", "failed") for d in docs
        ):
            return docs
        time.sleep(0.05)
    raise AssertionError("processing did not finish")


def test_upload_is_atomic_on_validation_error(client):
    r = client.post(
        "/api/documents/upload",
        files=[_csv(), ("files", ("x.exe", b"MZ", "application/x"))],
    )
    assert r.status_code == 400
    assert client.get("/api/documents").json() == []
    assert "docmind_session" not in client.cookies


def test_upload_rejects_fake_extension_content(client):
    r = client.post(
        "/api/documents/upload",
        files=[("files", ("evil.pdf", b"just text", "application/pdf"))],
    )
    assert r.status_code == 400 and "valid" in r.json()["detail"]


def test_upload_process_dedupe_and_delete(client):
    r = client.post("/api/documents/upload", files=[_csv(), _csv("copy.csv")])
    assert r.status_code == 200
    body = r.json()
    assert len(body["accepted"]) == 1 and body["skipped_duplicates"] == [
        "copy.csv"
    ]
    doc = _wait_ready(client)[0]
    assert doc["status"] == "ready" and doc["chunks"] >= 1
    assert client.delete(f"/api/documents/{doc['doc_id']}").status_code == 200
    assert client.get("/api/documents").json() == []


def test_failed_parse_reports_user_message(client):
    pdf = b"%PDF-1.4\n garbage"
    client.post(
        "/api/documents/upload",
        files=[("files", ("bad.pdf", pdf, "application/pdf"))],
    )
    doc = _wait_ready(client)[0]
    assert doc["status"] == "failed" and "PDF" in doc["error"]


def test_quota_limits(client):
    files = [_csv(f"{i}.csv", f"a,b\n{i},{i}\n") for i in range(7)]
    r = client.post("/api/documents/upload", files=files)
    assert r.status_code == 413 and client.get("/api/documents").json() == []


def test_oversized_file_and_body(client):
    big = (
        "files",
        ("big.csv", b"a,b\n" + b"1,2\n" * 2_000_000, "text/csv"),
    )
    assert client.post("/api/documents/upload", files=[big]).status_code == 413


def test_validation_error_shape_and_empty_question(client):
    r = client.post("/api/query", json={"question": "   "})
    assert r.status_code == 422 and isinstance(r.json()["detail"], list)


def test_forged_session_cookie_is_never_accepted(client):
    forged = "A" * 43
    r = client.get(
        "/api/documents", headers={"Cookie": f"docmind_session={forged}"}
    )
    assert r.json() == [] and forged not in sessions._sessions
    assert 'docmind_session=""' in r.headers["set-cookie"]


def test_session_is_issued_on_first_upload(client):
    r = client.post("/api/documents/upload", files=[_csv()])
    assert r.status_code == 200
    header = r.headers["set-cookie"]
    issued = header.split("docmind_session=")[1].split(";")[0]
    assert issued in sessions._sessions
    assert "httponly" in header.lower() and "samesite=lax" in header.lower()


def test_anonymous_requests_do_not_consume_sessions(client):
    before = sessions.count()
    for _ in range(25):
        assert client.get("/api/session").status_code == 200
        assert client.get("/api/documents").status_code == 200
    assert sessions.count() == before


def test_new_sessions_are_rate_limited_per_ip(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_new_session_per_min", 2)
    codes = []
    for i in range(4):
        fresh = type(client)(client.app, base_url="http://localhost")
        r = fresh.post(
            "/api/documents/upload",
            files=[_csv(f"{i}.csv", f"a,b\n{i},{i}\n")],
        )
        codes.append(r.status_code)
    assert codes == [200, 200, 429, 429]


def test_session_table_full_blocks_only_new_sessions(client, monkeypatch):
    from app.core.config import get_settings

    client.post("/api/documents/upload", files=[_csv()])
    monkeypatch.setattr(get_settings(), "max_sessions", sessions.count())
    newcomer = type(client)(client.app, base_url="http://localhost")
    r = newcomer.post("/api/documents/upload", files=[_csv("n.csv", "a\n1\n")])
    assert r.status_code == 503
    assert client.get("/api/documents").status_code == 200


def test_cross_origin_unsafe_request_blocked(client):
    r = client.delete(
        "/api/session", headers={"Origin": "https://evil.example"}
    )
    assert r.status_code == 403
    assert (
        client.delete(
            "/api/session", headers={"Origin": "http://localhost:5173"}
        ).status_code
        == 200
    )


def test_security_headers_and_docs_disabled(client):
    r = client.get("/api/health")
    assert (
        r.headers["x-content-type-options"] == "nosniff"
        and r.headers["x-frame-options"] == "DENY"
    )
    assert (
        client.get("/docs").status_code == 404
        and client.get("/openapi.json").status_code == 404
    )


def test_rate_limit(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_query_per_min", 2)
    from app.core.ratelimit import limiter

    limiter._buckets.clear()
    codes = [
        client.post("/api/query", json={"question": "hello?"}).status_code
        for _ in range(4)
    ]
    assert codes[:2] == [200, 200] and codes[2:] == [429, 429]


def test_query_without_documents(client):
    r = client.post("/api/query", json={"question": "Какая выручка?"})
    assert (
        r.status_code == 200
        and not r.json()["found"]
        and r.json()["language"] == "ru"
    )


def _upload_ru_en(client):
    client.post(
        "/api/documents/upload",
        files=[
            _csv(
                "sales.csv",
                "Показатель,Значение\nВыручка за 2023 год,1 250 000 рублей\n",
            ),
            _csv("lease.csv", "Term,Value\nMonthly rent,3400 USD\n"),
        ],
    )
    _wait_ready(client, 2)


def test_query_answers_in_question_language_with_verified_citation(
    client, fake_llm
):
    fake_llm.on(
        "answer",
        lambda user: {
            "answer": "Выручка за 2023 год — 1 250 000 рублей.",
            "found": True,
            "sources": [
                {"id": "S1", "quote": "Выручка за 2023 год | 1 250 000 рублей"}
            ],
        },
    )
    _upload_ru_en(client)
    r = client.post(
        "/api/query", json={"question": "Какая выручка за 2023 год?"}
    ).json()
    call = next(c for c in fake_llm.calls if c[0] == "answer")
    assert "Russian" in call[1] and r["found"] and r["language"] == "ru"
    assert r["sources"][0]["quote_verified"] is True and r["sources"][0][
        "location"
    ].startswith("row")
    assert [s["node"] for s in r["steps"]][0] == "analyze"


def test_english_question_over_russian_doc_requests_english_answer(
    client, fake_llm
):
    fake_llm.on(
        "rewrite",
        {
            "standalone": "What was the revenue in 2023?",
            "translation": "Какая выручка за 2023 год?",
        },
    )
    fake_llm.on(
        "answer",
        {
            "answer": "Revenue was 1 250 000 rubles.",
            "found": True,
            "sources": [{"id": "S1", "quote": "x"}],
        },
    )
    _upload_ru_en(client)
    r = client.post(
        "/api/query", json={"question": "What was the revenue in 2023?"}
    ).json()
    call = next(c for c in fake_llm.calls if c[0] == "answer")
    assert "Write the answer in English" in call[1] and r["found"]
    assert r["sources"][0]["quote_verified"] is False


def test_garbage_llm_output_never_presented_as_answer(client, fake_llm):
    _upload_ru_en(client)
    for reply in [
        "not json at all",
        "[1,2,3]",
        '{"answer": ["x"], "found": true, "sources": "S1"}',
        "",
    ]:
        fake_llm.on("answer", reply)
        r = client.post("/api/query", json={"question": "revenue 2023?"})
        assert r.status_code == 200 and r.json()["found"] is False


def test_llm_failures_map_to_clean_http_errors(client, fake_llm):
    _upload_ru_en(client)

    def boom(user):
        raise llm.LLMUnavailable("Timeout")

    fake_llm.on("answer", boom)
    r = client.post(
        "/api/query", json={"question": "What is the monthly rent?"}
    )
    assert r.status_code == 503 and "Timeout" not in r.text

    def busy(user):
        raise llm.LLMBudgetExceeded("daily")

    fake_llm.on("answer", busy)
    assert (
        client.post(
            "/api/query", json={"question": "What is the monthly rent?"}
        ).status_code
        == 429
    )


def test_history_is_validated_and_capped(client, fake_llm):
    _upload_ru_en(client)
    long = "x" * 5000
    assert (
        client.post(
            "/api/query",
            json={
                "question": "revenue?",
                "history": [{"question": long, "answer": "a"}],
            },
        ).status_code
        == 422
    )
    turns = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(6)]
    assert (
        client.post(
            "/api/query", json={"question": "and rent?", "history": turns}
        ).status_code
        == 200
    )
    rewrite = next(c for c in fake_llm.calls if c[0] == "rewrite")
    assert "q5" in rewrite[2] and "q0" not in rewrite[2]


def test_stream_endpoint_sends_steps_then_result(client, fake_llm):
    import json as _json

    fake_llm.on(
        "answer",
        {
            "answer": "ok",
            "found": True,
            "sources": [{"id": "S1", "quote": "Monthly rent | 3400 USD"}],
        },
    )
    _upload_ru_en(client)
    with client.stream(
        "POST",
        "/api/query/stream",
        json={"question": "What is the monthly rent?"},
    ) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [
        (e.split("\n")[0][7:], _json.loads(e.split("\n")[1][6:]))
        for e in body.strip().split("\n\n")
    ]
    assert [k for k, _ in events][:-1] == ["step"] * (
        len(events) - 1
    ) and events[-1][0] == "result"
    assert events[-1][1]["found"] is True and events[0][1]["node"] == "analyze"


def test_stream_reports_llm_errors_as_events(client, fake_llm):
    def boom(user):
        raise llm.LLMUnavailable("x")

    fake_llm.on("answer", boom)
    _upload_ru_en(client)
    with client.stream(
        "POST",
        "/api/query/stream",
        json={"question": "What is the monthly rent?"},
    ) as r:
        body = "".join(r.iter_text())
    assert "event: error" in body and '"status": 503' in body


def test_spreadsheet_question_end_to_end_with_sql(client, fake_llm):
    fake_llm.on(
        "sql",
        {
            "sql": (
                'SELECT "Город", SUM("Выручка") AS s FROM t1 '
                "GROUP BY 1 ORDER BY 2 DESC"
            )
        },
    )
    fake_llm.on(
        "sql_answer", {"answer": "Больше всего у Москвы — 1 245 000,25."}
    )
    client.post(
        "/api/documents/upload",
        files=[
            _csv(
                "sales.csv",
                "Город;Дата;Выручка\n"
                'Москва;2023-01-15;"1 250 000,50"\n'
                'Казань;15.02.2023;"980 000,00"\n'
                'Москва;01.03.2023;"(5 000,25)"\n',
            )
        ],
    )
    _wait_ready(client)
    r = client.post(
        "/api/query", json={"question": "В каком городе наибольшая выручка?"}
    ).json()
    assert (
        r["route"] == "sql"
        and r["calculation"]["rows"][0][0] == "Москва"
        and r["sources"][0]["kind"] == "table"
    )


def test_document_progress_fields(client):
    client.post("/api/documents/upload", files=[_csv()])
    doc = _wait_ready(client)[0]
    assert doc["progress"] == 100 and doc["stage"] == "done"


def test_scanned_pdf_is_ocrd_end_to_end(client):
    import shutil

    if shutil.which("tesseract") is None:
        pytest.skip("tesseract not installed")
    from tests.test_files import scanned_pdf

    client.post(
        "/api/documents/upload",
        files=[("files", ("scan.pdf", scanned_pdf(), "application/pdf"))],
    )
    doc = _wait_ready(client, timeout=60)[0]
    assert doc["status"] == "ready" and doc["chunks"] >= 1


def test_access_code_gate(client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "access_code", SecretStr("s3cret"))
    r = client.get("/api/documents")
    assert r.status_code == 401 and r.json()["code"] == "access_code_required"
    assert client.get("/api/session").json() == {
        "access_required": True,
        "unlocked": False,
    }
    assert (
        client.post("/api/session/unlock", json={"code": "wrong"}).status_code
        == 403
    )
    assert (
        client.post("/api/session/unlock", json={"code": "s3cret"}).status_code
        == 200
    )
    assert client.get("/api/documents").status_code == 200
    assert client.get("/api/session").json() == {
        "access_required": True,
        "unlocked": True,
    }


def test_access_code_unlock_is_rate_limited(client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "access_code", SecretStr("s3cret"))
    monkeypatch.setattr(get_settings(), "rate_limit_unlock_per_min", 3)
    codes = [
        client.post("/api/session/unlock", json={"code": str(i)}).status_code
        for i in range(5)
    ]
    assert codes[:3] == [403] * 3 and codes[3:] == [429, 429]


def test_request_id_header_and_metrics(client):
    r = client.get("/api/documents", headers={"X-Request-ID": "abc-12345678"})
    assert r.headers["x-request-id"] == "abc-12345678"
    assert (
        client.get(
            "/api/documents", headers={"X-Request-ID": "bad id!\n"}
        ).headers["x-request-id"]
        != "bad id!\n"
    )
    text = client.get("/metrics").text
    expected = (
        "docmind_http_requests_total{"
        'method="GET",route="/api/documents",status="200"}'
    )
    assert expected in text


def test_metrics_token_protects_endpoint(client, monkeypatch):
    from pydantic import SecretStr

    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "metrics_token", SecretStr("tok"))
    assert client.get("/metrics").status_code == 401
    assert (
        client.get(
            "/metrics", headers={"Authorization": "Bearer tok"}
        ).status_code
        == 200
    )


def test_wipe_during_processing_leaves_no_orphans(client, monkeypatch):
    from app.routers import documents as docs
    from app.services import vector_store

    sid = None
    real_index = vector_store.index_document

    def slow_index(session_id, *a, **k):
        nonlocal sid
        sid = session_id
        n = real_index(session_id, *a, **k)
        from app.services.lifecycle import wipe_session

        wipe_session(session_id)
        return n

    monkeypatch.setattr(docs.vector_store, "index_document", slow_index)
    client.post("/api/documents/upload", files=[_csv()])
    assert (
        sid
        and vector_store._indexes.get(sid) is None
        and registry.list_documents(sid) == []
    )


def test_subprocess_parser_end_to_end(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "parse_in_subprocess", True)
    client.post(
        "/api/documents/upload",
        files=[_csv("ru.csv", "Имя;Город\nАнна;Москва\n")],
    )
    assert _wait_ready(client, timeout=30)[0]["status"] == "ready"


def test_health_and_ready(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/ready").status_code in (200, 503)


def test_uploads_stay_in_memory_not_on_disk(client, monkeypatch):
    import starlette.formparsers as fp

    rolled = []
    original = fp.SpooledTemporaryFile.rollover
    monkeypatch.setattr(
        fp.SpooledTemporaryFile,
        "rollover",
        lambda self: (rolled.append(1), original(self))[1],
    )
    body = "a,b\n" + "1,2\n" * 700_000
    assert (
        client.post(
            "/api/documents/upload", files=[_csv("big.csv", body)]
        ).status_code
        == 200
    )
    assert rolled == []
