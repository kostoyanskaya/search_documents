from __future__ import annotations

import json
import logging
import re
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core import session as sessions
from app.core.config import get_settings
from app.core.observability import (
    HTTP_REQUESTS,
    HTTP_SECONDS,
    RATE_LIMITED,
    request_id_var,
)
from app.core.ratelimit import limiter

logger = logging.getLogger("app.access")
_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
_PUBLIC = {"/api/health", "/api/ready"}
_OPEN_WHEN_LOCKED = {"/api/session", "/api/session/unlock"}
_RID = re.compile(r"^[A-Za-z0-9-]{8,64}$")


def _bucket(request: Request) -> tuple[str, int]:
    s = get_settings()
    path = request.url.path
    if path in ("/api/query", "/api/query/stream"):
        return "query", s.rate_limit_query_per_min
    if path == "/api/session/unlock":
        return "unlock", s.rate_limit_unlock_per_min
    if path == "/api/documents/upload":
        return "upload", s.rate_limit_upload_per_min
    return "other", s.rate_limit_other_per_min


class SessionSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        rid = rid if _RID.match(rid) else uuid.uuid4().hex[:16]
        request_id_var.set(rid)
        started = time.perf_counter()
        response = await self._handle(request, call_next)
        response.headers["X-Request-ID"] = rid
        route = getattr(request.scope.get("route"), "path", "unmatched")
        HTTP_REQUESTS.labels(
            request.method, route, str(response.status_code)
        ).inc()
        elapsed = time.perf_counter() - started
        HTTP_SECONDS.labels(route).observe(elapsed)
        if request.url.path.startswith("/api/"):
            logger.info(
                "%s %s -> %d (%d ms)",
                request.method,
                route,
                response.status_code,
                int(elapsed * 1000),
            )
        return response

    async def _handle(self, request: Request, call_next):
        s = get_settings()
        path = request.url.path
        if not path.startswith("/api/") or path in _PUBLIC:
            response = await call_next(request)
            self._headers(response)
            return response

        if request.method in _UNSAFE:
            origin = request.headers.get("origin")
            if origin and origin.rstrip("/") not in s.cors_origin_list:
                return self._headers(
                    JSONResponse(
                        {"detail": "Origin not allowed."}, status_code=403
                    )
                )

        ip = request.client.host if request.client else "unknown"
        bucket, per_min = _bucket(request)
        ok, retry = limiter.allow(ip, bucket, per_min)
        if not ok:
            RATE_LIMITED.labels(bucket).inc()
            resp = JSONResponse(
                {"detail": "Too many requests. Please slow down."},
                status_code=429,
            )
            resp.headers["Retry-After"] = str(retry)
            return self._headers(resp)

        sid = sessions.lookup(request.cookies.get(s.session_cookie_name)) or ""
        request.state.session_id = sid

        if (
            s.access_code.get_secret_value()
            and path not in _OPEN_WHEN_LOCKED
            and not (sid and sessions.is_unlocked(sid))
        ):
            resp = JSONResponse(
                {
                    "detail": "Access code required.",
                    "code": "access_code_required",
                },
                status_code=401,
            )
            return self._headers(resp)

        response = await call_next(request)
        sid = getattr(request.state, "session_id", "")
        if sid and sessions.exists(sid):
            self._set_cookie(response, sid)
        elif request.cookies.get(s.session_cookie_name):
            response.delete_cookie(s.session_cookie_name, path="/")
        return self._headers(response)

    @staticmethod
    def _set_cookie(response, sid: str) -> None:
        s = get_settings()
        response.set_cookie(
            s.session_cookie_name,
            sid,
            max_age=s.session_ttl_minutes * 60,
            httponly=True,
            secure=s.session_cookie_secure,
            samesite=s.session_cookie_samesite,
            path="/",
        )

    @staticmethod
    def _headers(response):
        s = get_settings()
        h = response.headers
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Cache-Control"] = "no-store"
        h["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )
        if s.session_cookie_secure:
            h["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = get_settings().max_request_mb * 1024 * 1024
        headers = dict(scope["headers"])
        declared = headers.get(b"content-length")
        if declared and declared.isdigit() and int(declared) > limit:
            return await self._reject(send)

        received = 0
        started = False

        async def counting_receive() -> Message:
            nonlocal received
            msg = await receive()
            if msg["type"] == "http.request":
                received += len(msg.get("body", b""))
                if received > limit:
                    raise _TooLarge
            return msg

        async def tracking_send(msg: Message) -> None:
            nonlocal started
            started = started or msg["type"] == "http.response.start"
            await send(msg)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not started:
                await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = json.dumps({"detail": "Request body is too large."}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
