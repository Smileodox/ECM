"""Standalone ingestion script — runs outside the HTTP server to avoid event-loop blocking."""
import json
import logging
import sys
import time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

from app.config import settings
from app.ingestion.parser import parse_all_pdfs
from app.ingestion.chunker import chunk_all_documents
from app.ingestion.indexer import (
    create_or_update_index,
    embed_and_upload_incremental,
    get_indexed_documents,
)

docs_dir = Path(settings.documents_dir)
manifest_path = docs_dir / "manifest.json"

logger.info("=== Starting ingestion pipeline ===")
logger.info("Documents dir: %s (%d PDFs)", docs_dir, len(list(docs_dir.glob("*.pdf"))))

# 1. Parse all PDFs
t0 = time.time()
parsed_docs = parse_all_pdfs(docs_dir)
logger.info("Parsed %d documents in %.1fs", len(parsed_docs), time.time() - t0)

# 2. Load manifest metadata
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
    logger.info("Loaded manifest: %d entries", len(manifest["entries"]))

# 3. Chunk all documents
t1 = time.time()
chunks = chunk_all_documents(parsed_docs, url_map=url_map, doc_type_map=doc_type_map, program_map=program_map)
logger.info("Created %d chunks in %.1fs", len(chunks), time.time() - t1)

# 4. Create/update index
create_or_update_index()

# 5. Group chunks by document
from collections import defaultdict
chunks_by_doc: dict[str, list] = defaultdict(list)
for chunk in chunks:
    chunks_by_doc[chunk.doc_filename].append(chunk)
logger.info("Grouped into %d documents", len(chunks_by_doc))

# 6. Check what's already indexed (for resumability)
already_indexed = get_indexed_documents()
logger.info("Already indexed: %d documents", len(already_indexed))

# 7. Embed and upload incrementally
t2 = time.time()
total_indexed = embed_and_upload_incremental(chunks_by_doc, already_indexed)
elapsed = time.time() - t2
logger.info("=== Ingestion complete: %d chunks indexed in %.1fs ===", total_indexed, elapsed)
logger.info("Total time: %.1fs", time.time() - t0)
