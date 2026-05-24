from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import httpx

from .manifest import PdfEntry

log = logging.getLogger(__name__)

MAX_CONCURRENT = 3
DOWNLOAD_DELAY = 0.5
MAX_RETRIES = 3
RETRY_BACKOFF = 5.0


async def _download_one(
    client: httpx.AsyncClient,
    entry: PdfEntry,
    target_dir: Path,
    semaphore: asyncio.Semaphore,
) -> None:
    dest = target_dir / entry.filename
    if dest.exists() and dest.stat().st_size > 0:
        entry.downloaded = True
        entry.file_size_bytes = dest.stat().st_size
        return

    async with semaphore:
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await client.get(entry.source_url, follow_redirects=True)
                resp.raise_for_status()

                content_type = resp.headers.get("content-type", "")
                if "pdf" not in content_type and "octet-stream" not in content_type:
                    log.warning(
                        "Unexpected content-type for %s: %s",
                        entry.filename, content_type,
                    )

                dest.write_bytes(resp.content)
                entry.downloaded = True
                entry.file_size_bytes = len(resp.content)
                log.info("Downloaded %s (%d KB)", entry.filename, len(resp.content) // 1024)
                await asyncio.sleep(DOWNLOAD_DELAY)
                return

            except httpx.HTTPError as e:
                wait = RETRY_BACKOFF * attempt
                log.warning(
                    "Attempt %d/%d failed for %s: %s — retrying in %.0fs",
                    attempt, MAX_RETRIES, entry.filename, e, wait,
                )
                await asyncio.sleep(wait)

        log.error("Gave up on %s after %d attempts", entry.filename, MAX_RETRIES)


async def download_pdfs(entries: list[PdfEntry], target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    to_download = [e for e in entries if not e.downloaded]
    log.info("Downloading %d PDFs (skipping %d already downloaded)", len(to_download), len(entries) - len(to_download))

    async with httpx.AsyncClient(
        timeout=60,
        headers={"User-Agent": "campusLMU-Scraper/1.0"},
    ) as client:
        tasks = [_download_one(client, entry, target_dir, semaphore) for entry in to_download]
        await asyncio.gather(*tasks)

    downloaded = sum(1 for e in entries if e.downloaded)
    log.info("Done: %d/%d PDFs downloaded", downloaded, len(entries))
