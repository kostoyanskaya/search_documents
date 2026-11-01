import asyncio
import hmac
import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.formparsers import MultiPartParser

from app.core import observability
from app.core.config import get_settings
from app.core.middleware import (
    BodySizeLimitMiddleware,
    SessionSecurityMiddleware,
)
from app.routers import documents, query
from app.routers import session as session_router
from app.services import embeddings, llm
from app.services.lifecycle import purge_expired

logger = logging.getLogger("app")


def _warm_up(app: FastAPI) -> None:
    """Load models in the background so the first user request is not slow."""
    try:
        embeddings.get_embedder().embed_query("warm-up")
        app.state.embedder_ready = True
        logger.info("embedding model ready")
    except Exception:
        logger.exception("embedding model failed to load")
    try:
        reranker = embeddings.get_reranker()
        if reranker is not None:
            reranker.score("warm-up", ["warm-up"])
        app.state.reranker_ready = True
        logger.info(
            "reranker %s", "ready" if reranker is not None else "disabled"
        )
    except Exception:
        logger.exception("reranker failed to load - continuing without it")
        embeddings.set_reranker(None, disabled=True)
        app.state.reranker_ready = True


async def _cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(purge_expired)
        except Exception:
            logger.exception("session cleanup failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    MultiPartParser.spool_max_size = s.max_upload_mb * 1024 * 1024
    app.state.embedder_ready = embeddings._embedder is not None
    app.state.reranker_ready = (
        embeddings._reranker is not None
        or embeddings._reranker_disabled
        or not s.reranker_model
    )
    if not (app.state.embedder_ready and app.state.reranker_ready):
        threading.Thread(target=_warm_up, args=(app,), daemon=True).start()
    if not llm.is_configured():
        logger.critical("LLM_API_KEY is not set - /api/query will return 503")
    if observability.init_sentry():
        logger.info("Sentry enabled (PII and request bodies are never sent)")
    task = asyncio.create_task(_cleanup_loop())
    try:
        yield
    finally:
        task.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    observability.setup_logging()
    app = FastAPI(
        title="DocMind",
        version="3.0.0",
        lifespan=lifespan,
        docs_url="/docs" if s.enable_api_docs else None,
        redoc_url=None,
        openapi_url="/openapi.json" if s.enable_api_docs else None,
    )
    app.add_middleware(SessionSecurityMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(BodySizeLimitMiddleware)

    app.include_router(documents.router)
    app.include_router(query.router)
    app.include_router(session_router.router)

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/ready")
    def ready():
        parts = {
            "embedder": bool(app.state.embedder_ready),
            "reranker": bool(app.state.reranker_ready),
            "llm": llm.is_configured(),
        }
        ok = all(parts.values())
        return JSONResponse(
            {"ready": ok, **parts}, status_code=200 if ok else 503
        )

    @app.get("/metrics", include_in_schema=False)
    def metrics(authorization: str | None = Header(default=None)):
        cfg = get_settings()
        if not cfg.enable_metrics:
            raise HTTPException(404)
        token = cfg.metrics_token.get_secret_value()
        if token and not hmac.compare_digest(
            (authorization or "").encode(), f"Bearer {token}".encode()
        ):
            raise HTTPException(401)
        return Response(
            observability.render_metrics(),
            media_type="text/plain; version=0.0.4",
        )

    return app


app = create_app()
