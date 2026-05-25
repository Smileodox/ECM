from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from .classify import classify_doc_type
from .manifest import PdfEntry

log = logging.getLogger(__name__)

import os

SEARCH_URL = "https://cms-search.lmu.de/search/courses_by_name_asc/execute"
_search_user = os.environ.get("LMU_SEARCH_USER", "")
_search_pass = os.environ.get("LMU_SEARCH_PASS", "")
SEARCH_AUTH = (_search_user, _search_pass) if _search_user else None

AMTLICHE_CDN = "cms-cdn.lmu.de/media/contenthub/amtliche-veroeffentlichungen/"
PDF_HREF_RE = re.compile(r'href="([^"]*\.pdf)"', re.IGNORECASE)
REQUEST_DELAY = 1.0


@dataclass
class Program:
    name: str
    detail_url: str


async def fetch_master_programs(client: httpx.AsyncClient) -> list[Program]:
    programs = []
    page = 1
    while True:
        resp = await client.get(
            SEARCH_URL,
            params={
                "query": "*",
                "facet.filter.Graduation_value": '"Master"',
                "page": str(page),
            },
            auth=SEARCH_AUTH,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            break
        for result in results:
            name = (result.get("Name_value") or [""])[0]
            links = result.get("detailpage_link") or []
            if name and links:
                programs.append(Program(name=name, detail_url=links[0]))
        page += 1
    log.info("Found %d Master programs from API (%d pages)", len(programs), page - 1)
    return programs


async def extract_pdfs_from_page(
    client: httpx.AsyncClient,
    program: Program,
) -> list[PdfEntry]:
    try:
        resp = await client.get(program.detail_url, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        log.warning("Failed to fetch %s: %s", program.detail_url, e)
        return []

    html = resp.text
    entries = []
    seen_urls: set[str] = set()

    for match in PDF_HREF_RE.finditer(html):
        href = match.group(1)
        url = urljoin(program.detail_url, href)

        if AMTLICHE_CDN not in url:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # grab link text: scan backwards for > and forwards for </a
        start = match.start()
        end = match.end()
        link_text = ""
        close_tag = html.find("</a", end)
        open_tag = html.rfind(">", 0, end)
        if close_tag != -1 and open_tag != -1:
            raw = html[open_tag + 1 : close_tag]
            link_text = re.sub(r"<[^>]+>", "", raw).strip()

        filename = url.rsplit("/", 1)[-1]
        doc_type = classify_doc_type(link_text, url)

        entries.append(PdfEntry(
            source_url=url,
            filename=filename,
            doc_type=doc_type,
            programs=[program.name],
            link_text=link_text,
        ))

    return entries


async def fetch_all_pdfs(programs: list[Program]) -> list[PdfEntry]:
    all_entries: list[PdfEntry] = []
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "campusLMU-Scraper/1.0"}) as client:
        for i, program in enumerate(programs):
            entries = await extract_pdfs_from_page(client, program)
            if entries:
                log.info(
                    "[%d/%d] %s — %d PDFs",
                    i + 1, len(programs), program.name, len(entries),
                )
            else:
                log.info(
                    "[%d/%d] %s — no regulation PDFs found",
                    i + 1, len(programs), program.name,
                )
            all_entries.extend(entries)
            await asyncio.sleep(REQUEST_DELAY)
    return all_entries
