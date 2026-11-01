from fastapi import HTTPException, Request

from app.core import session as sessions
from app.core.config import get_settings
from app.core.ratelimit import limiter


def get_session_id(request: Request) -> str:
    return getattr(request.state, "session_id", "") or ""


def ensure_session(request: Request) -> str:
    sid = get_session_id(request)
    if sid:
        return sid
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    ok, retry = limiter.allow(
        ip, "new_session", s.rate_limit_new_session_per_min
    )
    if not ok:
        raise HTTPException(
            429,
            "Too many new sessions. Please slow down.",
            headers={"Retry-After": str(retry)},
        )
    try:
        sid = sessions.create()
    except sessions.SessionCapacityError:
        raise HTTPException(503, "Server is busy. Try again later.") from None
    request.state.session_id = sid
    return sid
