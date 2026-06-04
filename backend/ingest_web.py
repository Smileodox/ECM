"""Ingest scraped web pages (LMU 1x1) into the campuslmu-web-v1 search index.

Usage:
    cd backend && python ingest_web.py
"""
import logging
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

from app.ingestion.indexer import ingest_web_chunks
from app.ingestion.web_chunker import chunk_all_web_pages
from app.scraper.web_scraper import load_web_manifest

logger.info("=== Starting web content ingestion ===")

t0 = time.time()

entries = load_web_manifest()
if not entries:
    logger.error("No web manifest found. Run the scraper first: python -m app.scraper.web_scraper_cli")
    sys.exit(1)

ok_entries = [e for e in entries if not e.error and e.content_md]
logger.info("Loaded %d entries from web manifest (%d OK, %d with errors)", len(entries), len(ok_entries), len(entries) - len(ok_entries))

pages = [
    {
        "content_md": e.content_md,
        "title": e.title,
        "url": e.url,
        "topic_slug": e.topic_slug,
        "external_links": e.external_links,
    }
    for e in ok_entries
]

t1 = time.time()
chunks = chunk_all_web_pages(pages)
logger.info("Created %d chunks from %d pages in %.1fs", len(chunks), len(pages), time.time() - t1)

t2 = time.time()
indexed = ingest_web_chunks(chunks)
logger.info("=== Web ingestion complete: %d chunks indexed in %.1fs ===", indexed, time.time() - t2)
logger.info("Total time: %.1fs", time.time() - t0)
