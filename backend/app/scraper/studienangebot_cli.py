"""CLI for the Studiengangsfinder crawler.

Usage:
    cd backend && python -m app.scraper.studienangebot_cli
    cd backend && python -m app.scraper.studienangebot_cli --dry-run
"""
import argparse
import asyncio
import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stdout)

from app.scraper.studienangebot_crawler import fetch_master_programs, save_manifest


async def main(dry_run: bool = False) -> None:
    programs = await fetch_master_programs()
    logging.info("Fetched %d master programs", len(programs))

    if dry_run:
        for p in sorted(programs, key=lambda x: x.name):
            logging.info("  %s  [%s]", p.name, p.admission_type)
        return

    save_manifest(programs)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch master programs from LMU Studiengangsfinder")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't save")
    args = parser.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
