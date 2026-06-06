import asyncio
import json
import logging
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from app.config import settings
from app.ingestion.chunker import chunk_all_documents
from app.ingestion.indexer import ingest_chunks
from app.ingestion.parser import parse_all_pdfs
from app.models import IngestResponse

_API_KEY_HEADER = APIKeyHeader(name="X-Ingest-Key", auto_error=False)
_INGEST_KEY = os.environ.get("INGEST_API_KEY", "")

logger = logging.getLogger(__name__)
router = APIRouter()


async def _verify_ingest_key(key: str | None = Security(_API_KEY_HEADER)):
    if not _INGEST_KEY:
        raise HTTPException(status_code=503, detail="Ingestion not configured (INGEST_API_KEY not set)")
    if key != _INGEST_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-Ingest-Key header")


def _run_ingest(docs_dir: Path) -> IngestResponse:
    """Blocking ingestion pipeline — runs in a thread pool to avoid blocking the event loop."""
    pdf_files = list(docs_dir.glob("*.pdf"))
    if not pdf_files:
        raise ValueError("No PDF files found in documents directory")

    from app.search.version_registry import get_registry, invalidate_registry
    invalidate_registry()
    registry = get_registry()
    blocked = registry.get_blocked_filenames()

    parsed_docs = parse_all_pdfs(docs_dir)
    if blocked:
        before = len(parsed_docs)
        parsed_docs = {fn: pages for fn, pages in parsed_docs.items() if fn not in blocked}
        logger.info("Version filter: %d → %d documents (skipped %d superseded)", before, len(parsed_docs), before - len(parsed_docs))
    docs_count = len(parsed_docs)
    logger.info("Parsed %d documents.", docs_count)

    manifest_path = docs_dir / "manifest.json"
    url_map: dict[str, str] = {}
    doc_type_map: dict[str, str] = {}
    program_map: dict[str, list[str]] = {}

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["entries"]:
            fn = entry["filename"]
            url_map[fn] = entry["source_url"]
            doc_type_map[fn] = entry.get("doc_type", "")
            program_map[fn] = entry.get("programs", [])
    else:
        url_map = {fn: f"{settings.lmu_cdn_base_url}/{fn}" for fn in parsed_docs}

    chunks = chunk_all_documents(
        parsed_docs,
        url_map=url_map,
        doc_type_map=doc_type_map,
        program_map=program_map,
        generate_summaries=True,
    )
    chunks_count = len(chunks)
    logger.info("Created %d chunks.", chunks_count)

    indexed_count = ingest_chunks(chunks)
    logger.info("Indexed %d chunks.", indexed_count)

    return IngestResponse(
        documents_processed=docs_count,
        chunks_created=chunks_count,
        chunks_indexed=indexed_count,
    )


@router.post("/ingest", response_model=IngestResponse, dependencies=[Depends(_verify_ingest_key)])
async def ingest_documents():
    """Parse, chunk, and index all PDF documents. Runs in a thread pool to avoid blocking."""
    docs_dir = Path(settings.documents_dir)
    if not docs_dir.exists():
        raise HTTPException(status_code=404, detail=f"Documents directory not found: {docs_dir}")
    if not list(docs_dir.glob("*.pdf")):
        raise HTTPException(status_code=404, detail="No PDF files found in documents directory")

    logger.info("Starting ingestion (offloaded to thread pool)...")
    try:
        result = await asyncio.to_thread(_run_ingest, docs_dir)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    from app.chat.engine import invalidate_program_cache
    invalidate_program_cache()

    return result
