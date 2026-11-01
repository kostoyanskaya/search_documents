import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, StringConstraints

from app.core import session as sessions
from app.core.config import get_settings
from app.routers.deps import ensure_session, get_session_id
from app.services.lifecycle import wipe_session

router = APIRouter(prefix="/api/session", tags=["session"])


class UnlockRequest(BaseModel):
    code: Annotated[str, StringConstraints(max_length=200)]


@router.get("")
def session_status(session_id: str = Depends(get_session_id)):
    required = bool(get_settings().access_code.get_secret_value())
    unlocked = (not required) or (
        bool(session_id) and sessions.is_unlocked(session_id)
    )
    return {"access_required": required, "unlocked": unlocked}


@router.post("/unlock")
def unlock(body: UnlockRequest, request: Request):
    expected = get_settings().access_code.get_secret_value()
    if expected and not hmac.compare_digest(
        body.code.encode(), expected.encode()
    ):
        raise HTTPException(403, "Wrong access code.")
    sessions.unlock(ensure_session(request))
    return {"ok": True}


@router.delete("")
def clear_session(session_id: str = Depends(get_session_id)):
    if session_id:
        wipe_session(session_id)
    return {"ok": True}
