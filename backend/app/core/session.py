from __future__ import annotations

import hashlib
import re
import secrets
import threading
import time

from app.core.config import get_settings

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{43}$")
_lock = threading.Lock()
_sessions: dict[str, float] = {}
_unlocked: set[str] = set()


class SessionCapacityError(Exception):
    pass


def sid_hash(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()[:8]


def lookup(cookie_value: str | None) -> str | None:
    ttl = get_settings().session_ttl_minutes * 60
    now = time.time()
    with _lock:
        if cookie_value and _TOKEN_RE.match(cookie_value):
            last = _sessions.get(cookie_value)
            if last is not None and now - last <= ttl:
                _sessions[cookie_value] = now
                return cookie_value
    return None


def create() -> str:
    with _lock:
        if len(_sessions) >= get_settings().max_sessions:
            raise SessionCapacityError
        sid = secrets.token_urlsafe(32)
        _sessions[sid] = time.time()
        return sid


def exists(session_id: str) -> bool:
    with _lock:
        return session_id in _sessions


def drop(session_id: str) -> None:
    with _lock:
        _sessions.pop(session_id, None)
        _unlocked.discard(session_id)


def unlock(session_id: str) -> None:
    with _lock:
        if session_id in _sessions:
            _unlocked.add(session_id)


def is_unlocked(session_id: str) -> bool:
    with _lock:
        return session_id in _unlocked


def expired_ids() -> list[str]:
    ttl = get_settings().session_ttl_minutes * 60
    now = time.time()
    with _lock:
        dead = [s for s, last in _sessions.items() if now - last > ttl]
        for s in dead:
            del _sessions[s]
            _unlocked.discard(s)
        return dead


def count() -> int:
    with _lock:
        return len(_sessions)
