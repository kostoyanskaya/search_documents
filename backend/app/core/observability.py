from __future__ import annotations

import contextvars
import json
import logging
import time
from datetime import UTC, datetime

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.core.config import get_settings

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)

REGISTRY = CollectorRegistry()
HTTP_REQUESTS = Counter(
    "docmind_http_requests_total",
    "HTTP requests",
    ["method", "route", "status"],
    registry=REGISTRY,
)
HTTP_SECONDS = Histogram(
    "docmind_http_request_seconds",
    "HTTP latency",
    ["route"],
    registry=REGISTRY,
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)
NODE_SECONDS = Histogram(
    "docmind_agent_node_seconds",
    "Agent graph node latency",
    ["node"],
    registry=REGISTRY,
    buckets=(0.005, 0.02, 0.1, 0.5, 1, 2.5, 5, 10, 30),
)
AGENT_ROUTES = Counter(
    "docmind_agent_route_total",
    "Final route taken by the agent",
    ["route", "outcome"],
    registry=REGISTRY,
)
LLM_CALLS = Counter(
    "docmind_llm_calls_total", "LLM calls", ["outcome"], registry=REGISTRY
)
DOCS_PROCESSED = Counter(
    "docmind_documents_processed_total",
    "Documents processed",
    ["status"],
    registry=REGISTRY,
)
RATE_LIMITED = Counter(
    "docmind_rate_limited_total",
    "Requests rejected by the rate limiter",
    ["bucket"],
    registry=REGISTRY,
)
ACTIVE_SESSIONS = Gauge(
    "docmind_active_sessions", "Sessions held in memory", registry=REGISTRY
)


def render_metrics() -> bytes:
    from app.core import session as sessions

    ACTIVE_SESSIONS.set(sessions.count())
    return generate_latest(REGISTRY)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging() -> None:
    s = get_settings()
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdFilter())
    if s.log_format == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s [%(request_id)s] "
                "%(name)s: %(message)s"
            )
        )
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def _scrub_event(event, hint):
    """Strip everything user-provided before it leaves the process."""
    request = event.get("request") or {}
    for key in ("data", "cookies", "query_string", "headers"):
        request.pop(key, None)
    event["request"] = request
    event.pop("user", None)
    return event


def init_sentry() -> bool:
    dsn = get_settings().sentry_dsn
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        before_send=_scrub_event,
        traces_sample_rate=0.0,
    )
    return True


class Timer:
    def __enter__(self):
        self.t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.seconds = time.perf_counter() - self.t
