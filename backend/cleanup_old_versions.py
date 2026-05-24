"""One-time script to delete superseded document chunks from Azure AI Search."""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def main():
    from app.ingestion.indexer import delete_document_chunks, _get_search_client
    from app.search.version_registry import VersionRegistry, get_registry

    registry = get_registry()
    blocked = registry.get_blocked_filenames()

    if not blocked:
        logger.info("No superseded documents found. Index is clean.")
        return

    logger.info("Found %d superseded documents to remove from index.", len(blocked))

    client = _get_search_client()
    doc_count_before = client.get_document_count()
    logger.info("Index document count before cleanup: %d", doc_count_before)

    total_deleted = 0
    for i, filename in enumerate(sorted(blocked), 1):
        deleted = delete_document_chunks(filename)
        total_deleted += deleted
        if deleted > 0:
            logger.info("[%d/%d] Deleted %d chunks from %s", i, len(blocked), deleted, filename)

    doc_count_after = client.get_document_count()
    logger.info(
        "Cleanup complete: deleted %d chunks from %d superseded documents. "
        "Index: %d → %d documents.",
        total_deleted, len(blocked), doc_count_before, doc_count_after,
    )


if __name__ == "__main__":
    main()
