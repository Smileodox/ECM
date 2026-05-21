from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from app.chat.engine import chat_stream
from app.models import ChatRequest

router = APIRouter()


@router.post("/chat")
async def chat(request: ChatRequest):
    """Stream a RAG-augmented chat response via Server-Sent Events."""

    async def event_generator():
        async for event in chat_stream(request.message, request.history):
            yield event

    return EventSourceResponse(
        event_generator(),
        media_type="text/event-stream",
    )
