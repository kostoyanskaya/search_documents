from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from functools import lru_cache

import openai
from openai import OpenAI

from app.core.config import get_settings
from app.core.observability import LLM_CALLS

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """Provider unreachable, misconfigured or timed out."""


class LLMBudgetExceeded(Exception):
    """Global request budget or concurrency limit hit."""


_sem: threading.BoundedSemaphore | None = None
_budget_lock = threading.Lock()
_budget = {"day": "", "count": 0}


def _semaphore() -> threading.BoundedSemaphore:
    global _sem
    if _sem is None:
        _sem = threading.BoundedSemaphore(get_settings().llm_max_concurrent)
    return _sem


@lru_cache
def _client() -> OpenAI:
    s = get_settings()
    return OpenAI(
        api_key=s.llm_api_key.get_secret_value(),
        base_url=s.llm_base_url,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
    )


def is_configured() -> bool:
    return bool(get_settings().llm_api_key.get_secret_value())


def _charge_budget() -> None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _budget_lock:
        if _budget["day"] != today:
            _budget["day"], _budget["count"] = today, 0
        if _budget["count"] >= get_settings().llm_daily_request_cap:
            LLM_CALLS.labels("budget_exceeded").inc()
            raise LLMBudgetExceeded("daily budget")
        _budget["count"] += 1


def complete(
    system: str,
    user: str,
    *,
    max_tokens: int = 1200,
    json_mode: bool | None = None,
) -> str:
    if not is_configured():
        raise LLMUnavailable("LLM_API_KEY is not configured")
    s = get_settings()
    _charge_budget()
    if not _semaphore().acquire(timeout=20):
        raise LLMBudgetExceeded("busy")
    started = time.monotonic()
    try:
        want_json = (
            s.llm_json_mode
            if json_mode is None
            else (json_mode and s.llm_json_mode)
        )
        kwargs = (
            {"response_format": {"type": "json_object"}} if want_json else {}
        )
        resp = _client().chat.completions.create(
            model=s.llm_model,
            temperature=0,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        LLM_CALLS.labels("ok").inc()
        return resp.choices[0].message.content or ""
    except openai.OpenAIError as exc:
        LLM_CALLS.labels("error").inc()
        logger.error(
            "LLM call failed: %s (%.1fs)",
            type(exc).__name__,
            time.monotonic() - started,
        )
        raise LLMUnavailable(type(exc).__name__) from exc
    finally:
        _semaphore().release()
