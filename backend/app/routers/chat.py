import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from app.chat.engine import chat_stream
from app.limiter import limiter
from app.models import ChatRequest

router = APIRouter()

MAX_MESSAGE_LENGTH = 2000
MAX_HISTORY_LENGTH = 50
STREAM_TIMEOUT_SECONDS = 120


@router.post("/chat")
@limiter.limit("10/minute")
async def chat(request: Request, body: ChatRequest):
    """Stream a RAG-augmented chat response via Server-Sent Events."""
    if len(body.message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail=f"Nachricht zu lang (max {MAX_MESSAGE_LENGTH} Zeichen)")
    if len(body.history) > MAX_HISTORY_LENGTH:
        body.history = body.history[-MAX_HISTORY_LENGTH:]

    async def event_generator():
        try:
            async with asyncio.timeout(STREAM_TIMEOUT_SECONDS):
                async for event in chat_stream(body.message, body.history, program_name=body.program_name):
                    if await request.is_disconnected():
                        return
                    yield event
        except TimeoutError:
            yield {"event": "error", "data": json.dumps({"message": "Die Anfrage hat zu lange gedauert. Bitte versuche es erneut."}, ensure_ascii=False)}

    return EventSourceResponse(
        event_generator(),
        media_type="text/event-stream",
    )
