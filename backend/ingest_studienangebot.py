"""Ingest Studiengangsfinder data into the campuslmu-web-v1 search index.

Usage:
    cd backend && python ingest_studienangebot.py
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
from app.ingestion.studienangebot_chunker import chunk_studienangebot
from app.scraper.studienangebot_crawler import load_manifest

logger.info("=== Starting Studienangebot ingestion ===")
t0 = time.time()

programs = load_manifest()
if not programs:
    logger.error("No studienangebot manifest found. Run the crawler first: python -m app.scraper.studienangebot_cli")
    sys.exit(1)

logger.info("Loaded %d master programs from manifest", len(programs))

t1 = time.time()
chunks = chunk_studienangebot(programs)
logger.info("Created %d chunks in %.1fs", len(chunks), time.time() - t1)

overview_chunks = [c for c in chunks if "overview" in c.doc_filename]
admission_chunks = [c for c in chunks if "admission" in c.doc_filename]
logger.info("  Overview chunks: %d", len(overview_chunks))
logger.info("  Admission chunks: %d", len(admission_chunks))

t2 = time.time()
indexed = ingest_web_chunks(chunks)
logger.info("=== Studienangebot ingestion complete: %d chunks indexed in %.1fs ===", indexed, time.time() - t2)
logger.info("Total time: %.1fs", time.time() - t0)
