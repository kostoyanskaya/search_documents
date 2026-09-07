from __future__ import annotations

import secrets
import threading
from datetime import datetime, timezone
from typing import Any

from fastapi import Request, Response

from app.core.config import get_settings

_lock = threading.Lock()
_sessions: dict[str, dict[str, Any]] = {}  # session_id -> {created_at, last_activity}


def _is_valid_token(session_id: str) -> bool:
    return bool(session_id) and all(c.isalnum() or c in "-_" for c in session_id)


def touch(session_id: str) -> None:
    with _lock:
        now = datetime.now(timezone.utc).isoformat()
        entry = _sessions.setdefault(session_id, {"created_at": now})
        entry["last_activity"] = now


def drop(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)


def get_session_id(request: Request, response: Response) -> str:
    settings = get_settings()
    session_id = request.cookies.get(settings.session_cookie_name)

    if not session_id or not _is_valid_token(session_id):
        session_id = secrets.token_urlsafe(32)
        response.set_cookie(
            key=settings.session_cookie_name,
            value=session_id,
            httponly=True,
            samesite="lax",
            secure=settings.session_cookie_secure,
            max_age=settings.session_ttl_hours * 3600,
            path="/",
        )

    touch(session_id)
    return session_id


def purge_expired(registry_module, vector_store_module) -> list[str]:
    """Removes sessions that have had no activity for longer than the TTL.
    There's nothing to clean up on disk — nothing is ever written there."""
    settings = get_settings()
    now = datetime.now(timezone.utc)

    with _lock:
        snapshot = dict(_sessions)

    expired = [
        sid for sid, meta in snapshot.items()
        if (now - datetime.fromisoformat(meta["last_activity"])).total_seconds()
        > settings.session_ttl_hours * 3600
    ]

    for sid in expired:
        wipe_session(sid, registry_module, vector_store_module)

    return expired


def wipe_session(session_id: str, registry_module, vector_store_module) -> None:
    """Single source of truth for tearing down everything tied to a session.
    Used by both the background cleanup loop and the explicit
    DELETE /api/session endpoint, so the teardown logic only lives in one place."""
    registry_module.remove_session(session_id)
    vector_store_module.delete_session(session_id)
    drop(session_id)
