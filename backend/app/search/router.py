"""Query router: classifies queries as REGULATION, GENERAL, or BOTH.

Determines which search index(es) to query for a given user question.
"""
from __future__ import annotations

import logging
import re
from enum import Enum

import httpx
from openai import AsyncAzureOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class QueryRoute(str, Enum):
    REGULATION = "regulation"
    GENERAL = "general"
    BOTH = "both"


_REGULATION_KEYWORDS = re.compile(
    r"(?:prüfung(?:s(?:ordnung|amt))?|studienordnung|ects|modul(?:plan|katalog|handbuch)?"
    r"|masterarbeit|bachelorarbeit|regelstudienzeit|eignung(?:s(?:satzung|verfahren|prüfung))?"
    r"|zulassungsordnung|änderungssatzung|anrechnung|wiederholung|klausur|pflicht(?:modul)?"
    r"|wahlpflicht|thesis|exam\b|credit|psto|satzung|notenberechnung"
    r"|schwerpunkt(?:fach)?|vertiefung|studienplan"
    r"|§\s*\d)",
    re.IGNORECASE,
)

_GENERAL_KEYWORDS = re.compile(
    r"(?:rückmeldung|exmatrikulation|beiträge|gebühren|semesterticket"
    r"|krankenversicherung|beurlaubung|bibliothek|lmucard|studienberatung"
    r"|datenschutz|stundenplan|fachschaft|studierendenvertretung"
    r"|immatrikulation(?!shindernisse)|adresse|adressänderung"
    r"|semesterbeitrag|finanzierung|stipendium|wohn(?:en|ung)"
    r"|career\s*service|auslandsstudium|erasmus|lmuexchange"
    r"|unfallversicherung|rentenversicherung|vorlesungsverzeichnis"
    r"|vorlesungszeit(?:en)?|semestertermin|frühstudi"
    r"|seniorenstudium|gaststudierende|zweitstudium|doppelstudium"
    r"|promotionsstudium|lehramt|quereinstieg|ortswechsel"
    r"|behinderung|beeinträchtigung|kind\b|eltern"
    r"|online.?selbstbedienung|bescheinigung(?:en)?)",
    re.IGNORECASE,
)

_BOTH_KEYWORDS = re.compile(
    r"(?:fachwechsel|studiengangswechsel|höherstufung|bewerbung|zulass(?:ung|ungsbeschränk)"
    r"|hochschulzugang|anerkennung|transcript)",
    re.IGNORECASE,
)

_ROUTER_SYSTEM = (
    "You classify student questions at LMU Munich into categories for search routing.\n\n"
    "REGULATION — about specific exam/study regulations (PSTO, Eignungssatzung, Zulassungsordnung), "
    "specific program requirements, ECTS, thesis rules, paragraph numbers (§), module structure, grades.\n\n"
    "GENERAL — about administrative procedures, fees, enrollment, re-registration, deadlines, "
    "campus services, student ID, libraries, health insurance, semester ticket, study abroad, "
    "career services, student representation, documents/certificates, financial aid, disability support.\n\n"
    "BOTH — questions that clearly need BOTH regulation details AND administrative/procedural info. "
    "Examples: changing your major (needs both the process AND the regulation requirements), "
    "admission requirements (needs both the Zulassungsordnung AND the application process).\n\n"
    "Reply with ONLY one word: REGULATION, GENERAL, or BOTH."
)


async def classify_query(query: str) -> QueryRoute:
    """Classify a query into a routing category. Uses keyword fast-path, falls back to LLM."""
    has_regulation = bool(_REGULATION_KEYWORDS.search(query))
    has_general = bool(_GENERAL_KEYWORDS.search(query))
    has_both = bool(_BOTH_KEYWORDS.search(query))

    if has_both:
        return QueryRoute.BOTH
    if has_regulation and not has_general:
        return QueryRoute.REGULATION
    if has_general and not has_regulation:
        return QueryRoute.GENERAL
    if has_regulation and has_general:
        return QueryRoute.BOTH

    return await _llm_classify(query)


async def _llm_classify(query: str) -> QueryRoute:
    try:
        client = AsyncAzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        response = await client.chat.completions.create(
            model=settings.azure_openai_mini_deployment,
            messages=[
                {"role": "system", "content": _ROUTER_SYSTEM},
                {"role": "user", "content": query},
            ],
            temperature=0,
            max_completion_tokens=5,
        )
        answer = response.choices[0].message.content.strip().upper()
        if answer.startswith("REGULATION"):
            return QueryRoute.REGULATION
        if answer.startswith("GENERAL"):
            return QueryRoute.GENERAL
        if answer.startswith("BOTH"):
            return QueryRoute.BOTH
        logger.warning("Unexpected router LLM response: %s — defaulting to BOTH", answer)
        return QueryRoute.BOTH
    except Exception:
        logger.warning("Router LLM failed, defaulting to BOTH", exc_info=True)
        return QueryRoute.BOTH
