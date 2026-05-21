import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.ingestion.chunker import chunk_all_documents
from app.ingestion.indexer import ingest_chunks
from app.ingestion.parser import parse_all_pdfs
from app.models import IngestResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/ingest", response_model=IngestResponse)
async def ingest_documents():
    """Parse, chunk, and index all PDF documents."""
    docs_dir = Path(settings.documents_dir)
    if not docs_dir.exists():
        raise HTTPException(status_code=404, detail=f"Documents directory not found: {docs_dir}")

    pdf_files = list(docs_dir.glob("*.pdf"))
    if not pdf_files:
        raise HTTPException(status_code=404, detail="No PDF files found in documents directory")

    logger.info("Starting ingestion of %d PDF files...", len(pdf_files))

    # Parse
    parsed_docs = parse_all_pdfs(docs_dir)
    docs_count = len(parsed_docs)
    logger.info("Parsed %d documents.", docs_count)

    # Chunk
    url_map = {
        filename: f"{settings.lmu_cdn_base_url}/{filename}"
        for filename in parsed_docs
    }
    chunks = chunk_all_documents(parsed_docs, url_map=url_map)
    chunks_count = len(chunks)
    logger.info("Created %d chunks.", chunks_count)

    # Index
    indexed_count = ingest_chunks(chunks)
    logger.info("Indexed %d chunks.", indexed_count)

    return IngestResponse(
        documents_processed=docs_count,
        chunks_created=chunks_count,
        chunks_indexed=indexed_count,
    )
