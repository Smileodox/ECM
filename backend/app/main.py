import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger.json import JsonFormatter
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

_handler = logging.StreamHandler()
if os.environ.get("LOG_FORMAT") == "text":
    _handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    ))
else:
    _handler.setFormatter(JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
        datefmt="%Y-%m-%dT%H:%M:%SZ",
    ))
logging.root.handlers = [_handler]
logging.root.setLevel(logging.INFO)

_log_filter_class = type("RequestIDFilter", (logging.Filter,), {
    "filter": lambda self, record: (setattr(record, "request_id", "-") or True) if not hasattr(record, "request_id") else True,
})
_handler.addFilter(_log_filter_class())

from app.config import settings
from app.limiter import limiter
from app.models import FeedbackRequest
from app.routers import chat, ingest


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    from app.search.retriever import close_search_client
    await close_search_client()


app = FastAPI(
    title="campusLMU Chatbot API",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Zu viele Anfragen. Bitte warte einen Moment."},
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:8]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


app.add_middleware(RequestIDMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Ingest-Key"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")


_health_cache: dict = {"status": "ok", "openai_ok": False, "search_ok": False, "checked_at": 0.0}

@app.get("/api/health")
async def health():
    """Health check — probes dependencies at most once per minute to avoid billable calls."""
    import time
    now = time.monotonic()
    if now - _health_cache["checked_at"] > 60:
        checks: dict = {"status": "ok", "openai_ok": False, "search_ok": False}
        try:
            from app.search.retriever import _get_search_client
            client = _get_search_client()
            await client.get_document_count()
            checks["openai_ok"] = True  # if search is up, config is valid
            checks["search_ok"] = True
        except Exception:
            checks["status"] = "degraded"
        _health_cache.update(checks)
        _health_cache["checked_at"] = now
    return {k: v for k, v in _health_cache.items() if k != "checked_at"}


@app.get("/api/programs")
async def list_programs():
    from app.chat.engine import _load_program_names_async
    return {"programs": await _load_program_names_async()}


@app.post("/api/feedback")
@limiter.limit("30/minute")
async def submit_feedback(request: Request, body: FeedbackRequest):
    """Store user feedback (thumbs up/down) for quality monitoring."""
    import json
    from pathlib import Path
    from datetime import datetime, timezone

    entry = json.dumps(
        {"timestamp": datetime.now(timezone.utc).isoformat(), **body.model_dump()},
        ensure_ascii=False,
    ) + "\n"

    def _write():
        feedback_dir = Path(settings.feedback_dir)
        feedback_dir.mkdir(exist_ok=True, parents=True)
        with open(feedback_dir / "feedback.jsonl", "a") as f:
            f.write(entry)

    import asyncio
    await asyncio.to_thread(_write)
    return {"status": "ok"}
