"""
CLI for the 1x1 web scraper.

Usage:
    cd backend && python -m app.scraper.web_scraper_cli
    cd backend && python -m app.scraper.web_scraper_cli --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging

from .web_scraper import (
    WEB_MANIFEST_PATH,
    load_web_manifest,
    save_web_manifest,
    scrape_1x1_pages,
)


async def run(args: argparse.Namespace) -> None:
    existing = load_web_manifest()
    logging.info("Loaded %d entries from existing web manifest", len(existing))

    entries = await scrape_1x1_pages(
        dry_run=args.dry_run,
        existing_manifest=existing or None,
    )

    if entries:
        save_web_manifest(entries, WEB_MANIFEST_PATH)


def main() -> None:
    parser = argparse.ArgumentParser(description="Scrape LMU 1x1 des Studiums pages")
    parser.add_argument("--dry-run", action="store_true", help="List pages only, don't fetch content")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    asyncio.run(run(args))


if __name__ == "__main__":
    main()
