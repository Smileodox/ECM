import logging
import os
import time

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SemanticConfiguration,
    SemanticField,
    SemanticPrioritizedFields,
    SemanticSearch,
    SimpleField,
    VectorSearch,
    VectorSearchProfile,
)
from collections import defaultdict

from openai import APIConnectionError, APITimeoutError, AzureOpenAI, BadRequestError, RateLimitError

from app.config import settings
from app.ingestion.chunker import Chunk

logger = logging.getLogger(__name__)

EMBEDDING_BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "8"))


def _get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
    )


def _get_index_client() -> SearchIndexClient:
    return SearchIndexClient(
        endpoint=settings.azure_search_endpoint,
        credential=AzureKeyCredential(settings.azure_search_key),
    )


def _get_search_client(index_name: str | None = None) -> SearchClient:
    return SearchClient(
        endpoint=settings.azure_search_endpoint,
        index_name=index_name or settings.azure_search_index_name,
        credential=AzureKeyCredential(settings.azure_search_key),
    )


def create_or_update_index() -> None:
    """Create or update the Azure AI Search index with the required schema."""
    index = SearchIndex(
        name=settings.azure_search_index_name,
        fields=[
            SimpleField(
                name="id",
                type=SearchFieldDataType.String,
                key=True,
                filterable=True,
            ),
            SearchableField(
                name="content",
                type=SearchFieldDataType.String,
                analyzer_name="de.lucene",
            ),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=1536,
                vector_search_profile_name="default-vector-profile",
            ),
            SimpleField(
                name="doc_name",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SimpleField(
                name="doc_filename",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="source_url",
                type=SearchFieldDataType.String,
            ),
            SearchableField(
                name="section_id",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SearchableField(
                name="section_title",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="absatz",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="page_number",
                type=SearchFieldDataType.Int32,
                filterable=True,
                sortable=True,
            ),
            SimpleField(
                name="part",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SimpleField(
                name="sub_part",
                type=SearchFieldDataType.String,
                filterable=True,
            ),
            SimpleField(
                name="chunk_index",
                type=SearchFieldDataType.Int32,
                sortable=True,
                filterable=True,
            ),
            SimpleField(
                name="amendment_context",
                type=SearchFieldDataType.String,
            ),
            SimpleField(
                name="doc_type",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
            SearchableField(
                name="program_name",
                type=SearchFieldDataType.String,
                filterable=True,
                facetable=True,
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="default-hnsw",
                    parameters={
                        "m": 16,
                        "efConstruction": 400,
                        "efSearch": 500,
                        "metric": "cosine",
                    },
                ),
            ],
            profiles=[
                VectorSearchProfile(
                    name="default-vector-profile",
                    algorithm_configuration_name="default-hnsw",
                ),
            ],
        ),
        semantic_search=SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name="default",
                    prioritized_fields=SemanticPrioritizedFields(
                        content_fields=[SemanticField(field_name="content")],
                        title_field=SemanticField(field_name="section_title"),
                        keywords_fields=[SemanticField(field_name="section_id")],
                    ),
                ),
            ],
        ),
    )

    client = _get_index_client()
    client.create_or_update_index(index)
    logger.info("Index '%s' created/updated.", settings.azure_search_index_name)


def embed_chunks(chunks: list[Chunk]) -> list[list[float]]:
    """Generate embeddings for a list of chunks in batches."""
    client = _get_openai_client()
    all_embeddings: list[list[float]] = []

    for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
        batch = chunks[i : i + EMBEDDING_BATCH_SIZE]
        texts = [c.content for c in batch]

        for attempt in range(8):
            try:
                response = client.embeddings.create(
                    model=settings.azure_openai_embedding_deployment,
                    input=texts,
                )
                break
            except Exception as e:
                transient = (
                    isinstance(e, (RateLimitError, APIConnectionError, APITimeoutError))
                    or "429" in str(e)
                    or "rate" in str(e).lower()
                    or "connection" in str(e).lower()
                    or "disconnected" in str(e).lower()
                )
                if transient:
                    wait = min(10 * (2 ** attempt), 120)
                    logger.warning("Embedding transient error (%s) attempt %d, retrying in %ds...", type(e).__name__, attempt + 1, wait)
                    time.sleep(wait)
                else:
                    raise
        else:
            raise RuntimeError(f"Failed to embed batch after 8 attempts (chunks {i+1}-{i+len(batch)})")

        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)
        logger.info(
            "Embedded batch %d-%d of %d chunks.",
            i + 1,
            min(i + EMBEDDING_BATCH_SIZE, len(chunks)),
            len(chunks),
        )

        if i + EMBEDDING_BATCH_SIZE < len(chunks):
            time.sleep(2)

    return all_embeddings


def upload_chunks(chunks: list[Chunk], embeddings: list[list[float]]) -> int:
    """Upload chunks with embeddings to Azure AI Search. Returns count uploaded."""
    client = _get_search_client()

    documents = []
    for chunk, embedding in zip(chunks, embeddings):
        documents.append({
            "id": chunk.id,
            "content": chunk.content,
            "content_vector": embedding,
            "doc_name": chunk.doc_name,
            "doc_filename": chunk.doc_filename,
            "source_url": chunk.source_url,
            "section_id": chunk.section_id,
            "section_title": chunk.section_title,
            "absatz": chunk.absatz or "",
            "page_number": chunk.page_number,
            "part": chunk.part,
            "sub_part": chunk.sub_part,
            "chunk_index": chunk.chunk_index,
            "doc_type": chunk.doc_type,
            "program_name": chunk.program_name,
            "amendment_context": chunk.amendment_context,
        })

    # Upload in batches of 100 (Azure limit is 1000, but smaller is safer)
    uploaded = 0
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        result = client.upload_documents(documents=batch)
        succeeded = sum(1 for r in result if r.succeeded)
        uploaded += succeeded
        logger.info(
            "Uploaded batch %d-%d: %d/%d succeeded.",
            i + 1,
            min(i + batch_size, len(documents)),
            succeeded,
            len(batch),
        )

    return uploaded


def ingest_chunks(chunks: list[Chunk]) -> int:
    """Full pipeline: create index, embed, upload. Returns count indexed."""
    try:
        create_or_update_index()
    except Exception:
        logger.warning("Index schema update failed (may need full re-index for field changes)", exc_info=True)
    embeddings = embed_chunks(chunks)
    return upload_chunks(chunks, embeddings)


def delete_document_chunks(doc_filename: str) -> int:
    """Delete all chunks for a given document filename. Returns count deleted."""
    client = _get_search_client()
    results = client.search(
        search_text="*",
        filter=f"doc_filename eq '{doc_filename}'",
        select=["id"],
        top=1000,
    )
    ids = [{"id": r["id"]} for r in results]
    if not ids:
        return 0
    result = client.delete_documents(documents=ids)
    deleted = sum(1 for r in result if r.succeeded)
    logger.info("Deleted %d chunks for %s", deleted, doc_filename)
    return deleted


def get_indexed_documents() -> set[str]:
    """Return set of doc_filenames already present in the index."""
    client = _get_search_client()
    try:
        results = client.search(
            search_text="*",
            select=["doc_filename"],
            top=0,
            facets=["doc_filename,count:1000"],
        )
        # Force evaluation to populate facets
        list(results)
        facets = results.get_facets()
        if facets and "doc_filename" in facets:
            return {f["value"] for f in facets["doc_filename"]}
    except Exception as e:
        logger.warning("Could not query indexed documents: %s", e)
    return set()


# ---------------------------------------------------------------------------
# Web index (campuslmu-web-v1)
# ---------------------------------------------------------------------------


def create_or_update_web_index() -> None:
    """Create or update the web content search index."""
    index = SearchIndex(
        name=settings.azure_search_web_index_name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True, filterable=True),
            SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="de.lucene"),
            SearchField(
                name="content_vector",
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=1536,
                vector_search_profile_name="default-vector-profile",
            ),
            SimpleField(name="doc_name", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="doc_filename", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="source_url", type=SearchFieldDataType.String),
            SearchableField(name="section_title", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="chunk_index", type=SearchFieldDataType.Int32, sortable=True, filterable=True),
            SimpleField(name="doc_type", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SearchableField(name="topic_slug", type=SearchFieldDataType.String, filterable=True, facetable=True),
        ],
        vector_search=VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="default-hnsw",
                    parameters={"m": 16, "efConstruction": 400, "efSearch": 500, "metric": "cosine"},
                ),
            ],
            profiles=[
                VectorSearchProfile(name="default-vector-profile", algorithm_configuration_name="default-hnsw"),
            ],
        ),
        semantic_search=SemanticSearch(
            configurations=[
                SemanticConfiguration(
                    name="default",
                    prioritized_fields=SemanticPrioritizedFields(
                        content_fields=[SemanticField(field_name="content")],
                        title_field=SemanticField(field_name="section_title"),
                        keywords_fields=[SemanticField(field_name="topic_slug")],
                    ),
                ),
            ],
        ),
    )
    client = _get_index_client()
    client.create_or_update_index(index)
    logger.info("Web index '%s' created/updated.", settings.azure_search_web_index_name)


def upload_web_chunks(chunks: list[Chunk], embeddings: list[list[float]]) -> int:
    """Upload web content chunks to the web search index."""
    client = _get_search_client(settings.azure_search_web_index_name)

    documents = []
    for chunk, embedding in zip(chunks, embeddings):
        documents.append({
            "id": chunk.id,
            "content": chunk.content,
            "content_vector": embedding,
            "doc_name": chunk.doc_name,
            "doc_filename": chunk.doc_filename,
            "source_url": chunk.source_url,
            "section_title": chunk.section_title,
            "chunk_index": chunk.chunk_index,
            "doc_type": chunk.doc_type,
            "topic_slug": chunk.topic_slug,
        })

    uploaded = 0
    batch_size = 100
    for i in range(0, len(documents), batch_size):
        batch = documents[i : i + batch_size]
        result = client.upload_documents(documents=batch)
        succeeded = sum(1 for r in result if r.succeeded)
        uploaded += succeeded
        logger.info("Web index: uploaded %d-%d: %d/%d", i + 1, min(i + batch_size, len(documents)), succeeded, len(batch))
    return uploaded


def ingest_web_chunks(chunks: list[Chunk]) -> int:
    """Full pipeline for web chunks: create index, embed, upload."""
    create_or_update_web_index()
    embeddings = embed_chunks(chunks)
    return upload_web_chunks(chunks, embeddings)


MAX_EMBED_CHARS = 16000


def _embed_with_retry(client: AzureOpenAI, texts: list[str]) -> list[list[float]]:
    """Embed texts with retry for 429 and auto-split for token overflow."""
    texts = [t[:MAX_EMBED_CHARS] if len(t) > MAX_EMBED_CHARS else t for t in texts]
    if len(texts) > 1:
        try:
            return _embed_single_call(client, texts)
        except BadRequestError:
            mid = len(texts) // 2
            left = _embed_with_retry(client, texts[:mid])
            right = _embed_with_retry(client, texts[mid:])
            return left + right
    return _embed_single_call(client, texts)


def _embed_single_call(client: AzureOpenAI, texts: list[str]) -> list[list[float]]:
    for attempt in range(5):
        try:
            response = client.embeddings.create(
                model=settings.azure_openai_embedding_deployment,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except RateLimitError as e:
            retry_after = 60
            if hasattr(e, "response") and e.response is not None:
                retry_after = int(e.response.headers.get("retry-after", 60))
            logger.warning(
                "Rate limited (attempt %d/5), waiting %ds...",
                attempt + 1, retry_after,
            )
            time.sleep(retry_after)
    raise RuntimeError("Failed to embed after 5 attempts")


def embed_and_upload_incremental(
    chunks_by_doc: dict[str, list[Chunk]],
    already_indexed: set[str],
) -> int:
    """Embed and upload document by document. Resumable — skips already indexed docs."""
    oai_client = AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        max_retries=0,
    )
    search_client = _get_search_client()

    docs_to_process = {k: v for k, v in chunks_by_doc.items() if k not in already_indexed}
    total_docs = len(docs_to_process)
    total_indexed = 0

    if already_indexed:
        logger.info("Skipping %d already indexed documents.", len(already_indexed))
    logger.info("Processing %d documents...", total_docs)

    for doc_num, (doc_filename, chunks) in enumerate(docs_to_process.items(), 1):
        # Embed all chunks for this document
        all_embeddings: list[list[float]] = []
        for i in range(0, len(chunks), EMBEDDING_BATCH_SIZE):
            batch_texts = [c.content for c in chunks[i : i + EMBEDDING_BATCH_SIZE]]
            embeddings = _embed_with_retry(oai_client, batch_texts)
            all_embeddings.extend(embeddings)

        # Upload to search index
        documents = []
        for chunk, embedding in zip(chunks, all_embeddings):
            documents.append({
                "id": chunk.id,
                "content": chunk.content,
                "content_vector": embedding,
                "doc_name": chunk.doc_name,
                "doc_filename": chunk.doc_filename,
                "source_url": chunk.source_url,
                "section_id": chunk.section_id,
                "section_title": chunk.section_title,
                "absatz": chunk.absatz or "",
                "page_number": chunk.page_number,
                "part": chunk.part,
                "sub_part": chunk.sub_part,
                "chunk_index": chunk.chunk_index,
                "doc_type": chunk.doc_type,
                "program_name": chunk.program_name,
                "amendment_context": chunk.amendment_context,
            })

        result = search_client.upload_documents(documents=documents)
        succeeded = sum(1 for r in result if r.succeeded)
        total_indexed += succeeded

        logger.info(
            "[%d/%d] %s — %d chunks indexed",
            doc_num, total_docs, doc_filename, succeeded,
        )

        # Pace between documents to respect TPM
        if doc_num < total_docs:
            time.sleep(2)

    return total_indexed
