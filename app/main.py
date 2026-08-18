import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.deps import require_api_key
from app.api.v1.routes import claims, papers, queries, stream
from app.api.v2.routes import ws as v2_ws
from app.core.config import settings
from app.core.llm_provider import get_embedder_name, get_llm_name
from app.db.session import engine
from app.services import limits, pdf_export
from app.services.errors import NodusError, TooManyRequests

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Nodus starting — llm=%s embeddings=%s auth=%s admin=%s "
        "max_active_queries=%s daily_runs=%s rate_limit=%s",
        get_llm_name(),
        get_embedder_name(),
        # Never the values themselves: this line goes to stdout and log shipping.
        "on" if settings.api_key else "off",
        "on" if settings.admin_api_key else "off",
        settings.max_active_queries,
        settings.max_daily_runs or "unlimited",
        "on" if settings.rate_limit_enabled else "off",
    )
    yield
    await queries.cancel_background_tasks()
    await pdf_export.shutdown()
    await engine.dispose()


app = FastAPI(
    title="Nodus",
    description=(
        "Research paper analysis with evidence lineage, disagreement modelling "
        "and quality weighting."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(NodusError)
async def domain_error_handler(request: Request, exc: NodusError) -> JSONResponse:
    """Map transport-neutral service errors onto status codes.

    Services raise these so the same call works over HTTP and over the v2
    socket, which translates them to error frames instead.
    """
    headers = None
    if isinstance(exc, TooManyRequests) and exc.retry_after is not None:
        # A 429 without Retry-After tells a client to guess, and clients guess
        # by retrying immediately.
        headers = {"Retry-After": str(max(1, int(exc.retry_after)))}
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.message, **({"context": exc.detail} if exc.detail else {})},
        headers=headers,
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return a structured error instead of leaking a stack trace."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "path": request.url.path},
    )


_protected = [Depends(require_api_key)]

app.include_router(queries.router, prefix="/api/v1", dependencies=_protected)
app.include_router(papers.router, prefix="/api/v1", dependencies=_protected)
app.include_router(claims.router, prefix="/api/v1", dependencies=_protected)
# WebSocket routers authenticate inline — HTTP security schemes do not apply.
app.include_router(stream.router, prefix="/api/v1")
# v2 is a single socket carrying the whole API; see app/schemas/stream.py for
# the frame contract and `meta.describe` for the action catalogue.
app.include_router(v2_ws.router, prefix="/api/v2")


@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0"}


@app.get("/health/config", tags=["meta"])
async def health_config() -> dict:
    """Non-secret view of the active configuration — useful when swapping providers."""
    return {
        "llm_provider": settings.llm_provider,
        "llm_model": get_llm_name(),
        "embedding_provider": settings.embedding_provider,
        "embedding_model": get_embedder_name(),
        "embedding_dim": settings.embedding_dim,
        "auth_enabled": bool(settings.api_key),
        "admin_enabled": bool(settings.admin_api_key),
        "max_concurrent_papers": settings.max_concurrent_papers,
        "top_k_papers": settings.top_k_papers,
        "cluster_similarity_threshold": settings.active_cluster_threshold,
        "retrieval_mode": settings.retrieval_mode,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "runs": limits.run_gate.snapshot(),
    }
