import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncGenerator
from functools import lru_cache

import httpx
import tiktoken
from openai import AsyncAzureOpenAI

from app.chat.citations import extract_used_citation_indices, normalize_citation_markers
from app.chat.few_shot import classify_query
from app.chat.prompts import NO_INFO_FALLBACK, build_context, build_system_prompt, build_user_prompt
from app.config import settings
from app.models import ChatMessage, Citation
from app.search.retriever import RetrievalResult, retrieve

logger = logging.getLogger(__name__)

_PROGRAM_NAMES: list[str] | None = None
_enc = tiktoken.encoding_for_model("gpt-4o")


@lru_cache(maxsize=1)
def _get_openai_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        timeout=httpx.Timeout(60.0, connect=10.0),
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


async def _load_program_names_async() -> list[str]:
    """Non-blocking wrapper — reads manifest in thread pool on first call."""
    import asyncio as _asyncio
    if _PROGRAM_NAMES is not None:
        return _PROGRAM_NAMES
    return await _asyncio.to_thread(_load_program_names)


def invalidate_program_cache() -> None:
    global _PROGRAM_NAMES
    _PROGRAM_NAMES = None
    _program_names_prompt.cache_clear()


_EN_PROGRAM_MAP = {
    # Natural sciences
    "computer science": "Informatik",
    "media informatics": "Medieninformatik",
    "bioinformatics": "Bioinformatik",
    "data science": "Data Science",
    "mathematics": "Mathematik",
    "physics": "Physik",
    "chemistry": "Chemie",
    "biochemistry": "Biochemie",
    "biology": "Biologie",
    "molecular biology": "Molekulare Biologie",
    "ecology": "Ökologie",
    "geology": "Geologie",
    "geophysics": "Geophysik",
    "meteorology": "Meteorologie",
    "statistics": "Statistik",
    "astrophysics": "Astrophysik",
    # Social sciences & humanities
    "law": "Rechtswissenschaften",
    "political science": "Politikwissenschaft",
    "philosophy": "Philosophie",
    "psychology": "Psychologie",
    "sociology": "Soziologie",
    "pedagogy": "Pädagogik",
    "education": "Pädagogik",
    "educational science": "Pädagogik",
    "history": "Geschichte",
    "geography": "Geographie",
    "human geography": "Humangeographie",
    "linguistics": "Linguistik",
    "german language": "Germanistik",
    "german studies": "Germanistik",
    "english studies": "Anglistik",
    "anglistics": "Anglistik",
    "romantics": "Romanistik",
    "romance studies": "Romanistik",
    "journalism": "Journalismus",
    "communication": "Kommunikationswissenschaft",
    "media studies": "Medienwissenschaft",
    "musicology": "Musikwissenschaft",
    "art history": "Kunstgeschichte",
    "archaeology": "Archäologie",
    "ethnology": "Ethnologie",
    "religious studies": "Religionswissenschaft",
    "theology": "Theologie",
    "catholic theology": "Katholische Theologie",
    "protestant theology": "Evangelische Theologie",
    # Business & economics
    "business administration": "Betriebswirtschaftslehre",
    "bwl": "Betriebswirtschaftslehre",
    "economics": "Volkswirtschaftslehre",
    "vwl": "Volkswirtschaftslehre",
    "management": "Management",
    "finance": "Finance",
    "accounting": "Wirtschaftsprüfung",
    # Life sciences & medicine
    "pharmacy": "Pharmazie",
    "veterinary medicine": "Tiermedizin",
    "veterinary": "Tiermedizin",
    "medicine": "Medizin",
    "dentistry": "Zahnmedizin",
    "sport science": "Sportwissenschaft",
    "sports": "Sportwissenschaft",
    "nursing": "Pflege",
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



_RESET_KEYWORDS = ("anderer studiengang", "anderen studiengang", "andere fakultät", "alle studiengänge")
_MAX_CONTEXT_LOOKBACK = 4


def _wants_context_reset(message: str) -> bool:
    lower = message.lower()
    return any(kw in lower for kw in _RESET_KEYWORDS)


async def _detect_program_from_context(message: str, history: list[ChatMessage]) -> str | None:
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
    return await _llm_resolve_program(message, history)


@lru_cache(maxsize=1)
def _program_names_prompt() -> str:
    return "\n".join(_load_program_names())


async def _llm_resolve_program(message: str, history: list[ChatMessage]) -> str | None:
    programs_text = _program_names_prompt()
    context_msgs = [f"{m.role}: {m.content[:300]}" for m in history[-4:]]
    context_msgs.append(f"user: {message}")
    conversation = "\n".join(context_msgs)
    client = _get_openai_client()
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": (
                    "Given a conversation about university programs at LMU Munich, identify which specific program the user is asking about. "
                    "Match abbreviations, informal names, and partial names to the correct official program name.\n\n"
                    f"Available programs:\n{programs_text}\n\n"
                    "Reply with ONLY the exact program name from the list, or NONE if no specific program is mentioned or identifiable."
                )},
                {"role": "user", "content": conversation},
            ],
            temperature=0,
            max_tokens=100,
        )
        result = response.choices[0].message.content.strip()
        if result == "NONE" or not result:
            return None
        for name in _load_program_names():
            if name.lower() == result.lower():
                return name
            if name.lower() in result.lower():
                return name
        return None
    except Exception:
        logger.warning("LLM program resolution failed", exc_info=True)
        return None


_DOMAIN_CLASSIFIER_SYSTEM = (
    "You are a domain classifier for a university regulation chatbot (LMU Munich). "
    "Decide whether the question is about university regulations — Prüfungs- und Studienordnungen (PSTO), "
    "Eignungssatzungen, Zulassungsordnungen, Änderungssatzungen, exam rules, study programs, "
    "ECTS credits, thesis requirements, admission requirements, or similar academic/legal topics "
    "related to LMU programs. Answer only with YES or NO. "
    "YES = in domain. NO = off-topic (e.g. Mensa, housing, IT support, sports, personal advice)."
)

_OFF_TOPIC_RESPONSE = (
    "Ich bin der campusLMU Studienassistent und beantworte ausschließlich Fragen zu "
    "Prüfungs- und Studienordnungen, Eignungssatzungen und Zulassungsordnungen. "
    "Für andere Anliegen wende dich bitte an die zuständige Stelle der LMU."
)


async def _is_in_domain(query: str) -> bool:
    """Return True if query is about university regulations; fail-open on error."""
    client = _get_openai_client()
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": _DOMAIN_CLASSIFIER_SYSTEM},
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_tokens=5,
        )
        answer = response.choices[0].message.content.strip().upper()
        in_domain = not answer.startswith("NO")
        if not in_domain:
            logger.info("Domain classifier rejected query: '%s'", query[:60])
        return in_domain
    except Exception:
        logger.warning("Domain classifier failed, defaulting to in-domain", exc_info=True)
        return True


async def _rewrite_query(message: str, history: list[ChatMessage]) -> str:
    if not history:
        return message
    client = _get_openai_client()
    recent = history[-6:]
    max_msg_tokens = 150
    parts = []
    for m in recent:
        tokens = _enc.encode(m.content)
        truncated = _enc.decode(tokens[:max_msg_tokens]) if len(tokens) > max_msg_tokens else m.content
        parts.append(f"{m.role}: {truncated}")
    history_text = "\n".join(parts)
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": "Rewrite the user's follow-up question as a standalone question that includes all necessary context from the conversation history. Only output the rewritten question, nothing else. If the question is already standalone, return it unchanged. Keep the same language as the original question. Preserve all legal references exactly as written (e.g., §14 Abs. 3, Ziff. 2, Nr. 1). Preserve program names (Studiengangbezeichnungen) exactly."},
                {"role": "user", "content": f"Conversation:\n{history_text}\n\nFollow-up: {message}"},
            ],
            temperature=0,
            max_tokens=200,
        )
        rewritten = response.choices[0].message.content.strip()
        logger.debug("Query rewrite: '%s' → '%s'", message[:60], rewritten[:60])
        return rewritten
    except Exception:
        logger.warning("Query rewrite failed, using original message", exc_info=True)
        return message


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _trim_history(history: list[ChatMessage], system_tokens: int, context_tokens: int) -> list[ChatMessage]:
    budget = settings.model_context_limit - system_tokens - context_tokens - 2500
    if budget <= 0:
        logger.warning(
            "Context budget exhausted (system=%d, context=%d, limit=%d), dropping all history",
            system_tokens, context_tokens, settings.model_context_limit,
        )
        return []
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

    # 1. Domain check + query rewrite + program detection in parallel
    #    Skip domain check on follow-ups — user already established context.
    t0 = time.perf_counter()
    program_was_provided = program_name is not None
    need_domain = not history
    need_rewrite = bool(history)
    need_program = not program_name

    coros = {}
    if need_domain:
        coros["domain"] = _is_in_domain(message)
    if need_rewrite:
        coros["rewrite"] = _rewrite_query(message, history)
    if need_program:
        coros["program"] = _detect_program_from_context(message, history)

    keys = list(coros.keys())
    results_list = await asyncio.gather(*coros.values())
    results_map = dict(zip(keys, results_list))

    in_domain = results_map.get("domain", True)
    search_query = results_map.get("rewrite", message)
    if need_program and not program_was_provided:
        program_name = results_map.get("program")
    timing["rewrite_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    if not in_domain:
        yield _sse("token", {"content": _OFF_TOPIC_RESPONSE})
        yield _sse("citations", {"citations": []})
        yield _sse("done", {})
        return

    if program_name and not program_was_provided:
        yield _sse("detected_program", {"program_name": program_name})

    # 2b. Infer doc_type from query classification
    _QUERY_TYPE_TO_DOC_TYPE = {"eligibility": "eignung", "amendment": "aenderung"}
    query_type = classify_query(search_query)
    doc_type = _QUERY_TYPE_TO_DOC_TYPE.get(query_type)

    # 3. Retrieve relevant chunks (includes HyDE, dual-search, RRF, neighbor expansion)
    t0 = time.perf_counter()
    result = await retrieve(search_query, doc_type=doc_type, program_name=program_name)

    # Fallback: if doc_type filter was too restrictive, retry without it
    if doc_type and not result.citations:
        result = await retrieve(search_query, program_name=program_name)
        result.low_confidence = True
    timing["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    if result.timing:
        timing.update({f"ret_{k}": v for k, v in result.timing.items()})
    citations = result.citations

    if not citations:
        yield _sse("token", {"content": NO_INFO_FALLBACK})
        yield _sse("citations", {"citations": []})
        yield _sse("done", {})
        return

    # 4. Build prompt with context
    context = build_context(citations)
    if result.low_confidence:
        context = "**Hinweis: Die folgenden Quellen haben nur eine geringe Relevanz zur Anfrage. Die Antwort könnte unvollständig sein.**\n\n" + context
    user_prompt = build_user_prompt(context, search_query)

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
        from openai import RateLimitError, APIConnectionError, APITimeoutError
        if isinstance(e, RateLimitError):
            user_msg = "Der Dienst ist momentan überlastet. Bitte versuche es in wenigen Sekunden erneut."
        elif isinstance(e, (APIConnectionError, APITimeoutError)):
            user_msg = "Der Server ist momentan nicht erreichbar. Bitte versuche es in wenigen Sekunden erneut."
        else:
            user_msg = "Bei der Verarbeitung deiner Anfrage ist ein Fehler aufgetreten. Bitte versuche es erneut."
        yield _sse("error", {"message": user_msg})
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
    logger.debug("Chat stream completed: %s", ", ".join(f"{k}={v}" for k, v in timing.items()))
    yield _sse("metrics", timing)
    yield _sse("done", {})


def _sse(event: str, data: dict) -> dict:
    """Format an SSE event dict for sse-starlette."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
