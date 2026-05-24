"""Re-ingest allowed Änderungssatzung documents that are missing from the index."""

import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.config import settings
    from app.ingestion.chunker import chunk_document
    from app.ingestion.indexer import (
        create_or_update_index,
        get_indexed_documents,
        embed_and_upload_incremental,
    )
    from app.ingestion.parser import parse_pdf
    from app.search.version_registry import get_registry

    docs_dir = Path(settings.documents_dir)
    manifest_path = docs_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())

    registry = get_registry()
    blocked = registry.get_blocked_filenames()

    aenderung_entries = [
        e for e in manifest["entries"]
        if e.get("doc_type") == "aenderung" and e["filename"] not in blocked
    ]
    logger.info("Found %d allowed Änderungssatzung files.", len(aenderung_entries))

    already_indexed = get_indexed_documents()
    to_ingest = [e for e in aenderung_entries if e["filename"] not in already_indexed]
    logger.info("%d already indexed, %d to ingest.", len(aenderung_entries) - len(to_ingest), len(to_ingest))

    if not to_ingest:
        logger.info("Nothing to do.")
        return

    create_or_update_index()

    chunks_by_doc = {}
    for entry in to_ingest:
        fn = entry["filename"]
        pdf_path = docs_dir / fn
        if not pdf_path.exists():
            logger.warning("File not found: %s", pdf_path)
            continue

        pages = parse_pdf(pdf_path)
        if not pages:
            logger.warning("No pages parsed from %s", fn)
            continue

        programs = entry.get("programs", [])
        chunks = chunk_document(
            pages,
            doc_filename=fn,
            source_url=entry.get("source_url", ""),
            doc_type="aenderung",
            program_name=programs[0] if programs else "",
        )
        if chunks:
            chunks_by_doc[fn] = chunks
            logger.info("Chunked %s: %d chunks", fn, len(chunks))

    if not chunks_by_doc:
        logger.info("No chunks to ingest.")
        return

    total = embed_and_upload_incremental(chunks_by_doc, already_indexed=set())
    logger.info("Done. Ingested %d chunks from %d Änderungssatzung documents.", total, len(chunks_by_doc))


if __name__ == "__main__":
    main()
