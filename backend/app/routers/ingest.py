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

    # Parse (only current versions)
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

    # Build metadata maps from manifest if available
    import json
    manifest_path = docs_dir / "manifest.json"
    url_map: dict[str, str] = {}
    doc_type_map: dict[str, str] = {}
    program_map: dict[str, str] = {}

    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for entry in manifest["entries"]:
            fn = entry["filename"]
            url_map[fn] = entry["source_url"]
            doc_type_map[fn] = entry.get("doc_type", "")
            programs = entry.get("programs", [])
            program_map[fn] = programs[0] if programs else ""
    else:
        url_map = {
            filename: f"{settings.lmu_cdn_base_url}/{filename}"
            for filename in parsed_docs
        }

    chunks = chunk_all_documents(
        parsed_docs,
        url_map=url_map,
        doc_type_map=doc_type_map,
        program_map=program_map,
        generate_summaries=True,
    )
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
