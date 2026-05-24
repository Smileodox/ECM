from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.responses import JSONResponse

from app.config import settings
from app.routers import chat, ingest

limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])

app = FastAPI(title="campusLMU Chatbot API", version="2.0.0")
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Zu viele Anfragen. Bitte warte einen Moment."},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")


@app.get("/api/health")
async def health():
    """Health check with dependency probing."""
    checks = {"status": "ok", "openai_ok": False, "search_ok": False}
    try:
        from openai import AsyncAzureOpenAI
        client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
        )
        await client.models.list()
        checks["openai_ok"] = True
    except Exception:
        checks["status"] = "degraded"

    try:
        from azure.core.credentials import AzureKeyCredential
        from azure.search.documents.aio import SearchClient
        async with SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index_name,
            credential=AzureKeyCredential(settings.azure_search_key),
        ) as client:
            await client.get_document_count()
        checks["search_ok"] = True
    except Exception:
        checks["status"] = "degraded"

    return checks


@app.get("/api/programs")
async def list_programs():
    from app.chat.engine import _load_program_names
    return {"programs": _load_program_names()}


@app.post("/api/feedback")
async def submit_feedback(request: Request):
    """Store user feedback (thumbs up/down) for quality monitoring."""
    import json
    from pathlib import Path
    from datetime import datetime, timezone

    body = await request.json()
    feedback_dir = Path("feedback")
    feedback_dir.mkdir(exist_ok=True)

    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message_id": body.get("message_id", ""),
        "rating": body.get("rating", ""),  # "up" or "down"
        "comment": body.get("comment", ""),
        "query": body.get("query", ""),
    }

    feedback_file = feedback_dir / "feedback.jsonl"
    with open(feedback_file, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return {"status": "ok"}
