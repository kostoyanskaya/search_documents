import openai
import pytest

from app.core.config import get_settings
from app.services import llm


class _Resp:
    def __init__(self, text):
        self.choices = [
            type("C", (), {"message": type("M", (), {"content": text})()})()
        ]


class _FakeClient:
    def __init__(self, behaviour):
        self.calls = []
        self.chat = type("Chat", (), {"completions": self})()
        self.behaviour = behaviour

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.behaviour()


@pytest.fixture
def client(monkeypatch):
    fake = _FakeClient(lambda: _Resp('{"ok": true}'))
    monkeypatch.setattr(llm, "_client", lambda: fake)
    monkeypatch.setattr(llm, "_budget", {"day": "", "count": 0})
    return fake


def test_request_shape_json_mode_and_deterministic(client):
    assert llm.complete("sys", "usr", max_tokens=300) == '{"ok": true}'
    call = client.calls[0]
    assert (
        call["temperature"] == 0
        and call["max_tokens"] == 300
        and call["response_format"] == {"type": "json_object"}
    )
    llm.complete("s", "u", json_mode=False)
    assert "response_format" not in client.calls[1]


def test_provider_errors_become_clean_unavailable(client):
    def boom():
        raise openai.APITimeoutError(request=None)

    client.behaviour = boom
    with pytest.raises(llm.LLMUnavailable) as exc:
        llm.complete("s", "u")
    assert "secret" not in str(exc.value)


def test_daily_budget_is_enforced(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "llm_daily_request_cap", 2)
    llm.complete("s", "u")
    llm.complete("s", "u")
    with pytest.raises(llm.LLMBudgetExceeded):
        llm.complete("s", "u")


def test_missing_key_is_reported_not_crashed(monkeypatch):
    from pydantic import SecretStr

    monkeypatch.setattr(get_settings(), "llm_api_key", SecretStr(""))
    with pytest.raises(llm.LLMUnavailable):
        llm.complete("s", "u")
