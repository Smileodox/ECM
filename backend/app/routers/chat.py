from fastapi import APIRouter, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sse_starlette.sse import EventSourceResponse

from app.chat.engine import chat_stream
from app.models import ChatRequest

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)

MAX_MESSAGE_LENGTH = 2000
MAX_HISTORY_LENGTH = 50


@router.post("/chat")
@limiter.limit("10/minute")
async def chat(request: Request, body: ChatRequest):
    """Stream a RAG-augmented chat response via Server-Sent Events."""
    if len(body.message) > MAX_MESSAGE_LENGTH:
        raise HTTPException(status_code=400, detail=f"Message too long (max {MAX_MESSAGE_LENGTH} characters)")
    if len(body.history) > MAX_HISTORY_LENGTH:
        body.history = body.history[-MAX_HISTORY_LENGTH:]

    async def event_generator():
        async for event in chat_stream(body.message, body.history, program_name=body.program_name):
            yield event

    return EventSourceResponse(
        event_generator(),
        media_type="text/event-stream",
    )
