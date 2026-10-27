import logging
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.auth.router import router as auth_router
from app.core.config import get_settings
from app.core.queue import redis_connection
from app.core.router import router as core_router
from app.routes.generation import router as generation_router
from contracts.v1.schemas import ErrorResponse
from services.assessment.router import router as assessment_router
from services.curriculum.router import router as curriculum_router
from services.export.router import router as publishing_router
from services.extraction.assets import router as assets_router
from services.extraction.router import router as extraction_router
from services.ingestion.router import router as ingestion_router
from services.knowledge.router import router as knowledge_router

settings = get_settings()
app = FastAPI(
    title="SomaLoom API",
    version="1.0.0",
    docs_url="/api/v1/docs",
    redoc_url=None,
    openapi_url="/api/v1/openapi.json",
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        429: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Idempotency-Key"],
)

LIMIT_SCRIPT = "local n = redis.call('INCR', KEYS[1]); if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end; return n"


def error(request, status, code, message, details=None):
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message, "details": details},
            "request_id": request.state.request_id,
        },
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = str(uuid4())
    response = None
    safe = request.method in {"GET", "HEAD", "OPTIONS"}
    cookie_auth = "somaloom_session" in request.cookies and not request.headers.get(
        "authorization", ""
    ).startswith("Bearer ")
    # Login also requires Origin to prevent login CSRF. CLI can supply an allowed Origin.
    if (
        not safe
        and (cookie_auth or request.url.path == "/api/v1/auth/login")
        and request.headers.get("origin") not in settings.origins
    ):
        response = error(request, 403, "csrf_rejected", "Allowed Origin required")
    if (
        response is None
        and settings.app_env != "test"
        and request.url.path not in {"/api/v1/health", "/api/v1/ready"}
    ):
        try:
            auth = request.url.path == "/api/v1/auth/login"
            client_ip = (
                request.headers.get("x-real-ip") if settings.app_env == "production" else None
            )
            client_ip = client_ip or (request.client.host if request.client else "unknown")
            key = f"somaloom:rate:{'login' if auth else 'api'}:{client_ip}"
            count = redis_connection().eval(LIMIT_SCRIPT, 1, key, 60)
            if count > (10 if auth else 600):
                response = error(request, 429, "rate_limited", "Too many requests")
                response.headers["Retry-After"] = "60"
        except Exception:
            response = error(
                request, 503, "rate_limit_unavailable", "Service temporarily unavailable"
            )
    if response is None:
        response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(StarletteHTTPException)
async def http_error(request, exc):
    return error(request, exc.status_code, f"http_{exc.status_code}", str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Never return input values: validation errors can contain passwords.
    details = [
        {"loc": list(e["loc"]), "type": e["type"], "message": e["msg"]} for e in exc.errors()
    ]
    return error(request, 422, "validation_error", "Invalid request", details)


@app.exception_handler(Exception)
async def internal_error(request, exc):
    logging.getLogger("somaloom").error(
        "Unhandled request failure request_id=%s type=%s",
        request.state.request_id,
        type(exc).__name__,
    )
    response = error(request, 500, "internal_error", "An internal error occurred")
    response.headers["X-Request-ID"] = request.state.request_id
    return response


app.include_router(auth_router, prefix="/api/v1")
app.include_router(core_router, prefix="/api/v1")
app.include_router(generation_router, prefix="/api/v1")
app.include_router(publishing_router, prefix="/api/v1")

app.include_router(ingestion_router, prefix="/api/v1")
app.include_router(extraction_router, prefix="/api/v1")
app.include_router(assets_router, prefix="/api/v1")
app.include_router(curriculum_router, prefix="/api/v1")
app.include_router(knowledge_router, prefix="/api/v1")
app.include_router(assessment_router, prefix="/api/v1")
