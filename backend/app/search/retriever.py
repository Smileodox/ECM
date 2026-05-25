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

_GERMAN_PATTERN = re.compile(r"[äöüßÄÖÜ]|(?:der|die|das|und|für|ist|ein|des|den|dem)\b", re.IGNORECASE)
_SELECT_FIELDS = [
    "id", "content", "doc_name", "doc_filename", "source_url",
    "section_id", "section_title", "absatz", "page_number",
    "part", "sub_part", "doc_type", "program_name", "chunk_index",
]


@lru_cache(maxsize=1)
def _get_openai_client() -> AsyncAzureOpenAI:
    return AsyncAzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


_search_client: SearchClient | None = None


def _get_search_client() -> SearchClient:
    global _search_client
    if _search_client is None:
        _search_client = SearchClient(
            endpoint=settings.azure_search_endpoint,
            index_name=settings.azure_search_index_name,
            credential=AzureKeyCredential(settings.azure_search_key),
        )
    return _search_client


async def close_search_client() -> None:
    global _search_client
    if _search_client is not None:
        await _search_client.close()
        _search_client = None


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
    return bool(_GERMAN_PATTERN.search(text))


@_RETRY
async def _translate_to_german(query: str) -> str:
    client = _get_openai_client()
    response = await client.chat.completions.create(
        model=settings.azure_openai_deployment,
        messages=[
            {"role": "system", "content": "Translate the user's question to German. Only output the translation, nothing else."},
            {"role": "user", "content": query},
        ],
        temperature=0,
        max_tokens=200,
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
            model=settings.azure_openai_deployment,
            messages=[
                {"role": "system", "content": (
                    "Du bist ein Experte für deutsche Hochschulrechtsdokumente. "
                    "Schreibe einen kurzen, fiktiven Paragraphen einer Prüfungs- und Studienordnung (PSTO), "
                    "der die folgende Frage beantworten würde. Schreibe im Stil eines echten PSTO-Dokuments "
                    "mit §-Nummern, Absätzen und juristischer Fachsprache. Nur den Paragraphen ausgeben, nichts sonst."
                )},
                {"role": "user", "content": query},
            ],
            temperature=0.3,
            max_tokens=300,
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
            model=settings.azure_openai_deployment,
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
            max_tokens=150,
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


def _build_filter(doc_type: str | None, program_name: str | None) -> str | None:
    parts = []
    if doc_type:
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
    """When both PSTO §X Abs. Y and Änderung §X Abs. Y exist for the same program, prefer the Änderung.

    Only removes PSTO chunks where the Änderung covers the same section AND absatz.
    PSTO chunks with absätze not covered by the amendment are kept.
    """
    from collections import defaultdict
    amendment_keys: set[tuple[str, str, str | None]] = set()
    for c in citations:
        if c.doc_type == "aenderung" and c.section_id:
            amendment_keys.add((c.program_name, c.section_id, c.absatz))

    if not amendment_keys:
        return citations

    to_remove: set[int] = set()
    for c in citations:
        if c.doc_type != "psto" or not c.section_id:
            continue
        key_exact = (c.program_name, c.section_id, c.absatz)
        key_section = (c.program_name, c.section_id, None)
        if key_exact in amendment_keys or (c.absatz is not None and key_section in amendment_keys):
            to_remove.add(id(c))

    if to_remove:
        result = [c for c in citations if id(c) not in to_remove]
        logger.info("Amendment preference: %d PSTO chunks superseded by amendments", len(to_remove))
        return result
    return citations


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
    """Run hybrid search with vector query + semantic reranker."""
    client = _get_search_client()
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


async def _search_bm25_only(
    search_query: str,
    filter_expr: str | None,
    top_k: int,
) -> list[tuple[float, dict]]:
    """Run BM25-only search with semantic reranker (no vector)."""
    client = _get_search_client()
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

    enc = _tiktoken.encoding_for_model("gpt-4o")

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
    __slots__ = ("citations", "low_confidence", "timing")

    def __init__(self, citations: list[Citation], low_confidence: bool = False, timing: dict | None = None):
        self.citations = citations
        self.low_confidence = low_confidence
        self.timing = timing or {}


async def retrieve(
    query: str,
    top_k: int = 15,
    doc_type: str | None = None,
    program_name: str | None = None,
) -> RetrievalResult:
    """Perform multi-path hybrid search (HyDE + original + expansions + BM25) with RRF fusion."""
    timing: dict[str, float] = {}
    t0 = time.perf_counter()

    # 1. Translate if not German
    search_query = query
    if not _is_german(query):
        search_query = await _translate_to_german(query)

    # 2. Generate HyDE, embed original query, and generate expansions in parallel
    t1 = time.perf_counter()
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
    hyde_vector = embed_results[0]
    expansion_vectors = list(embed_results[1:])
    timing["hyde_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    filter_expr = _build_filter(doc_type, program_name)

    # 3. Multi-path search: HyDE vector + original vector + BM25 + expansion vectors
    t2 = time.perf_counter()
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

    # 5. Apply reranker thresholds
    primary = [(s, r) for s, r in all_scored if s >= settings.reranker_min_score]

    if not primary:
        fallback = [(s, r) for s, r in all_scored if s >= settings.reranker_fallback_score]
        fallback.sort(key=lambda x: x[0], reverse=True)
        chosen = fallback[:FALLBACK_TOP_K]
        low_confidence = bool(chosen)
        if low_confidence:
            logger.info("Reranker fallback: using %d results (scores %.2f–%.2f)", len(chosen), chosen[-1][0], chosen[0][0])
    else:
        chosen = primary
        low_confidence = False

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
        )
        c.chunk_index = result.get("chunk_index")
        raw_citations.append(c)

    # 7. Version filtering + Diversity + Global cap
    citations = _filter_superseded(raw_citations)
    citations = _prefer_amendment_sections(citations)
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
        "Retrieved %d citations (from %d raw, low_confidence=%s, %d paths+rrf) for query: %s (filter: %s) [%s]",
        len(citations), len(raw_citations), low_confidence, len(search_tasks), query[:60],
        filter_expr or "none",
        ", ".join(f"{k}={v}" for k, v in timing.items()),
    )
    return RetrievalResult(citations=citations, low_confidence=low_confidence, timing=timing)
