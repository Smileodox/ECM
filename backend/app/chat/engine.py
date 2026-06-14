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

from app.chat.citations import extract_used_citation_indices, normalize_citation_markers, strip_for_display
from app.chat.escalation import (
    ESCALATION_CONTACTS,
    FSB_OVERVIEW_URL,
    PRUEFUNGSAMT_OVERVIEW_URL,
    get_fsb_url,
    get_pruefungsamt_url,
)
from app.chat.few_shot import classify_query
from app.chat.grounding import verify_grounding
from app.chat.prompts import (
    build_advisory_disclaimer,
    build_context,
    build_grounding_retraction,
    build_low_confidence_notice,
    build_no_info_fallback,
    build_system_prompt,
    build_user_prompt,
    detect_response_language,
    short_doc_label,
)
from app.config import settings
from app.models import ChatMessage, Citation
from app.search.retriever import RetrievalResult, retrieve, retrieve_web, retrieve_combined
from app.search.router import QueryRoute, classify_route

logger = logging.getLogger(__name__)

_PROGRAM_NAMES: list[str] | None = None
_enc = tiktoken.get_encoding("o200k_base")
MAX_CONTEXT_TOKENS = 8000
RESPONSE_TOKEN_RESERVE = 2500

_REGULATION_DOC_TYPES = frozenset({"psto", "eignung", "zulassung", "aenderung"})


def _audit_turn(request_id: str, decision: str, **fields) -> None:
    """Emit one structured decision record per turn — the legal audit trail.

    JSON-logged (see main.py); no answer text / PII, only decision metadata and the
    cited section ids, which is what an audit needs.
    """
    extra = {"audit": "chat_turn", "request_id": request_id, "decision": decision}
    extra.update({k: v for k, v in fields.items() if v is not None})
    logger.info("chat_turn", extra=extra)


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
    "statistics and data science": "Statistics and Data Science",
    "mathematics": "Mathematik",
    "financial and actuarial mathematics": "Finanz- und Versicherungsmathematik",
    "actuarial mathematics": "Finanz- und Versicherungsmathematik",
    "physics": "Physik",
    "astrophysics": "Astrophysics",
    "theoretical and mathematical physics": "Theoretical and Mathematical Physics",
    "chemistry": "Chemie",
    "biochemistry": "Biochemie",
    "biology": "Biologie",
    "molecular biology": "Molekulare Biologie",
    "molecular and cellular biology": "Molecular and Cellular Biology",
    "ecology": "Ökologie",
    "evolution, ecology and systematics": "Evolution, Ecology and Systematics",
    "plant sciences": "Plant Sciences",
    "geology": "Geologie",
    "engineering geology": "Ingenieur- und Hydrogeologie",
    "hydrogeology": "Ingenieur- und Hydrogeologie",
    "geobiology and paleobiology": "Geobiology and Paleobiology",
    "geomaterials and geochemistry": "Geomaterials and Geochemistry",
    "geophysics": "Geophysik",
    "meteorology": "Meteorologie",
    "statistics": "Statistik",
    "software engineering": "Software Engineering",
    "human-computer interaction": "Mensch-Computer-Interaktion",
    "hci": "Mensch-Computer-Interaktion",
    # Social sciences & humanities
    "law": "Rechtswissenschaften",
    "political science": "Politikwissenschaft",
    "philosophy": "Philosophie",
    "ancient philosophy": "Antike Philosophie",
    "theoretical philosophy": "Theoretische Philosophie",
    "logic and philosophy of science": "Logic and Philosophy of Science",
    "philosophy, politics and economics": "Philosophie, Politik und Wirtschaft",
    "ppe": "Philosophie, Politik und Wirtschaft",
    "psychology": "Psychologie",
    "clinical psychology": "Psychologie: Klinische Psychologie und Psychotherapie",
    "psychotherapy": "Psychologie: Klinische Psychologie und Psychotherapie",
    "organizational psychology": "Psychologie: Wirtschafts-, Organisations- und Sozialpsychologie",
    "neuro-cognitive psychology": "Neuro-cognitive Psychology",
    "neurosciences": "Neurosciences",
    "psychology: learning sciences": "Psychology: Learning Sciences and Human Development",
    "sociology": "Soziologie",
    "pedagogy": "Pädagogik",
    "education": "Pädagogik",
    "educational science": "Pädagogik",
    "education research and management": "Pädagogik mit Schwerpunkt Bildungsforschung und Bildungsmanagement",
    "music education": "Musikpädagogik",
    "speech therapy": "Sprachtherapie",
    "deaf education": "Prävention, Inklusion und Rehabilitation (PIR) - Gehörlosenpädagogik",
    "hard of hearing education": "Prävention, Inklusion und Rehabilitation (PIR) - Schwerhörigenpädagogik",
    "pir": "Prävention, Inklusion und Rehabilitation (PIR) - Gehörlosenpädagogik",
    "business education": "Wirtschaftspädagogik I",
    "wirtschaftspädagogik": "Wirtschaftspädagogik I",
    "history": "Geschichte",
    "medieval and renaissance studies": "Mittelalter- und Renaissancestudien",
    "geography": "Geographie",
    "human geography": "Humangeographie",
    "human geography and sustainability": "Human Geography and Sustainability: Monitoring, Modeling and Management",
    "environment and society": "Environment and Society",
    "environmental systems and sustainability": "Umweltsysteme und Nachhaltigkeit - Monitoring, Modellierung und Management",
    "linguistics": "Linguistik",
    "computational linguistics": "Computerlinguistik mit Nebenfach",
    "cultural and cognitive linguistics": "Cultural and Cognitive Linguistics",
    "phonetics": "Phonetik und Sprachverarbeitung",
    "speech processing": "Phonetik und Sprachverarbeitung",
    "german language": "Germanistik",
    "german studies": "Germanistik",
    "german linguistics": "Germanistische Linguistik",
    "german literature": "Germanistische Literaturwissenschaft",
    "german as a foreign language": "Deutsch als Fremdsprache",
    "english studies": "English Studies",
    "anglistics": "Anglistik",
    "romantics": "Romanistik",
    "romance studies": "Romanistik",
    "italian studies": "Italienstudien",
    "comparative literature": "Allgemeine und Vergleichende Literaturwissenschaft",
    "literary translation": "Literarisches Übersetzen",
    "greek philology": "Griechische Philologie",
    "latin philology": "Lateinische Philologie",
    "journalism": "Journalismus",
    "journalism, media and globalisation": "Journalism, Media and Globalisation",
    "strategic communication": "Strategische Kommunikation",
    "communication": "Kommunikationswissenschaft",
    "communication and media research": "Kommunikations- und Medienforschung",
    "media studies": "Medienwissenschaft",
    "film and media culture": "Film- und Medienkultur-Forschung",
    "musicology": "Musikwissenschaft",
    "art history": "Kunstgeschichte",
    "late antique and byzantine art history": "Spätantike und Byzantinische Kunstgeschichte",
    "archaeology": "Archäologie",
    "classical archaeology": "Klassische Archäologie",
    "provincial roman archaeology": "Provinzialrömische Archäologie",
    "prehistoric archaeology": "Vor- und Frühgeschichtliche Archäologie",
    "near eastern archaeology": "Vorderasiatische Archäologie",
    "dramaturgy": "Dramaturgie",
    "theater research": "Theaterforschung und kulturelle Praxis",
    "digital cultural heritage": "Digital Cultural Heritage",
    "ethnology": "Ethnologie",
    "cultural anthropology": "Empirische Kulturwissenschaft und Europäische Ethnologie",
    "european ethnology": "Empirische Kulturwissenschaft und Europäische Ethnologie",
    "intercultural communication": "Interkulturelle Kommunikation",
    "religious studies": "Religionswissenschaft",
    "religion and cultural studies": "Religions- und Kulturwissenschaft",
    "religion and philosophy in asia": "Religion und Philosophie in Asien",
    "theology": "Theologie",
    "catholic theology": "Katholische Theologie",
    "protestant theology": "Evangelische Theologie",
    "east european studies": "Osteuropastudien",
    "slavic studies": "Slavistik",
    "scandinavian studies": "Skandinavistik",
    "sinology": "Sinologie",
    "japanese studies": "Japanologie",
    "near and middle east": "Naher und Mittlerer Osten",
    "albanian studies": "Albanologie",
    "ancient oriental studies": "Altorientalistik",
    "byzantine studies": "Byzantinistik",
    "modern greek studies": "Neogräzistik",
    "finno-ugric studies": "Finnougristik",
    "egyptology": "Ägyptologie und Koptologie",
    "coptology": "Ägyptologie und Koptologie",
    "comparative indo-european linguistics": "Vergleichende Indoeuropäische Sprachwissenschaft",
    "book studies": "Buchwissenschaft: Buch- und Medienforschung",
    "publishing": "Buchwissenschaft: Verlagspraxis",
    "american history": "American History, Culture and Society",
    "computational social science": "Computational Social Science",
    # Business & economics
    "business administration": "Betriebswirtschaftslehre",
    "bwl": "Betriebswirtschaftslehre",
    "economics": "Economics",
    "quantitative economics": "Quantitative Economics",
    "vwl": "Volkswirtschaftslehre",
    "management": "Management",
    "management and digital technologies": "Management and Digital Technologies",
    "mdt": "Management and Digital Technologies",
    "mmt": "Management and Digital Technologies",
    "european triple degree": "Master of Science in Management - European Triple Degree",
    "international triple degree": "Master of Science in Management – International Triple Degree",
    "finance": "Finance",
    "insurance": "Insurance",
    "accounting": "Wirtschaftsprüfung",
    # Life sciences & medicine
    "epidemiology": "Epidemiologie",
    "public health": "Public Health",
    "international health": "International Health",
    "human biology": "Human Biology - Principles of Health and Disease",
    "pharmaceutical sciences": "Pharmaceutical Sciences",
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
    program_names = _load_program_names()

    for en_name, de_name in _EN_PROGRAM_MAP.items():
        matched = en_name in msg_lower
        if not matched:
            de_lower = de_name.lower()
            de_pattern = r"(?<![a-zäöüß])" + re.escape(de_lower) + r"(?![a-zäöüß])"
            matched = bool(re.search(de_pattern, msg_lower))
        if matched:
            candidates = [de_name.lower(), en_name.lower()]
            for name in program_names:
                if name.lower() in candidates:
                    return name
            for candidate in candidates:
                for name in program_names:
                    if candidate in name.lower():
                        return name
    for name in program_names:
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
            model=settings.azure_openai_mini_deployment,
            messages=[
                {"role": "system", "content": (
                    "Given a conversation about university programs at LMU Munich, identify which specific program the user is asking about. "
                    "Match abbreviations, informal names, and partial names to the correct official program name.\n"
                    "IMPORTANT: Match the MOST SPECIFIC program name. Do NOT confuse similar-sounding programs. "
                    "For example, 'Management and Digital Technologies' is NOT the same as 'Umweltsysteme und Nachhaltigkeit'.\n\n"
                    f"Available programs:\n{programs_text}\n\n"
                    "Reply with ONLY the exact program name from the list, or NONE if no specific program is mentioned or identifiable."
                )},
                {"role": "user", "content": conversation},
            ],
            temperature=0,
            max_completion_tokens=100,
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
    "You are a domain classifier for a university student assistant chatbot (LMU Munich). "
    "Decide whether the question is related to studying at LMU Munich — including "
    "study regulations, exams, enrollment, fees, administrative procedures, campus services, "
    "student life, deadlines, program changes, study abroad, career services, "
    "financial aid, disability support, libraries, or any other topic relevant to LMU students. "
    "Answer only with YES or NO. "
    "YES = related to studying at LMU. NO = completely unrelated (e.g. cooking recipes, "
    "general trivia, programming help, weather, sports results)."
)

def _build_off_topic_response(lang: str = "de") -> str:
    if lang == "en":
        return (
            "I am the campusLMU Study Assistant and can help with questions about "
            "studying at LMU — regulations, enrollment, fees, deadlines, campus services, and more. "
            "This question seems outside my scope. Could you rephrase it in relation to your studies?"
        )
    return (
        "Ich bin der campusLMU Studienassistent und helfe bei Fragen rund ums Studium an der LMU — "
        "Prüfungsordnungen, Einschreibung, Gebühren, Fristen, Campusservices und mehr. "
        "Diese Frage scheint außerhalb meines Bereichs zu liegen. Kannst du sie in Bezug auf dein Studium umformulieren?"
    )


_IN_DOMAIN_KEYWORDS = re.compile(
    r"(?:prüfung|studien|ects|modul|semester|masterarbeit|bachelorarbeit|"
    r"regelstudienzeit|eignung|zulassung|änderung|anrechnung|immatrikulation|"
    r"wiederholung|klausur|pflicht|wahlpflicht|thesis|exam|credit|admission|"
    r"eligibility|enrollment|psto|studienordnung|prüfungsordnung|satzung|"
    r"studiengang|abschluss|diplom|bachelor|master|§\s*\d"
    r"|rückmeldung|exmatrikulation|beiträge|gebühren|semesterticket"
    r"|krankenversicherung|beurlaubung|bibliothek|lmucard|studienberatung"
    r"|datenschutz|stundenplan|fachschaft|studierendenvertretung"
    r"|adresse|adressänderung|semesterbeitrag|finanzierung|stipendium"
    r"|career\s*service|ausland|erasmus|lmuexchange"
    r"|unfallversicherung|vorlesungsverzeichnis|vorlesungszeit"
    r"|semestertermin|seniorenstudium|gaststudierende|zweitstudium"
    r"|doppelstudium|promotion|lehramt|quereinstieg|ortswechsel"
    r"|behinderung|beeinträchtigung|bescheinigung|fachwechsel"
    r"|hochschulzugang|bewerbung|uni|universität|lmu"
    r"|wohnung|wohnen|wohnheim|studierendenwerk|mensa|bafög|bafoeg"
    r"|eduroam|wlan|wifi|vpn|it.?service|lmu.?account"
    r"|housing|dormitory|cafeteria|financial\s*aid"
    r"|visa|aufenthalts|international\s*office"
    r"|get\s*in(?:to)?|apply|application|program(?:me)?|degree|course|module"
    r"|tuition|registration|re.?register|gpa|grade|prerequisite|requirement"
    r"|how\s*(?:do|can|to)|deadline|fee|schedule|lecture|curriculum"
    r"|study|studying|student|university|campus)",
    re.IGNORECASE,
)


async def _is_in_domain(query: str) -> bool:
    """Return True if query is about university regulations; fail-open on error."""
    if _IN_DOMAIN_KEYWORDS.search(query):
        return True

    client = _get_openai_client()
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_mini_deployment,
            messages=[
                {"role": "system", "content": _DOMAIN_CLASSIFIER_SYSTEM},
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_completion_tokens=5,
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
            model=settings.azure_openai_mini_deployment,
            messages=[
                {"role": "system", "content": "Rewrite the user's follow-up question as a standalone question that includes all necessary context from the conversation history. Only output the rewritten question, nothing else. If the question is already standalone, return it unchanged. Keep the same language as the original question. Preserve all legal references exactly as written (e.g., §14 Abs. 3, Ziff. 2, Nr. 1). Preserve program names (Studiengangbezeichnungen) exactly. IMPORTANT: Preserve the user's actual intent — if they ask about something NEW (e.g. curriculum, modules, grading) that differs from the previous topic (e.g. admission), do NOT fold the new question back into the old topic. Only add context like the program name, not the previous topic."},
                {"role": "user", "content": f"Conversation:\n{history_text}\n\nFollow-up: {message}"},
            ],
            temperature=0,
            max_completion_tokens=200,
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
    budget = settings.model_context_limit - system_tokens - context_tokens - RESPONSE_TOKEN_RESERVE
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
    model_name: str | None = None,
    request_id: str = "-",
) -> AsyncGenerator[dict, None]:
    """Stream a RAG-augmented chat response.

    Yields dicts with 'event' and 'data' keys for sse-starlette.
    """
    timing: dict[str, float] = {}
    t_start = time.perf_counter()

    # 1. Domain check + query rewrite + route classification in parallel
    #    Skip domain check on follow-ups — user already established context.
    t0 = time.perf_counter()
    program_was_provided = program_name is not None
    need_domain = not history
    need_rewrite = bool(history)

    coros = {}
    if need_domain:
        coros["domain"] = _is_in_domain(message)
    if need_rewrite:
        coros["rewrite"] = _rewrite_query(message, history)
    coros["route"] = classify_route(message)

    keys = list(coros.keys())
    results_list = await asyncio.gather(*coros.values())
    results_map = dict(zip(keys, results_list))

    in_domain = results_map.get("domain", True)
    search_query = results_map.get("rewrite", message)
    route: QueryRoute = results_map["route"]
    if program_name:
        in_domain = True
    timing["rewrite_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    if not in_domain:
        lang = detect_response_language(message, history)
        yield _sse("token", {"content": _build_off_topic_response(lang)})
        yield _sse("citations", {"citations": []})
        yield _sse("done", {})
        _audit_turn(request_id, "rejected_off_topic", route=route.value, lang=lang)
        return

    # Detect language early so the frontend can localize the program hint
    lang = detect_response_language(message, history)
    yield _sse("language", {"lang": lang})

    # Program detection: only for REGULATION and BOTH routes
    need_program = not program_name  # detect for all routes — used in escalation contact URLs
    if need_program:
        program_name = await _detect_program_from_context(message, history)
    if program_name and not program_was_provided:
        yield _sse("detected_program", {"program_name": program_name})

    # 2b. Infer doc_type from query classification (regulation queries only)
    _QUERY_TYPE_TO_DOC_TYPE = {"eligibility": "eignung", "amendment": "aenderung"}
    query_type = classify_query(search_query)
    doc_type = _QUERY_TYPE_TO_DOC_TYPE.get(query_type) if route != QueryRoute.GENERAL else None

    # 3. Retrieve from the appropriate index(es) based on route
    t0 = time.perf_counter()
    if route == QueryRoute.GENERAL:
        result = await retrieve_web(search_query)
    elif route == QueryRoute.BOTH:
        result = await retrieve_combined(
            search_query, doc_type=doc_type, program_name=program_name, query_type=query_type,
        )
        if not result.citations and (doc_type or program_name):
            result = await retrieve_combined(search_query, query_type=query_type)
            result.low_confidence = True
            if result.confidence == "solid":
                result.confidence = "uncertain"  # precise-filter intent failed → less sure
    else:  # REGULATION
        result = await retrieve(search_query, doc_type=doc_type, program_name=program_name, query_type=query_type)
        if doc_type and not result.citations:
            result = await retrieve(search_query, program_name=program_name, query_type=query_type)
            result.low_confidence = True
            if result.confidence == "solid":
                result.confidence = "uncertain"  # precise-filter intent failed → less sure

    timing["retrieve_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    timing["route"] = route.value
    if result.timing:
        timing.update({f"ret_{k}": v for k, v in result.timing.items()})
    citations = result.citations
    confidence = result.confidence

    if not citations:
        lang = detect_response_language(message, history)
        fallback = build_no_info_fallback(
            query=search_query,
            route=route.value,
            query_type=query_type,
            lang=lang,
            program_name=program_name,
        )
        yield _sse("token", {"content": fallback})
        yield _sse("citations", {"citations": []})
        yield _sse("done", {})
        decision = "abstained_low_score" if confidence == "abstain" else "abstained_no_results"
        _audit_turn(
            request_id, decision, route=route.value, query_type=query_type,
            program_name=program_name, lang=lang, confidence=confidence,
            top_score=round(result.top_score, 3), num_citations=0, timing=timing,
        )
        return

    # 4. Build prompt with context
    context = build_context(citations)

    # Trim context if it exceeds token budget to avoid blowing the model window
    context_tokens_count = _count_tokens(context)
    if context_tokens_count > MAX_CONTEXT_TOKENS:
        trimmed_citations = citations[:]
        while trimmed_citations and _count_tokens(build_context(trimmed_citations)) > MAX_CONTEXT_TOKENS:
            trimmed_citations.pop()  # Remove lowest-ranked (last) citation
        context = build_context(trimmed_citations)
        logger.info("Context trimmed from %d to %d citations to fit budget", len(citations), len(trimmed_citations))
        citations = trimmed_citations

    # Inject program-specific contact URLs so the LLM cites them directly instead
    # of falling back to generic URLs from web citations or the regulations index.
    if program_name:
        contact_hints: list[str] = []
        fsb_url = get_fsb_url(program_name)
        if fsb_url != FSB_OVERVIEW_URL:
            contact_hints.append(f"Fachstudienberatung {program_name}: {fsb_url}")
        pa_url = get_pruefungsamt_url(program_name)
        if pa_url != PRUEFUNGSAMT_OVERVIEW_URL:
            contact_hints.append(f"Prüfungsamt {program_name}: {pa_url}")
        if contact_hints:
            context += "\n\n---\n\n**Programmspezifische Anlaufstellen:**\n" + "\n".join(
                f"- {h}" for h in contact_hints
            )

    # Note: low-confidence is surfaced as a VISIBLE uncertainty notice + a constrained
    # system prompt below — not buried as a context hint the model can ignore.
    user_prompt = build_user_prompt(context, search_query)

    # 5. Build messages array with token-aware history trimming
    content_types = {c.doc_type for c in citations}
    system_prompt = build_system_prompt(
        message, history,
        content_types=content_types,
        route=route.value,
        query_type=query_type,
        program_name=program_name,
        confidence=confidence,
    )
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
            "doc_name": short_doc_label(c) if c.doc_type not in ("web_1x1", "studienangebot") else c.doc_name,
            "doc_type": c.doc_type,
        }
        for c in citations
    }
    yield _sse("pre_citations", {"citation_map": pre_citation_map})

    from app.chat.providers import resolve_model, stream_chat
    resolved_model = resolve_model(model_name)
    full_response = ""

    # 6b. UNCERTAIN band: lead with a visible uncertainty notice. Part of full_response
    #     so it survives client-side normalization (no [Quelle N] markers inside it).
    if confidence == "uncertain":
        notice = build_low_confidence_notice(
            query=search_query, route=route.value, query_type=query_type,
            lang=lang, program_name=program_name,
        )
        full_response = notice
        yield _sse("token", {"content": notice})

    # 7. Stream from LLM provider
    try:
        async for token in stream_chat(resolved_model, messages, temperature=0.1, max_tokens=2000):
            full_response += token
            yield _sse("token", {"content": token})

    except Exception as e:
        logger.exception("Error during chat streaming")
        from openai import RateLimitError, APIConnectionError, APITimeoutError
        if isinstance(e, RateLimitError):
            user_msg = "The service is currently overloaded. Please try again in a few seconds."
        elif isinstance(e, (APIConnectionError, APITimeoutError)):
            user_msg = "The server is currently unavailable. Please try again in a few seconds."
        else:
            user_msg = "An error occurred while processing your request. Please try again."
        yield _sse("error", {"message": user_msg})
        _audit_turn(request_id, "error", route=route.value, query_type=query_type,
                    confidence=confidence, lang=lang, timing=timing)
        return

    # 8. Grounding check (regulation turns) — append a retraction if § refs are unsupported
    used_indices = extract_used_citation_indices(full_response)
    verification = "skipped"
    if settings.enable_grounding_check and route in (QueryRoute.REGULATION, QueryRoute.BOTH):
        t_g = time.perf_counter()
        verdict = verify_grounding(full_response, citations, used_indices)
        verification = verdict["verdict"]
        timing["grounding_ms"] = round((time.perf_counter() - t_g) * 1000, 1)
        if verification in ("partially_grounded", "ungrounded"):
            retraction = build_grounding_retraction(
                query=search_query, route=route.value, query_type=query_type,
                lang=lang, program_name=program_name,
            )
            full_response += retraction
            yield _sse("token", {"content": retraction})
            logger.warning("Grounding %s [req=%s]: unsupported=%s", verification, request_id, verdict["unsupported"])

    # 8b. Advisory answers (program selection) are covered by neither the score gate nor
    #     the grounding verifier — guarantee a not-binding disclaimer + hand-off to advising,
    #     unless the model already linked Studienberatung / International Office itself.
    advisory_disclaimer_added = False
    if "studienangebot" in content_types:
        sb_url = ESCALATION_CONTACTS["studienberatung"]["url"]
        io_urls = (ESCALATION_CONTACTS["international"]["url"], ESCALATION_CONTACTS["international"]["url_en"])
        has_referral = sb_url in full_response or any(u in full_response for u in io_urls)
        has_io = any(u in full_response for u in io_urls)
        want_io = lang == "en"  # international applicants should also see the International Office
        if not has_referral or (want_io and not has_io):
            disclaimer = build_advisory_disclaimer(
                lang=lang, include_international=want_io, referral_present=has_referral,
            )
            full_response += disclaimer
            yield _sse("token", {"content": disclaimer})
            advisory_disclaimer_added = True

    # 9. Normalize citation markers and send metadata
    normalized_content = normalize_citation_markers(full_response)
    used_citations = [
        {
            "index": c.index,
            "section_id": c.section_id,
            "section_title": c.section_title,
            "absatz": c.absatz,
            "page_number": c.page_number,
            "doc_name": short_doc_label(c) if c.doc_type not in ("web_1x1", "studienangebot") else c.doc_name,
            "source_url": c.source_url,
            "content": strip_for_display(c.content),
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
    yield _sse("metrics", {**timing, "confidence": confidence, "verification": verification})
    yield _sse("done", {})

    cited_sections = sorted({c.section_id for c in citations if c.index in used_indices and c.section_id})
    _audit_turn(
        request_id, "answered_uncertain" if confidence == "uncertain" else "answered_solid",
        route=route.value, query_type=query_type, program_name=program_name, lang=lang,
        model=resolved_model, confidence=confidence, top_score=round(result.top_score, 3),
        num_citations=len(used_citations), cited_sections=cited_sections,
        verification=verification, advisory=advisory_disclaimer_added, timing=timing,
    )


def _sse(event: str, data: dict) -> dict:
    """Format an SSE event dict for sse-starlette."""
    return {"event": event, "data": json.dumps(data, ensure_ascii=False)}
