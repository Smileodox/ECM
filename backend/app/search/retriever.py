import asyncio
import logging
import re
import time
from functools import lru_cache

import tiktoken as _tiktoken

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import AsyncAzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.models import Citation
from app.search.cache import embedding_cache, hyde_cache

logger = logging.getLogger(__name__)

FALLBACK_TOP_K = 5
MAX_CHUNKS_PER_DOC = 3
RRF_K = 60  # standard RRF constant
NEIGHBOR_MAX_TOKENS = 2000

_GERMAN_UMLAUT_PATTERN = re.compile(r"[äöüßÄÖÜ]")
_GERMAN_ARTICLES = re.compile(r"\b(?:der|die|das|und|für|ist|ein|des|den|dem)\b", re.IGNORECASE)

_GERMAN_INDICATOR_WORDS = {
    "prüfung", "prüfungen", "studiengang", "studiengänge", "semester",
    "modul", "module", "leistung", "leistungen", "ordnung", "satzung",
    "studium", "frist", "fristen", "antrag", "arbeit", "pflicht",
    "note", "noten", "wie", "wann", "kann", "muss", "darf",
    "welche", "welcher", "welches", "gibt", "habe", "ich",
    "mich", "sich", "werden", "wurde", "wird", "bei", "nach",
    "noch", "nicht", "auch", "aber", "oder", "wenn", "mit",
    "bis", "zur", "zum", "vom", "von", "aus", "nur",
    "alle", "mein", "meine", "brauche", "bewerben", "bestanden",
    "wiederholung", "masterarbeit", "bachelorarbeit", "klausur",
    "anmeldung", "abmeldung", "zulassung", "eignung",
}

_GERMAN_PROGRAM_NAMES: set[str] | None = None


def _load_german_program_names() -> set[str]:
    global _GERMAN_PROGRAM_NAMES
    if _GERMAN_PROGRAM_NAMES is not None:
        return _GERMAN_PROGRAM_NAMES
    import json as _json
    from app.paths import manifest_path
    mp = manifest_path()
    names: set[str] = set()
    if mp.exists():
        try:
            data = _json.loads(mp.read_text())
            for entry in data.get("entries", []):
                for p in entry.get("programs", []):
                    names.add(p.lower())
        except Exception:
            pass
    _GERMAN_PROGRAM_NAMES = names
    return _GERMAN_PROGRAM_NAMES


_TRANSLATION_GLOSSARY = {
    "eligibility": "Eignung",
    "eligibility assessment": "Eignungsverfahren",
    "eligibility statute": "Eignungssatzung",
    "admission requirements": "Zulassungsvoraussetzungen",
    "admission regulations": "Zulassungsordnung",
    "examination regulations": "Prüfungsordnung",
    "study regulations": "Studienordnung",
    "examination and study regulations": "Prüfungs- und Studienordnung",
    "amendment": "Änderungssatzung",
    "amendment statute": "Änderungssatzung",
    "master thesis": "Masterarbeit",
    "bachelor thesis": "Bachelorarbeit",
    "standard period of study": "Regelstudienzeit",
    "compulsory module": "Pflichtmodul",
    "elective module": "Wahlpflichtmodul",
    "examination board": "Prüfungsausschuss",
    "credit points": "ECTS-Punkte",
    "credits": "ECTS-Punkte",
    "repeat examination": "Wiederholungsprüfung",
    "recognition of credits": "Anrechnung von Leistungen",
    "attendance requirement": "Anwesenheitspflicht",
    "grading": "Notenberechnung",
    "thesis extension": "Fristverlängerung",
    "enrollment": "Immatrikulation",
}
_SELECT_FIELDS = [
    "id", "content", "doc_name", "doc_filename", "source_url",
    "section_id", "section_title", "absatz", "page_number",
    "part", "sub_part", "doc_type", "program_name", "chunk_index",
    "amendment_context",
]


@lru_cache(maxsize=1)
def _get_openai_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


_search_client: SearchClient | None = None
_search_client_created: float = 0
_SEARCH_CLIENT_MAX_AGE = 3600  # recreate after 1 hour


def _get_search_client() -> SearchClient:
    global _search_client, _search_client_created
    now = time.monotonic()
    if _search_client is None or (now - _search_client_created > _SEARCH_CLIENT_MAX_AGE):
        if _search_client is not None:
            # Don't await close here since we're in sync context
            _search_client = None
        _search_client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index_name,
            credential=AzureKeyCredential(settings.azure_search_key),
        )
        _search_client_created = now
    return _search_client


async def close_search_client() -> None:
    global _search_client, _search_client_created, _web_search_client, _web_search_client_created
    if _search_client is not None:
        await _search_client.close()
        _search_client = None
        _search_client_created = 0
    if _web_search_client is not None:
        await _web_search_client.close()
        _web_search_client = None
        _web_search_client_created = 0


_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((TimeoutError, ConnectionError)),
    reraise=True,
)


@_RETRY
async def _embed_query(query: str) -> list[float]:
    cached = embedding_cache.get(query)
    if cached is not None:
        return cached
    client = _get_openai_client()
    response = await client.embeddings.create(
        model=settings.azure_openai_embedding_deployment,
        input=query,
    )
    vector = response.data[0].embedding
    embedding_cache.set(query, vector)
    return vector


def _is_german(text: str) -> bool:
    """Robust German detection: umlauts, program names, indicator words."""
    # Fast path: umlauts are unambiguously German
    if _GERMAN_UMLAUT_PATTERN.search(text):
        return True

    text_lower = text.lower()

    # Check if the query contains a known program name from manifest
    for name in _load_german_program_names():
        if name in text_lower:
            return True

    # Check German articles
    if _GERMAN_ARTICLES.search(text):
        return True

    # Check for German indicator words — even a single one is strong evidence
    words = re.findall(r"[a-zäöüß]+", text_lower)
    if words:
        if any(w in _GERMAN_INDICATOR_WORDS for w in words):
            return True

    return False


@_RETRY
async def _translate_to_german(query: str) -> str:
    client = _get_openai_client()
    query_lower = query.lower()
    glossary_matches = {
        k: v for k, v in _TRANSLATION_GLOSSARY.items() if k in query_lower
    }
    system_prompt = "Translate the user's question to German. Only output the translation, nothing else."
    if glossary_matches:
        terms = ", ".join(f'"{k}" → "{v}"' for k, v in glossary_matches.items())
        system_prompt += f" Use these domain-specific translations: {terms}"
    response = await client.chat.completions.create(
        model=settings.azure_openai_mini_deployment,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
        temperature=0,
        max_completion_tokens=200,
    )
    translated = response.choices[0].message.content.strip()
    logger.info("Translated query: '%s' → '%s'", query[:60], translated[:60])
    return translated


async def _generate_hyde(query: str) -> str:
    """Generate a hypothetical PSTO paragraph that would answer the query (HyDE)."""
    cached = hyde_cache.get(query)
    if cached is not None:
        return cached
    client = _get_openai_client()
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_mini_deployment,
            messages=[
                {"role": "system", "content": (
                    "Du bist ein Experte für deutsche Hochschulrechtsdokumente. "
                    "Schreibe einen kurzen, fiktiven Paragraphen einer Prüfungs- und Studienordnung (PSTO), "
                    "der die folgende Frage beantworten würde. Schreibe im Stil eines echten PSTO-Dokuments "
                    "mit §-Nummern, Absätzen und juristischer Fachsprache. Nur den Paragraphen ausgeben, nichts sonst. "
                    "WICHTIG: Erfinde KEINE konkreten Zahlen (z.B. Anzahl der Prüfungsversuche, ECTS-Punkte, Semesterzahl), "
                    "wenn du sie nicht sicher kennst — beschreibe stattdessen die Art der Regelung und die "
                    "einschlägige Fachterminologie (z.B. 'Wiederholung', 'Bestehen', 'beliebig oft', 'Regelstudienzeit')."
                )},
                {"role": "user", "content": query},
            ],
            temperature=0.3,
            max_completion_tokens=300,
        )
    except Exception as e:
        logger.warning("HyDE generation failed (%s), falling back to original query", e)
        hyde_cache.set(query, query)
        return query
    hyde_text = response.choices[0].message.content.strip()
    if len(hyde_text.split()) < 10:
        logger.info("HyDE too short, falling back to original query")
        hyde_cache.set(query, query)
        return query
    logger.info("HyDE generated: '%s...'", hyde_text[:80])
    hyde_cache.set(query, hyde_text)
    return hyde_text


async def _generate_expansions(query: str) -> list[str]:
    """Generate 2 alternative phrasings of the query to improve recall."""
    cache_key = f"exp:{query}"
    cached = hyde_cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]
    client = _get_openai_client()
    try:
        response = await client.chat.completions.create(
            model=settings.azure_openai_mini_deployment,
            messages=[
                {"role": "system", "content": (
                    "Schreibe genau 2 alternative Umformulierungen der folgenden Suchanfrage. "
                    "Die Anfrage bezieht sich auf deutsche Hochschulrechtsdokumente (Prüfungsordnungen, Eignungssatzungen). "
                    "Variiere Synonyme und Satzstruktur, behalte aber die ursprüngliche Bedeutung. "
                    "Gib nur die zwei Umformulierungen aus, eine pro Zeile, ohne Nummerierung."
                )},
                {"role": "user", "content": query},
            ],
            temperature=0.3,
            max_completion_tokens=150,
        )
    except Exception as e:
        logger.warning("Query expansion failed (%s), skipping", e)
        hyde_cache.set(cache_key, [])
        return []
    lines = [ln.strip() for ln in response.choices[0].message.content.strip().splitlines() if ln.strip()]
    seen: set[str] = set()
    expansions: list[str] = []
    for ln in lines:
        if ln not in seen:
            seen.add(ln)
            expansions.append(ln)
        if len(expansions) >= 2:
            break
    hyde_cache.set(cache_key, expansions)
    logger.debug("Query expansions: %s", expansions)
    return expansions


def _build_filter(doc_type: "str | tuple | list | None", program_name: str | None) -> str | None:
    parts = []
    if doc_type:
        if isinstance(doc_type, (list, tuple, set)):
            vals = ",".join(str(d).replace("'", "''") for d in doc_type)
            parts.append(f"search.in(doc_type, '{vals}', ',')")
        else:
            escaped = doc_type.replace("'", "''")
            parts.append(f"doc_type eq '{escaped}'")
    if program_name:
        escaped = program_name.replace("'", "''")
        parts.append(f"program_name eq '{escaped}'")
    return " and ".join(parts) if parts else None


def _filter_superseded(citations: list[Citation]) -> list[Citation]:
    """Remove citations from superseded document versions using the version registry."""
    from app.search.version_registry import get_registry
    registry = get_registry()
    filtered = [c for c in citations if registry.is_allowed(c.doc_filename)]
    removed = len(citations) - len(filtered)
    if removed:
        logger.info("Version filter: removed %d superseded citations (%d → %d)", removed, len(citations), len(filtered))
    return filtered


def _prefer_amendment_sections(citations: list[Citation]) -> list[Citation]:
    """When both a base doc (PSTO/Eignung/Zulassung) and Änderung exist for the same program+section, prefer the Änderung.

    Only removes base-doc chunks where the Änderung covers the same section AND absatz.
    Base-doc chunks with absätze not covered by the amendment are kept.
    """
    from collections import defaultdict
    amendment_keys: set[tuple[str, str, str | None]] = set()
    for c in citations:
        if c.doc_type == "aenderung" and c.section_id:
            amendment_keys.add((c.program_name, c.section_id, c.absatz))

    if not amendment_keys:
        return citations

    _BASE_DOC_TYPES = {"psto", "eignung", "zulassung"}
    to_remove: set[int] = set()
    for c in citations:
        if c.doc_type not in _BASE_DOC_TYPES or not c.section_id:
            continue
        key_exact = (c.program_name, c.section_id, c.absatz)
        key_section = (c.program_name, c.section_id, None)
        if key_exact in amendment_keys or (c.absatz is not None and key_section in amendment_keys):
            to_remove.add(id(c))

    if to_remove:
        result = [c for c in citations if id(c) not in to_remove]
        logger.info("Amendment preference: %d base-doc chunks superseded by amendments", len(to_remove))
        return result
    return citations


def _deduplicate_cross_program(citations: list[Citation]) -> list[Citation]:
    """Deduplicate identical sections across different programs.

    Groups by (section_id, absatz). Within each group, if all citations share the
    same doc_type, keep only the one with the highest reranker_score. If a group
    has mixed doc_types (e.g. psto + aenderung), keep the best per doc_type.
    """
    from collections import defaultdict
    groups: dict[tuple[str, str | None], list[Citation]] = defaultdict(list)
    ungrouped: list[Citation] = []
    for c in citations:
        if c.section_id:
            groups[(c.section_id, c.absatz)].append(c)
        else:
            ungrouped.append(c)

    result: list[Citation] = list(ungrouped)
    for key, group in groups.items():
        if len(group) <= 1:
            result.extend(group)
            continue
        # Check if there are multiple doc_types
        doc_types = {c.doc_type for c in group}
        if len(doc_types) <= 1:
            # Same doc_type across programs — keep only highest scored
            best = max(group, key=lambda c: c.reranker_score)
            result.append(best)
        else:
            # Mixed doc_types — keep the best per doc_type
            by_type: dict[str, Citation] = {}
            for c in group:
                if c.doc_type not in by_type or c.reranker_score > by_type[c.doc_type].reranker_score:
                    by_type[c.doc_type] = c
            result.extend(by_type.values())

    removed = len(citations) - len(result)
    if removed:
        logger.info("Cross-program dedup: removed %d duplicate sections (%d → %d)", removed, len(citations), len(result))
    # Preserve original score ordering
    result.sort(key=lambda c: c.reranker_score, reverse=True)
    return result


def _enforce_diversity(citations: list[Citation]) -> list[Citation]:
    """Limit to MAX_CHUNKS_PER_DOC chunks per document, keeping highest-scored."""
    doc_counts: dict[str, int] = {}
    diverse: list[Citation] = []
    sorted_citations = sorted(citations, key=lambda c: c.reranker_score, reverse=True)
    for c in sorted_citations:
        key = c.doc_filename
        count = doc_counts.get(key, 0)
        if count < MAX_CHUNKS_PER_DOC:
            diverse.append(c)
            doc_counts[key] = count + 1
    if len(diverse) < len(citations):
        logger.info("Diversity filter: %d → %d citations", len(citations), len(diverse))
    return diverse


# Student-vocabulary → PSTO-legal-vocabulary bridge.
# Keys are student/everyday terms (DE + EN); values are the German legal terms
# used in the actual regulation documents. Used to:
#   1. Augment the BM25 query string so first-stage retrieval surfaces the right §
#   2. Add a concept vector path (embedded German terms, language-neutral)
#   3. Extend title-match boosting even when query uses different vocabulary
_DOMAIN_EXPANSIONS: dict[str, list[str]] = {
    # Prüfungsversuche / exam attempts
    "prüfungsversuch":      ["Wiederholung der Modulprüfung", "beliebig oft", "nicht bestanden"],
    "prüfungsversuche":     ["Wiederholung der Modulprüfung", "beliebig oft", "nicht bestanden"],
    "klausurversuch":       ["Wiederholung der Modulprüfung", "beliebig oft"],
    "klausurversuche":      ["Wiederholung der Modulprüfung", "beliebig oft"],
    "durchgefallen":        ["nicht bestanden", "Wiederholung der Modulprüfung"],
    "exam attempt":         ["Wiederholung der Modulprüfung", "beliebig oft", "nicht bestanden"],
    "exam attempts":        ["Wiederholung der Modulprüfung", "beliebig oft", "nicht bestanden"],
    "retake":               ["Wiederholung", "nicht bestanden", "Wiederholungsprüfung"],
    "failed exam":          ["nicht bestanden", "Wiederholung der Modulprüfung"],
    "how many times":       ["Wiederholung", "beliebig oft"],
    # Note appeal / Widerspruch
    "note anfechten":       ["Widerspruch", "Prüfungsergebnis", "Einsicht", "Prüfungsamt"],
    "grade appeal":         ["Widerspruch", "Prüfungsergebnis", "Einsicht"],
    "appeal grade":         ["Widerspruch", "Prüfungsergebnis", "Einsicht"],
    # Thesis consequences
    "masterarbeit abgabe":  ["nicht bestanden", "Nichtbestehen", "Wiederholung der Masterarbeit"],
    "thesis deadline":      ["nicht bestanden", "Nichtbestehen", "Wiederholung der Masterarbeit"],
    "late submission":      ["nicht bestanden", "Nichtbestehen", "Fristversäumnis"],
}


def _domain_expand(query: str) -> list[str]:
    """Return PSTO legal terms that bridge vocabulary gaps in the query."""
    ql = query.lower()
    terms: list[str] = []
    for surface, legal in _DOMAIN_EXPANSIONS.items():
        if surface in ql:
            terms.extend(legal)
    seen: set[str] = set()
    out: list[str] = []
    for t in terms:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


_TITLE_SYNONYMS: dict[str, list[str]] = {
    "prüfungsformen": ["prüfung", "prüfungen", "art der prüfung"],
    "prüfungsform": ["prüfung", "prüfungen", "art der prüfung"],
    "klausur": ["prüfung", "schriftlich"],
    "mündlich": ["prüfung", "mündliche"],
    "masterarbeit": ["masterarbeit", "abschlussarbeit", "thesis"],
    "bachelorarbeit": ["bachelorarbeit", "abschlussarbeit"],
    "wiederholung": ["wiederholung", "wiederholen", "nicht bestanden"],
    "regelstudienzeit": ["regelstudienzeit", "studienzeit", "studiendauer"],
    "pflichtmodule": ["pflicht", "modul", "pflichtbereich"],
    "wahlpflicht": ["wahlpflicht", "wahlbereich", "wahl"],
    "anrechnung": ["anrechnung", "anerkennung"],
    "zulassung": ["zulassung", "zugang", "eignung"],
    "note": ["note", "noten", "berechnung", "bewertung"],
    "ects": ["ects", "leistungspunkt", "kreditpunkt"],
}


def _boost_title_matches(query: str, scored: list[tuple[float, dict]]) -> list[tuple[float, float, dict]]:
    """Boost ORDERING for title matches without corrupting the score the gate reads.

    Returns (rank_score, raw_score, doc): rank_score drives ordering/selection (the
    +0.3 title boost lives here), raw_score is the untouched reranker score (0..4)
    that the answerability gate must use — otherwise a keyword title match would fake
    high confidence and suppress abstention.
    """
    keywords = {w.lower() for w in query.split() if len(w) >= 4}
    expanded_keywords = set(keywords)
    for kw in keywords:
        for syn_key, syn_values in _TITLE_SYNONYMS.items():
            if kw.startswith(syn_key) or syn_key.startswith(kw):
                expanded_keywords.update(syn_values)
    # Also fold domain expansion terms so queries using student vocabulary
    # (e.g. "Prüfungsversuche") boost §-titles using legal vocabulary ("Wiederholung")
    for term in _domain_expand(query):
        expanded_keywords.update(w.lower() for w in term.split() if len(w) >= 4)

    boosted: list[tuple[float, float, dict]] = []
    for raw, doc in scored:
        title = (doc.get("section_title") or "").lower()
        matched = bool(title) and bool(expanded_keywords) and any(
            kw in title or title in kw for kw in expanded_keywords
        )
        rank = raw + 0.3 if matched else raw
        boosted.append((rank, raw, doc))
    boosted.sort(key=lambda x: x[0], reverse=True)
    return boosted


def _apply_answerability_gate(
    ranked: list[tuple[float, float, dict]],
) -> tuple[list[tuple[float, dict]], str, float]:
    """Three-band gate on the RAW reranker score (Azure semantic reranker: 0..4 scale).

    Returns (chosen, confidence, top_score) where chosen is [(raw_score, doc), ...]
    in rank order and confidence is 'solid' | 'uncertain' | 'abstain'.
      raw_top >= solid_score      -> answer confidently
      uncertain_score <= raw_top  -> answer with explicit uncertainty + escalation
      raw_top <  uncertain_score  -> abstain (empty -> hard hand-off upstream)
    """
    if not ranked:
        return [], "abstain", 0.0
    top_score = max(raw for _rank, raw, _doc in ranked)
    chosen_all = [(raw, doc) for _rank, raw, doc in ranked]

    if not settings.enable_answerability_gate:
        # Escape hatch: never abstain on score, behave like the old permissive path.
        return chosen_all, "solid", top_score

    solid = [(raw, doc) for raw, doc in chosen_all if raw >= settings.reranker_solid_score]
    if solid:
        return solid, "solid", top_score
    uncertain = [(raw, doc) for raw, doc in chosen_all if raw >= settings.reranker_uncertain_score]
    if uncertain:
        return uncertain[:FALLBACK_TOP_K], "uncertain", top_score
    return [], "abstain", top_score


def _reciprocal_rank_fusion(result_lists: list[list[tuple[float, dict]]]) -> list[tuple[float, dict]]:
    """Merge multiple ranked result lists using Reciprocal Rank Fusion."""
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    for results in result_lists:
        for rank, (reranker_score, doc) in enumerate(results):
            doc_id = doc.get("id", "")
            scores[doc_id] = scores.get(doc_id, 0) + 1.0 / (RRF_K + rank + 1)
            if doc_id not in docs or reranker_score > (docs[doc_id].get("_reranker_score") or 0):
                docs[doc_id] = dict(doc)  # copy to avoid mutating original
                docs[doc_id]["_reranker_score"] = reranker_score
    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(docs[doc_id].pop("_reranker_score", 0), docs[doc_id]) for doc_id, _ in merged if doc_id in docs]


async def _search_with_vector(
    search_query: str,
    query_vector: list[float],
    filter_expr: str | None,
    top_k: int,
) -> list[tuple[float, dict]]:
    """Run hybrid search with vector query + semantic reranker (falls back to plain hybrid if reranker unavailable)."""
    client = _get_search_client()
    try:
        results = await client.search(
            search_text=search_query,
            vector_queries=[
                VectorizedQuery(vector=query_vector, k_nearest_neighbors=top_k, fields="content_vector"),
            ],
            filter=filter_expr,
            query_type="semantic",
            semantic_configuration_name="default",
            top=top_k,
            select=_SELECT_FIELDS,
        )
        scored: list[tuple[float, dict]] = []
        async for result in results:
            score = result.get("@search.reranker_score") or 0.0
            scored.append((score, dict(result)))
        return scored
    except Exception as e:
        if "402" in str(e) or "semantic" in str(e).lower():
            logger.warning("Semantic reranker unavailable, falling back to plain hybrid search")
            return await _search_with_vector_no_reranker(search_query, query_vector, filter_expr, top_k)
        raise


async def _search_with_vector_no_reranker(
    search_query: str,
    query_vector: list[float],
    filter_expr: str | None,
    top_k: int,
) -> list[tuple[float, dict]]:
    """Hybrid search without semantic reranker — uses search score as fallback."""
    client = _get_search_client()
    results = await client.search(
        search_text=search_query,
        vector_queries=[
            VectorizedQuery(vector=query_vector, k_nearest_neighbors=top_k, fields="content_vector"),
        ],
        filter=filter_expr,
        top=top_k,
        select=_SELECT_FIELDS,
    )
    scored: list[tuple[float, dict]] = []
    async for result in results:
        score = result.get("@search.score") or 0.0
        scored.append((score, dict(result)))
    return scored


async def _search_bm25_only(
    search_query: str,
    filter_expr: str | None,
    top_k: int,
) -> list[tuple[float, dict]]:
    """Run BM25-only search with semantic reranker (falls back to plain BM25 if reranker unavailable)."""
    client = _get_search_client()
    try:
        results = await client.search(
            search_text=search_query,
            filter=filter_expr,
            query_type="semantic",
            semantic_configuration_name="default",
            top=top_k,
            select=_SELECT_FIELDS,
        )
        scored: list[tuple[float, dict]] = []
        async for result in results:
            score = result.get("@search.reranker_score") or 0.0
            scored.append((score, dict(result)))
        return scored
    except Exception as e:
        if "402" in str(e) or "semantic" in str(e).lower():
            logger.warning("Semantic reranker unavailable for BM25, falling back to plain BM25")
            results = await client.search(
                search_text=search_query,
                filter=filter_expr,
                top=top_k,
                select=_SELECT_FIELDS,
            )
            scored = []
            async for result in results:
                score = result.get("@search.score") or 0.0
                scored.append((score, dict(result)))
            return scored
        raise


async def _fetch_neighbor_chunks(citations: list[Citation]) -> list[Citation]:
    """Expand top citations with neighboring chunks from the same document.

    Uses a single batch query with an OR filter instead of one query per document.
    """
    if not citations:
        return citations

    targets: list[tuple[Citation, int]] = []
    for c in citations[:3]:
        chunk_idx = c.chunk_index
        if chunk_idx is None:
            continue
        targets.append((c, chunk_idx))

    if not targets:
        return citations

    needed: set[tuple[str, int]] = set()
    for c, idx in targets:
        needed.add((c.doc_filename, idx - 1))
        needed.add((c.doc_filename, idx + 1))

    neighbor_content: dict[tuple[str, int], str] = {}

    try:
        # Build a precise filter for exactly the chunks we need (at most 6)
        needed_filters = [
            f"(doc_filename eq '{fn.replace(chr(39), chr(39)*2)}' and chunk_index eq {idx})"
            for fn, idx in needed
        ]
        client = _get_search_client()
        results = await client.search(
            search_text="*",
            filter=" or ".join(needed_filters),
            top=len(needed),
            select=["doc_filename", "chunk_index", "content"],
        )
        async for r in results:
            key = (r["doc_filename"], r["chunk_index"])
            neighbor_content[key] = r["content"]
    except Exception:
        logger.warning("Neighbor chunk fetch failed, continuing without expansion", exc_info=True)
        return citations

    enc = _tiktoken.get_encoding("o200k_base")

    for c, chunk_idx in targets:
        expanded_parts = []
        prev = neighbor_content.get((c.doc_filename, chunk_idx - 1))
        if prev:
            expanded_parts.append(f"[...] {prev}")
        expanded_parts.append(c.content)
        nxt = neighbor_content.get((c.doc_filename, chunk_idx + 1))
        if nxt:
            expanded_parts.append(f"{nxt} [...]")
        expanded = "\n\n".join(expanded_parts)
        if len(enc.encode(expanded)) <= NEIGHBOR_MAX_TOKENS:
            c.content = expanded

    return citations


class RetrievalResult:
    __slots__ = ("citations", "low_confidence", "confidence", "top_score", "timing")

    def __init__(
        self,
        citations: list[Citation],
        low_confidence: bool = False,
        confidence: str = "solid",
        top_score: float = 0.0,
        timing: dict | None = None,
    ):
        self.citations = citations
        self.low_confidence = low_confidence
        self.confidence = confidence  # 'solid' | 'uncertain' | 'abstain'
        self.top_score = top_score
        self.timing = timing or {}


async def retrieve(
    query: str,
    top_k: int = 15,
    doc_type: str | None = None,
    program_name: str | None = None,
    query_type: str | None = None,
) -> RetrievalResult:
    """Perform multi-path hybrid search with RRF fusion.

    For factual queries, only 2 search paths (vector + BM25) are used to
    improve precision and latency.  All other types use the full 5-path
    pipeline (HyDE + original + BM25 + 2 expansions).
    """
    timing: dict[str, float] = {}
    t0 = time.perf_counter()

    # 1. Translate if not German
    search_query = query
    if not _is_german(query):
        search_query = await _translate_to_german(query)

    # 2. Generate embeddings (and optionally HyDE + expansions)
    t1 = time.perf_counter()

    if query_type in ("factual",):
        # Precision mode: skip HyDE and generative expansions to avoid noise.
        # Domain expansions (static vocabulary bridge) are still applied:
        # they close lexical gaps without the hallucination risk of LLM-generated content.
        domain_terms = _domain_expand(search_query)
        coros: list = [_embed_query(search_query)]
        if domain_terms:
            coros.append(_embed_query(" ".join(domain_terms)))
        embed_results_factual = await asyncio.gather(*coros)
        orig_vector = embed_results_factual[0]
        concept_vector: list[float] | None = embed_results_factual[1] if domain_terms else None
        expansion_vectors: list[list[float]] = []
        logger.info(
            "Factual query — precision mode (%d search paths, domain_terms=%d)",
            3 if concept_vector else 2, len(domain_terms),
        )
    else:
        # Full mode: all 5 paths for complex queries
        hyde_text, orig_vector, expansions = await asyncio.gather(
            _generate_hyde(search_query),
            _embed_query(search_query),
            _generate_expansions(search_query),
        )
        # Embed HyDE text and all expansion phrasings in parallel
        embed_results = await asyncio.gather(
            _embed_query(hyde_text),
            *[_embed_query(exp) for exp in expansions],
        )
        expansion_vectors = list(embed_results[1:])

    timing["hyde_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    filter_expr = _build_filter(doc_type, program_name)

    # 3. Multi-path search
    t2 = time.perf_counter()

    if query_type in ("factual",):
        # Precision mode: original vector + BM25 (augmented with domain terms) + optional concept vector
        bm25_query = (search_query + " " + " ".join(domain_terms)).strip() if domain_terms else search_query
        search_tasks = [
            _search_with_vector(search_query, orig_vector, filter_expr, top_k),
            _search_bm25_only(bm25_query, filter_expr, top_k),
        ]
        if concept_vector is not None:
            search_tasks.append(_search_with_vector(search_query, concept_vector, filter_expr, top_k))
    else:
        # Full mode: HyDE vector + original vector + BM25 + expansion vectors
        hyde_vector = embed_results[0]
        search_tasks = [
            _search_with_vector(search_query, hyde_vector, filter_expr, top_k),
            _search_with_vector(search_query, orig_vector, filter_expr, top_k),
            _search_bm25_only(search_query, filter_expr, top_k),
            *[_search_with_vector(search_query, vec, filter_expr, top_k) for vec in expansion_vectors],
        ]

    all_results = await asyncio.gather(*search_tasks)
    timing["search_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    # 4. Reciprocal Rank Fusion across all paths
    all_scored = _reciprocal_rank_fusion(list(all_results))

    # 4b. Title-match boost affects ORDERING only — keeps the raw score for the gate
    ranked = _boost_title_matches(search_query, all_scored)

    # 5. Three-band answerability gate on the raw reranker score (0..4 scale)
    chosen, confidence, top_score = _apply_answerability_gate(ranked)
    low_confidence = confidence != "solid"
    if confidence != "solid":
        logger.info("Answerability gate: confidence=%s top_score=%.2f chosen=%d", confidence, top_score, len(chosen))

    # 6. Build citations
    raw_citations: list[Citation] = []
    for i, (_score, result) in enumerate(chosen, start=1):
        c = Citation(
            index=i,
            section_id=result.get("section_id", ""),
            section_title=result.get("section_title", ""),
            absatz=result.get("absatz") or None,
            page_number=result.get("page_number", 0),
            doc_name=result.get("doc_name", ""),
            doc_filename=result.get("doc_filename", ""),
            program_name=result.get("program_name", ""),
            source_url=result.get("source_url", ""),
            content=result.get("content", ""),
            doc_type=result.get("doc_type", ""),
            reranker_score=_score,
            amendment_context=result.get("amendment_context") or "",
        )
        c.chunk_index = result.get("chunk_index")
        raw_citations.append(c)

    # 7. Version filtering + Cross-program dedup + Diversity + Global cap
    citations = _filter_superseded(raw_citations)
    citations = _prefer_amendment_sections(citations)
    citations = _deduplicate_cross_program(citations)
    citations = _enforce_diversity(citations)
    citations = citations[:10]

    # 8. Neighbor chunk expansion
    t3 = time.perf_counter()
    citations = await _fetch_neighbor_chunks(citations)
    timing["neighbor_ms"] = round((time.perf_counter() - t3) * 1000, 1)

    for i, c in enumerate(citations, start=1):
        c.index = i

    timing["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    logger.info(
        "Retrieved %d citations (from %d raw, confidence=%s, top_score=%.2f, %d paths+rrf) for query: %s (filter: %s) [%s]",
        len(citations), len(raw_citations), confidence, top_score, len(search_tasks), query[:60],
        filter_expr or "none",
        ", ".join(f"{k}={v}" for k, v in timing.items()),
    )
    return RetrievalResult(
        citations=citations, low_confidence=low_confidence,
        confidence=confidence, top_score=top_score, timing=timing,
    )


# ---------------------------------------------------------------------------
# Web index retrieval (campuslmu-web-v1)
# ---------------------------------------------------------------------------

_web_search_client: SearchClient | None = None
_web_search_client_created: float = 0

_WEB_SELECT_FIELDS = [
    "id", "content", "doc_name", "doc_filename", "source_url",
    "section_title", "chunk_index", "doc_type", "topic_slug",
]


def _get_web_search_client() -> SearchClient:
    global _web_search_client, _web_search_client_created
    now = time.monotonic()
    if _web_search_client is None or (now - _web_search_client_created > _SEARCH_CLIENT_MAX_AGE):
        _web_search_client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_web_index_name,
            credential=AzureKeyCredential(settings.azure_search_key),
        )
        _web_search_client_created = now
    return _web_search_client


async def _web_search_hybrid(
    search_query: str,
    query_vector: list[float],
    top_k: int,
) -> list[tuple[float, dict]]:
    client = _get_web_search_client()
    try:
        results = await client.search(
            search_text=search_query,
            vector_queries=[
                VectorizedQuery(vector=query_vector, k_nearest_neighbors=top_k, fields="content_vector"),
            ],
            query_type="semantic",
            semantic_configuration_name="default",
            top=top_k,
            select=_WEB_SELECT_FIELDS,
        )
        scored: list[tuple[float, dict]] = []
        async for result in results:
            score = result.get("@search.reranker_score") or 0.0
            scored.append((score, dict(result)))
        return scored
    except Exception as e:
        if "402" in str(e) or "semantic" in str(e).lower():
            logger.warning("Semantic reranker unavailable for web index, falling back")
            results = await client.search(
                search_text=search_query,
                vector_queries=[
                    VectorizedQuery(vector=query_vector, k_nearest_neighbors=top_k, fields="content_vector"),
                ],
                top=top_k,
                select=_WEB_SELECT_FIELDS,
            )
            scored = []
            async for result in results:
                scored.append((result.get("@search.score", 0.0), dict(result)))
            return scored
        raise


async def _web_search_keyword_reranked(search_query: str, top_k: int) -> list[tuple[float, dict]]:
    client = _get_web_search_client()
    try:
        results = await client.search(
            search_text=search_query,
            query_type="semantic",
            semantic_configuration_name="default",
            top=top_k,
            select=_WEB_SELECT_FIELDS,
        )
        scored: list[tuple[float, dict]] = []
        async for result in results:
            scored.append((result.get("@search.reranker_score", 0.0), dict(result)))
        return scored
    except Exception as e:
        if "402" in str(e) or "semantic" in str(e).lower():
            results = await client.search(
                search_text=search_query, top=top_k, select=_WEB_SELECT_FIELDS,
            )
            scored = []
            async for result in results:
                scored.append((result.get("@search.score", 0.0), dict(result)))
            return scored
        raise


def _web_doc_to_citation(score: float, doc: dict, index: int) -> Citation:
    return Citation(
        index=index,
        section_id="",
        section_title=doc.get("section_title", ""),
        absatz=None,
        page_number=0,
        doc_name=doc.get("doc_name", ""),
        doc_filename=doc.get("doc_filename", ""),
        program_name="",
        source_url=doc.get("source_url", ""),
        content=doc.get("content", ""),
        doc_type=doc.get("doc_type", "web_1x1"),
        reranker_score=score,
        chunk_index=doc.get("chunk_index"),
    )


async def retrieve_web(
    query: str,
    top_k: int = 10,
) -> RetrievalResult:
    """Retrieve from the web content index. 2-path: vector + BM25, no HyDE."""
    timing: dict[str, float] = {}
    t0 = time.perf_counter()

    search_query = query
    if not _is_german(query):
        search_query = await _translate_to_german(query)

    t1 = time.perf_counter()
    query_vector = await _embed_query(search_query)
    timing["embed_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    t2 = time.perf_counter()
    hybrid_results, bm25_results = await asyncio.gather(
        _web_search_hybrid(search_query, query_vector, top_k),
        _web_search_keyword_reranked(search_query, top_k),
    )
    timing["search_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    all_scored = _reciprocal_rank_fusion([hybrid_results, bm25_results])

    # Web index has no title boost — rank == raw reranker score
    ranked = [(s, s, doc) for s, doc in all_scored]
    chosen, confidence, top_score = _apply_answerability_gate(ranked)
    low_confidence = confidence != "solid"

    citations = [_web_doc_to_citation(s, r, i) for i, (s, r) in enumerate(chosen[:top_k], 1)]
    citations = _enforce_diversity(citations)
    citations = citations[:10]

    for i, c in enumerate(citations, 1):
        c.index = i

    timing["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)
    logger.info(
        "Web retrieval: %d citations (confidence=%s, top_score=%.2f) for: %s [%s]",
        len(citations), confidence, top_score, query[:60],
        ", ".join(f"{k}={v}" for k, v in timing.items()),
    )
    return RetrievalResult(
        citations=citations, low_confidence=low_confidence,
        confidence=confidence, top_score=top_score, timing=timing,
    )


async def retrieve_combined(
    query: str,
    top_k: int = 10,
    doc_type: str | None = None,
    program_name: str | None = None,
    query_type: str | None = None,
) -> RetrievalResult:
    """Retrieve from BOTH regulation and web indices, merge with RRF.

    Scores from different indices are not directly comparable, so we use
    rank-based RRF fusion instead of raw score sorting.
    """
    reg_result, web_result = await asyncio.gather(
        retrieve(query, top_k=top_k, doc_type=doc_type, program_name=program_name, query_type=query_type),
        retrieve_web(query, top_k=top_k),
    )

    # Build ranked lists keyed by source_url (unique across indices)
    reg_ranked = [(c.reranker_score, {"_citation": c}) for c in reg_result.citations]
    web_ranked = [(c.reranker_score, {"_citation": c}) for c in web_result.citations]

    scores: dict[int, float] = {}
    citation_by_id: dict[int, Citation] = {}
    for ranked_list in [reg_ranked, web_ranked]:
        for rank, (_, entry) in enumerate(ranked_list):
            c = entry["_citation"]
            cid = id(c)
            scores[cid] = scores.get(cid, 0) + 1.0 / (RRF_K + rank + 1)
            citation_by_id[cid] = c

    merged = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    all_citations = [citation_by_id[cid] for cid, _ in merged][:top_k]

    for i, c in enumerate(all_citations, 1):
        c.index = i

    timing = {
        "regulation_ms": reg_result.timing.get("total_ms", 0),
        "web_ms": web_result.timing.get("total_ms", 0),
    }
    # Inherit the strongest band from the two calibrated sub-retrievals. Cross-index
    # raw scores aren't directly comparable, so band-merge instead of re-thresholding.
    if reg_result.confidence == "solid" or web_result.confidence == "solid":
        confidence = "solid"
    elif reg_result.citations or web_result.citations:
        confidence = "uncertain"
    else:
        confidence = "abstain"
    low_confidence = confidence != "solid"
    top_score = max(reg_result.top_score, web_result.top_score)

    logger.info(
        "Combined retrieval: %d reg + %d web → %d total (confidence=%s)",
        len(reg_result.citations), len(web_result.citations), len(all_citations), confidence,
    )
    return RetrievalResult(
        citations=all_citations, low_confidence=low_confidence,
        confidence=confidence, top_score=top_score, timing=timing,
    )
