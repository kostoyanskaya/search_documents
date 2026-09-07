import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core import session as session_module
from app.services import document_registry as registry
from app.services import vector_store
from app.routers import documents, query, session as session_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()


async def _cleanup_loop() -> None:
    while True:
        try:
            expired = session_module.purge_expired(registry, vector_store)
            if expired:
                logger.info("Cleaned up %d expired session(s)", len(expired))
        except Exception:
            logger.exception("Session cleanup failed")
        await asyncio.sleep(settings.cleanup_interval_minutes * 60)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.session_cookie_secure:
        logger.warning(
            "session_cookie_secure=False — fine for local development, but "
            "this MUST be True in production (served over HTTPS)."
        )
    task = asyncio.create_task(_cleanup_loop())
    yield
    task.cancel()


app = FastAPI(
    title="Document Search Agent",
    description="A RAG agent that runs entirely in memory — uploaded documents are never written to disk.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(documents.router)
app.include_router(query.router)
app.include_router(session_router.router)


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "storage_mode": "in-memory (ephemeral)"}
