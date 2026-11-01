import logging

from app.core import session as sessions

from . import document_registry, table_store, vector_store

logger = logging.getLogger(__name__)


def wipe_session(session_id: str) -> None:
    document_registry.remove_session(session_id)
    vector_store.delete_session(session_id)
    table_store.remove_session(session_id)
    sessions.drop(session_id)


def purge_expired() -> int:
    dead = sessions.expired_ids()
    for sid in dead:
        document_registry.remove_session(sid)
        vector_store.delete_session(sid)
        table_store.remove_session(sid)
    if dead:
        logger.info("purged %d expired session(s)", len(dead))
    return len(dead)
