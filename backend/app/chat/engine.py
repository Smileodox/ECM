import json
import logging
from collections.abc import AsyncGenerator

from openai import AzureOpenAI

from app.chat.citations import extract_used_citation_indices, normalize_citation_markers
from app.chat.prompts import SYSTEM_PROMPT, build_context, build_user_prompt
from app.config import settings
from app.models import ChatMessage, Citation
from app.search.retriever import retrieve

logger = logging.getLogger(__name__)


def _get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


async def chat_stream(
    message: str,
    history: list[ChatMessage],
) -> AsyncGenerator[dict, None]:
    """Stream a RAG-augmented chat response.

    Yields dicts with 'event' and 'data' keys for sse-starlette.
    """
    # 1. Retrieve relevant chunks
    citations = retrieve(message)

    if not citations:
        yield _sse("token", {"content": "Dazu habe ich leider keine Information in den mir vorliegenden Dokumenten gefunden. Bitte wende dich an die Zentrale Studienberatung oder das Prüfungsamt."})
        yield _sse("citations", {"citations": []})
        yield _sse("done", {})
        return

    # 2. Build prompt with context
    context = build_context(citations)
    user_prompt = build_user_prompt(context, message)

    # 3. Build messages array with history
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history[-6:]:  # Keep last 6 messages for context window management
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_prompt})

    # 4. Stream from Azure OpenAI
    client = _get_openai_client()
    full_response = ""

    try:
        stream = client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
            stream=True,
        )

        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                yield _sse("token", {"content": token})

    except Exception as e:
        logger.exception("Error during chat streaming")
        yield _sse("error", {"message": str(e)})
        return

    # 5. Normalize citation markers and send metadata
    used_indices = extract_used_citation_indices(full_response)
    normalized_content = normalize_citation_markers(full_response)
    used_citations = [
        {
            "index": c.index,
            "section_id": c.section_id,
            "section_title": c.section_title,
            "absatz": c.absatz,
            "page_number": c.page_number,
            "doc_name": c.doc_name,
            "source_url": c.source_url,
            "content": c.content,
        }
        for c in citations
        if c.index in used_indices
    ]

    yield _sse("citations", {"citations": used_citations, "normalized_content": normalized_content})
    yield _sse("done", {})


def _sse(event: str, data: dict) -> dict:
    """Format an SSE event dict for sse-starlette."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
