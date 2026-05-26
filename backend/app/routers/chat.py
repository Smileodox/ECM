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
        raise HTTPException(status_code=400, detail=f"Message too long (max {MAX_MESSAGE_LENGTH} characters)")
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
            yield {"event": "error", "data": json.dumps({"message": "The request took too long. Please try again."}, ensure_ascii=False)}
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("SSE stream error")
            yield {"event": "error", "data": json.dumps({"message": f"Error: {type(exc).__name__}: {exc}"}, ensure_ascii=False)}

    return EventSourceResponse(
        event_generator(),
        media_type="text/event-stream",
    )
