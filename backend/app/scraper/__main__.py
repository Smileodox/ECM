"""
LMU regulation PDF scraper.

Usage:
    cd backend && python -m app.scraper              # full run
    cd backend && python -m app.scraper --dry-run    # crawl only, no download
    cd backend && python -m app.scraper --resume     # download missing PDFs from existing manifest
"""
from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

from .downloader import download_pdfs
from .fetcher import fetch_all_pdfs, fetch_master_programs
from .manifest import PdfEntry, deduplicate, load_manifest, save_manifest

log = logging.getLogger(__name__)

DOCUMENTS_DIR = Path(__file__).resolve().parents[3] / "documents"
MANIFEST_PATH = DOCUMENTS_DIR / "manifest.json"


async def run(args: argparse.Namespace) -> None:
    existing = load_manifest(MANIFEST_PATH)
    log.info("Loaded %d entries from existing manifest", len(existing))

    if not args.resume:
        import httpx

        async with httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "campusLMU-Scraper/1.0"},
        ) as client:
            programs = await fetch_master_programs(client)

        entries = await fetch_all_pdfs(programs)
        all_entries = deduplicate(existing + entries)
        save_manifest(all_entries, MANIFEST_PATH)
        log.info("Manifest saved: %d unique PDFs from %d programs", len(all_entries), len(programs))
    else:
        all_entries = existing

    regulation_entries = [e for e in all_entries if e.doc_type != "other"]
    log.info(
        "Regulation PDFs: %d (psto=%d, eignung=%d, zulassung=%d, aenderung=%d, other=%d)",
        len(regulation_entries),
        sum(1 for e in all_entries if e.doc_type == "psto"),
        sum(1 for e in all_entries if e.doc_type == "eignung"),
        sum(1 for e in all_entries if e.doc_type == "zulassung"),
        sum(1 for e in all_entries if e.doc_type == "aenderung"),
        sum(1 for e in all_entries if e.doc_type == "other"),
    )

    if args.dry_run:
        log.info("Dry run — skipping download")
        return

    await download_pdfs(all_entries, DOCUMENTS_DIR)
    save_manifest(all_entries, MANIFEST_PATH)
    log.info("Final manifest saved")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape LMU regulation PDFs")
    parser.add_argument("--dry-run", action="store_true", help="Crawl only, don't download")
    parser.add_argument("--resume", action="store_true", help="Download missing PDFs from existing manifest")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
