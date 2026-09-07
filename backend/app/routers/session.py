from fastapi import APIRouter, Depends

from app.core import session as session_module
from app.core.session import get_session_id
from app.services import document_registry as registry
from app.services import vector_store

router = APIRouter(prefix="/api/session", tags=["session"])


@router.delete("")
async def clear_session(session_id: str = Depends(get_session_id)) -> dict:
    session_module.wipe_session(session_id, registry, vector_store)
    return {"ok": True, "cleared": True}
