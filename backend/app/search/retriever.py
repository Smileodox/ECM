import logging

from azure.core.credentials import AzureKeyCredential
from azure.search.documents import SearchClient
from azure.search.documents.models import VectorizedQuery
from openai import AzureOpenAI

from app.config import settings
from app.models import Citation

logger = logging.getLogger(__name__)


def _get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
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


def _embed_query(query: str) -> list[float]:
    client = _get_openai_client()
    response = client.embeddings.create(
        model=settings.azure_openai_embedding_deployment,
        input=query,
    )
    return response.data[0].embedding


def retrieve(query: str, top_k: int = 5) -> list[Citation]:
    """Perform hybrid search (vector + BM25 + semantic reranker) and return citations."""
    query_vector = _embed_query(query)
    search_client = _get_search_client()

    results = search_client.search(
        search_text=query,
        vector_queries=[
            VectorizedQuery(
                vector=query_vector,
                k_nearest_neighbors=top_k,
                fields="content_vector",
            ),
        ],
        query_type="semantic",
        semantic_configuration_name="default",
        top=top_k,
        select=[
            "id",
            "content",
            "doc_name",
            "doc_filename",
            "source_url",
            "section_id",
            "section_title",
            "absatz",
            "page_number",
            "part",
            "sub_part",
        ],
    )

    citations: list[Citation] = []
    for i, result in enumerate(results, start=1):
        citations.append(Citation(
            index=i,
            section_id=result["section_id"],
            section_title=result["section_title"],
            absatz=result.get("absatz") or None,
            page_number=result["page_number"],
            doc_name=result["doc_name"],
            source_url=result.get("source_url", ""),
            content=result["content"],
        ))

    logger.info("Retrieved %d citations for query: %s", len(citations), query[:80])
    return citations
