import asyncio
import logging
import re
import time
from functools import lru_cache

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import AsyncAzureOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.config import settings
from app.models import Citation
from app.search.cache import embedding_cache, hyde_cache

logger = logging.getLogger(__name__)

MIN_RERANKER_SCORE = 0.8
FALLBACK_RERANKER_SCORE = 0.3
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


def _get_search_client() -> SearchClient:
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=settings.azure_search_index_name,
        credential=AzureKeyCredential(settings.azure_search_key),
    )


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
        model=settings.azure_openai_mini_deployment,
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
            model=settings.azure_openai_mini_deployment,
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
    """When both PSTO §X and current Änderung §X exist for the same program, prefer the Änderung."""
    from collections import defaultdict
    groups: dict[tuple[str, str], list[Citation]] = defaultdict(list)
    for c in citations:
        if c.doc_type in ("psto", "aenderung") and c.section_id:
            groups[(c.program_name, c.section_id)].append(c)

    to_remove: set[int] = set()
    for group in groups.values():
        has_aenderung = any(c.doc_type == "aenderung" for c in group)
        if not has_aenderung:
            continue
        for c in group:
            if c.doc_type == "psto":
                to_remove.add(id(c))

    if to_remove:
        result = [c for c in citations if id(c) not in to_remove]
        logger.info("Amendment preference: %d PSTO sections superseded by amendments", len(to_remove))
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
                docs[doc_id] = doc
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
    async with _get_search_client() as client:
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
    async with _get_search_client() as client:
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
    """Expand top citations with neighboring chunks from the same document."""
    if not citations:
        return citations

    targets: list[tuple[Citation, int]] = []
    doc_filenames: set[str] = set()
    for c in citations[:5]:
        chunk_idx = getattr(c, "_chunk_index", None)
        if chunk_idx is None:
            continue
        targets.append((c, chunk_idx))
        doc_filenames.add(c.doc_filename)

    if not targets:
        return citations

    needed: set[tuple[str, int]] = set()
    for c, idx in targets:
        needed.add((c.doc_filename, idx - 1))
        needed.add((c.doc_filename, idx + 1))

    neighbor_content: dict[tuple[str, int], str] = {}

    async def _fetch_doc_chunks(fname: str) -> list[tuple[tuple[str, int], str]]:
        escaped = fname.replace("'", "''")
        pairs: list[tuple[tuple[str, int], str]] = []
        async with _get_search_client() as client:
            results = await client.search(
                search_text="*",
                filter=f"doc_filename eq '{escaped}'",
                order_by=["chunk_index asc"],
                top=100,
                select=["doc_filename", "chunk_index", "content"],
            )
            async for r in results:
                key = (r["doc_filename"], r["chunk_index"])
                if key in needed:
                    pairs.append((key, r["content"]))
        return pairs

    try:
        results_lists = await asyncio.gather(
            *[_fetch_doc_chunks(fname) for fname in doc_filenames]
        )
        for pairs in results_lists:
            for key, content in pairs:
                neighbor_content[key] = content
    except Exception:
        logger.warning("Neighbor chunk fetch failed, continuing without expansion", exc_info=True)
        return citations

    import tiktoken
    enc = tiktoken.get_encoding("cl100k_base")

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
    """Perform dual-path hybrid search (HyDE vector + BM25) with RRF fusion."""
    timing: dict[str, float] = {}
    t0 = time.perf_counter()

    # 1. Translate if not German
    search_query = query
    if not _is_german(query):
        search_query = await _translate_to_german(query)

    # 2. Generate HyDE + embed in parallel
    t1 = time.perf_counter()
    hyde_text, _ = await asyncio.gather(
        _generate_hyde(search_query),
        asyncio.sleep(0),  # placeholder to keep gather pattern
    )
    hyde_vector = await _embed_query(hyde_text)
    timing["hyde_ms"] = round((time.perf_counter() - t1) * 1000, 1)

    filter_expr = _build_filter(doc_type, program_name)

    # 3. Dual-path search: HyDE vector search + BM25 search in parallel
    t2 = time.perf_counter()
    hyde_results, bm25_results = await asyncio.gather(
        _search_with_vector(search_query, hyde_vector, filter_expr, top_k),
        _search_bm25_only(search_query, filter_expr, top_k),
    )
    timing["search_ms"] = round((time.perf_counter() - t2) * 1000, 1)

    # 4. Reciprocal Rank Fusion
    all_scored = _reciprocal_rank_fusion([hyde_results, bm25_results])

    # 5. Apply reranker thresholds
    primary = [(s, r) for s, r in all_scored if s >= MIN_RERANKER_SCORE]

    if not primary:
        fallback = [(s, r) for s, r in all_scored if s >= FALLBACK_RERANKER_SCORE]
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
        c._chunk_index = result.get("chunk_index")
        raw_citations.append(c)

    # 7. Version filtering + Diversity
    citations = _filter_superseded(raw_citations)
    citations = _prefer_amendment_sections(citations)
    citations = _enforce_diversity(citations)

    # 8. Neighbor chunk expansion
    t3 = time.perf_counter()
    citations = await _fetch_neighbor_chunks(citations)
    timing["neighbor_ms"] = round((time.perf_counter() - t3) * 1000, 1)

    for i, c in enumerate(citations, start=1):
        c.index = i

    timing["total_ms"] = round((time.perf_counter() - t0) * 1000, 1)

    logger.info(
        "Retrieved %d citations (from %d raw, low_confidence=%s, hyde+rrf) for query: %s (filter: %s) [%s]",
        len(citations), len(raw_citations), low_confidence, query[:60],
        filter_expr or "none",
        ", ".join(f"{k}={v}" for k, v in timing.items()),
    )
    return RetrievalResult(citations=citations, low_confidence=low_confidence, timing=timing)
