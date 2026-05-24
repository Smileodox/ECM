import json
import logging
import re
import time
from collections.abc import AsyncGenerator
from functools import lru_cache

import tiktoken
from openai import AsyncAzureOpenAI

from app.chat.citations import extract_used_citation_indices, normalize_citation_markers
from app.chat.prompts import build_context, build_system_prompt, build_user_prompt
from app.config import settings
from app.models import ChatMessage, Citation
from app.search.retriever import RetrievalResult, retrieve

logger = logging.getLogger(__name__)

_PROGRAM_NAMES: list[str] | None = None
_enc = tiktoken.get_encoding("cl100k_base")


@lru_cache(maxsize=1)
def _get_openai_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def _load_program_names() -> list[str]:
    global _PROGRAM_NAMES
    if _PROGRAM_NAMES is not None:
        return _PROGRAM_NAMES
    import json as _json
    from pathlib import Path
    manifest_path = Path(settings.documents_dir) / "manifest.json"
    if manifest_path.exists():
        data = _json.loads(manifest_path.read_text())
        names = set()
        for entry in data.get("entries", []):
            names.update(entry.get("programs", []))
        _PROGRAM_NAMES = sorted(names, key=len, reverse=True)
    else:
        _PROGRAM_NAMES = []
    return _PROGRAM_NAMES


_EN_PROGRAM_MAP = {
    "computer science": "Informatik",
    "business administration": "Betriebswirtschaftslehre",
    "economics": "Volkswirtschaftslehre",
    "mathematics": "Mathematik",
    "physics": "Physik",
    "chemistry": "Chemie",
    "biology": "Biologie",
    "law": "Rechtswissenschaften",
    "political science": "Politikwissenschaft",
    "media informatics": "Medieninformatik",
    "bioinformatics": "Bioinformatik",
    "data science": "Data Science",
    "statistics": "Statistik",
    "philosophy": "Philosophie",
    "psychology": "Psychologie",
    "sociology": "Soziologie",
    "pedagogy": "Pädagogik",
    "education": "Pädagogik",
    "history": "Geschichte",
    "geography": "Geographie",
    "human geography": "Humangeographie",
}


def _detect_program(message: str) -> str | None:
    msg_lower = message.lower()
    for en_name, de_name in _EN_PROGRAM_MAP.items():
        if en_name in msg_lower:
            de_lower = de_name.lower()
            for name in _load_program_names():
                if name.lower() == de_lower:
                    return name
            for name in _load_program_names():
                if de_lower in name.lower():
                    return name
    for name in _load_program_names():
        pattern = r"(?<![a-zäöüß])" + re.escape(name.lower()) + r"(?![a-zäöüß])"
        if re.search(pattern, msg_lower):
            return name
    return None



_RESET_KEYWORDS = ("allgemein", "generell", "anderer studiengang", "anderen studiengang", "andere fakultät", "alle studiengänge")
_MAX_CONTEXT_LOOKBACK = 4


def _wants_context_reset(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _RESET_KEYWORDS)


def _detect_program_from_context(message: str, history: list[ChatMessage]) -> str | None:
    if _wants_context_reset(message):
        return None
    detected = _detect_program(message)
    if detected:
        return detected
    seen = 0
    for msg in reversed(history):
        if msg.role == "user":
            detected = _detect_program(msg.content)
            if detected:
                return detected
            seen += 1
            if seen >= _MAX_CONTEXT_LOOKBACK:
                break
    return None



async def _rewrite_query(message: str, history: list[ChatMessage]) -> str:
    if not history:
        return message
    client = _get_openai_client()
    recent = history[-6:]
    history_text = "\n".join(f"{m.role}: {m.content[:200]}" for m in recent)
    response = await client.chat.completions.create(
        model=settings.azure_openai_mini_deployment,
        messages=[
            {"role": "system", "content": "Rewrite the user's follow-up question as a standalone question that includes all necessary context from the conversation history. Only output the rewritten question, nothing else. If the question is already standalone, return it unchanged. Keep the same language as the original question. Preserve all legal references exactly as written (e.g., §14 Abs. 3, Ziff. 2, Nr. 1). Preserve program names (Studiengangbezeichnungen) exactly."},
            {"role": "user", "content": f"Conversation:\n{history_text}\n\nFollow-up: {message}"},
        ],
        temperature=0,
        max_tokens=200,
    )
    rewritten = response.choices[0].message.content.strip()
    logger.info("Query rewrite: '%s' → '%s'", message[:60], rewritten[:60])
    return rewritten


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _trim_history(history: list[ChatMessage], system_tokens: int, context_tokens: int) -> list[ChatMessage]:
    budget = 128_000 - system_tokens - context_tokens - 2500
    trimmed: list[ChatMessage] = []
    used = 0
    for msg in reversed(history):
        msg_tokens = _count_tokens(msg.content) + 4
        if used + msg_tokens > budget:
            break
        trimmed.insert(0, msg)
        used += msg_tokens
    return trimmed


async def chat_stream(
    message: str,
    history: list[ChatMessage],
    program_name: str | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream a RAG-augmented chat response.

    Yields dicts with 'event' and 'data' keys for sse-starlette.
    """
    timing: dict[str, float] = {}
    t_start = time.perf_counter()

    # 1. Rewrite follow-up queries to be standalone
    t0 = time.perf_counter()
    search_query = (await _rewrite_query(message, history)) if history else message
    timing["rewrite_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    # 2. Detect filters from query + history
    if not program_name:
        program_name = _detect_program_from_context(search_query, history)
    # 3. Retrieve relevant chunks (includes HyDE, dual-search, RRF, neighbor expansion)
    t0 = time.perf_counter()
    result = await retrieve(search_query, program_name=program_name)
    timing["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if result.timing:
        timing.update({f"ret_{k}": v for k, v in result.timing.items()})
    citations = result.citations

    if not citations:
        msg = "Dazu habe ich leider keine Information in den mir vorliegenden Dokumenten gefunden. Bitte wende dich an die Zentrale Studienberatung oder das Prüfungsamt."
        yield _sse("token", {"content": msg})
        yield _sse("citations", {"citations": []})
        yield _sse("done", {})
        return

    # 4. Build prompt with context
    context = build_context(citations)
    if result.low_confidence:
        context = "**Hinweis: Die folgenden Quellen haben nur eine geringe Relevanz zur Anfrage. Die Antwort könnte unvollständig sein.**\n\n" + context
    user_prompt = build_user_prompt(context, message)

    # 5. Build messages array with token-aware history trimming
    system_prompt = build_system_prompt(message)
    system_tokens = _count_tokens(system_prompt)
    context_tokens = _count_tokens(user_prompt)
    trimmed_history = _trim_history(history, system_tokens, context_tokens)

    messages = [{"role": "system", "content": system_prompt}]
    for msg in trimmed_history:
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": user_prompt})

    # 6. Send preliminary citation map so frontend can render chips during streaming
    pre_citation_map = {
        c.index: {
            "index": c.index,
            "section_id": c.section_id,
            "section_title": c.section_title,
            "absatz": c.absatz,
            "doc_name": c.doc_name,
            "doc_type": c.doc_type,
        }
        for c in citations
    }
    yield _sse("pre_citations", {"citation_map": pre_citation_map})

    # 7. Stream from Azure OpenAI
    client = _get_openai_client()
    full_response = ""

    try:
        stream = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=messages,
            temperature=0.1,
            max_tokens=2000,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                token = chunk.choices[0].delta.content
                full_response += token
                yield _sse("token", {"content": token})

    except Exception as e:
        logger.exception("Error during chat streaming")
        yield _sse("error", {"message": str(e)})
        return

    # 7. Normalize citation markers and send metadata
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
            "doc_type": c.doc_type,
        }
        for c in citations
        if c.index in used_indices
    ]

    yield _sse("citations", {"citations": used_citations, "normalized_content": normalized_content})

    timing["total_ms"] = round((time.perf_counter() - t_start) * 1000, 1)
    timing["num_citations"] = len(used_citations)
    timing["prompt_tokens"] = system_tokens + context_tokens
    logger.info("Chat stream completed: %s", ", ".join(f"{k}={v}" for k, v in timing.items()))
    yield _sse("metrics", timing)
    yield _sse("done", {})


def _sse(event: str, data: dict) -> dict:
    """Format an SSE event dict for sse-starlette."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
