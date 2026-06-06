"""Scraper for LMU '1x1 des Studiums' web pages (depth-2 crawl)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from markdownify import markdownify as md

log = logging.getLogger(__name__)

INDEX_URL = "https://www.lmu.de/de/workspace-fuer-studierende/1x1-des-studiums/"
REQUEST_DELAY = 1.0
USER_AGENT = "campusLMU-Scraper/1.0"

STUDENT_PATH_PREFIXES = (
    "/de/workspace-fuer-studierende/",
    "/de/studium/hochschulzugang/",
    "/de/studium/studienangebot/",
    "/de/studium/wichtige-kontakte/",
    "/de/studium/beratung-und-service/",
    "/de/studium/1x1-fuer-studieninteressierte/",
    "/de/studium/internationale-vollzeit-studierende/",
    "/de/die-lmu/struktur/zentrale-universitaetsverwaltung/informations-und-kommunikationstechnik-dezernat-vi/it-servicedesk/",
)

SKIP_PATH_PREFIXES = (
    "/de/workspace-fuer-studierende/meldungen-und-termine/",
)

SKIP_EXTENSIONS = frozenset({".pdf", ".zip", ".docx", ".xlsx", ".jpg", ".png"})

EXTERNAL_DOMAINS = frozenset({
    "stuve.lmu.de",
    "www.studentenwerk-muenchen.de",
    "studentenwerk-muenchen.de",
    "www.it-servicedesk.uni-muenchen.de",
    "it-servicedesk.uni-muenchen.de",
})

WEB_MANIFEST_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "web_manifest.json"


@dataclass
class WebPageEntry:
    url: str
    title: str
    topic_slug: str
    depth: int = 0
    parent_url: str = ""
    content_md: str = ""
    content_hash: str = ""
    last_fetched: str = ""
    external_links: list[dict[str, str]] = field(default_factory=list)
    error: str = ""


def _slug_from_url(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    last_segment = path.rsplit("/", 1)[-1] if "/" in path else path
    last_segment = re.sub(r"\.html?$", "", last_segment)
    return last_segment or "index"


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    clean_path = re.sub(r"\.html?$", "", parsed.path.rstrip("/")) + "/"
    return f"{parsed.scheme}://{parsed.hostname}{clean_path}"


def _is_student_relevant(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if host in EXTERNAL_DOMAINS:
        return False
    if host != "www.lmu.de":
        return False
    path = parsed.path
    if any(path.rsplit(".", 1)[-1].lower() == ext.lstrip(".") for ext in SKIP_EXTENSIONS if "." in path):
        return False
    if any(path.startswith(skip) for skip in SKIP_PATH_PREFIXES):
        return False
    return any(path.startswith(prefix) for prefix in STUDENT_PATH_PREFIXES)


def _extract_main_content(soup: BeautifulSoup) -> str:
    main = soup.find(id="r-main")
    if not main:
        main = soup.find("main") or soup.find("article")
    if not main:
        main = soup.find("div", class_=re.compile(r"content", re.I))
    if not main:
        return ""

    for tag in main.find_all(["nav", "footer", "script", "style", "noscript"]):
        tag.decompose()

    breadcrumb = main.find(attrs={"aria-label": re.compile(r"breadcrumb", re.I)})
    if breadcrumb:
        breadcrumb.decompose()
    for bc in main.find_all(class_=re.compile(r"breadcrumb", re.I)):
        bc.decompose()

    return str(main)


def _extract_child_links(soup: BeautifulSoup, page_url: str, seen_urls: set[str]) -> list[tuple[str, str]]:
    main = soup.find(id="r-main") or soup.find("main") or soup
    children: list[tuple[str, str]] = []
    for a_tag in main.find_all("a", href=True):
        href = a_tag["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        abs_url = _normalize_url(urljoin(page_url, href))
        if abs_url in seen_urls:
            continue
        if not _is_student_relevant(abs_url):
            continue
        label = a_tag.get_text(strip=True) or _slug_from_url(abs_url)
        children.append((abs_url, label))
    return children


def _extract_external_links(soup: BeautifulSoup, page_url: str) -> list[dict[str, str]]:
    externals: list[dict[str, str]] = []
    seen: set[str] = set()
    for a_tag in soup.find_all("a", href=True):
        href = urljoin(page_url, a_tag["href"])
        host = urlparse(href).hostname or ""
        if host and host != "www.lmu.de" and not host.endswith(".lmu.de"):
            if href not in seen:
                seen.add(href)
                label = a_tag.get_text(strip=True) or href
                externals.append({"label": label, "url": href})
    for a_tag in soup.find_all("a", href=True):
        href = urljoin(page_url, a_tag["href"])
        host = urlparse(href).hostname or ""
        if host in EXTERNAL_DOMAINS and href not in seen:
            seen.add(href)
            label = a_tag.get_text(strip=True) or href
            externals.append({"label": label, "url": href})
    return externals


def _resolve_relative_links(markdown: str, base_url: str) -> str:
    """Convert relative markdown links to absolute URLs."""
    def _replace(match: re.Match) -> str:
        text = match.group(1)
        href = match.group(2)
        if href.startswith(("http://", "https://", "mailto:", "tel:", "#")):
            return match.group(0)
        absolute = urljoin(base_url, href)
        return f"[{text}]({absolute})"
    return re.sub(r"\[([^\]]*)\]\(([^)]+)\)", _replace, markdown)


_SOCIAL_NOISE = re.compile(
    r"(?:facebook|instagram|linkedin|bluesky|bsky\.app|twitter|youtube"
    r"|google\.com/maps|route\s*anzeigen|teilen)",
    re.IGNORECASE,
)


def _filter_external_links(links: list[dict[str, str]]) -> list[dict[str, str]]:
    """Remove social media, map links, and other noise from external links."""
    return [l for l in links if not _SOCIAL_NOISE.search(l["label"]) and not _SOCIAL_NOISE.search(l["url"])]


def _html_to_markdown(html: str, base_url: str = "") -> str:
    raw_md = md(html, heading_style="ATX", strip=["img"], newline_style="backslash")
    if base_url:
        raw_md = _resolve_relative_links(raw_md, base_url)
    lines = raw_md.split("\n")
    cleaned: list[str] = []
    blank_count = 0
    for line in lines:
        stripped = line.rstrip()
        if not stripped:
            blank_count += 1
            if blank_count <= 2:
                cleaned.append("")
        else:
            blank_count = 0
            cleaned.append(stripped)
    return "\n".join(cleaned).strip()


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


async def _fetch_page(
    client: httpx.AsyncClient, url: str, label: str, depth: int, parent_url: str,
) -> tuple[WebPageEntry, BeautifulSoup | None]:
    slug = _slug_from_url(url)
    entry = WebPageEntry(url=url, title=label, topic_slug=slug, depth=depth, parent_url=parent_url)

    try:
        resp = await client.get(url, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        entry.error = str(e)
        log.warning("Failed to fetch %s: %s", url, e)
        return entry, None

    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("h1")
    if title_tag:
        entry.title = title_tag.get_text(strip=True)

    main_html = _extract_main_content(soup)
    if not main_html:
        entry.error = "no main content found"
        log.warning("No main content for %s", url)
        return entry, None

    entry.content_md = _html_to_markdown(main_html, base_url=url)
    entry.content_hash = _content_hash(entry.content_md)
    entry.last_fetched = datetime.now(timezone.utc).isoformat()
    entry.external_links = _filter_external_links(_extract_external_links(soup, url))

    return entry, soup


async def scrape_1x1_pages(
    dry_run: bool = False,
    existing_manifest: list[WebPageEntry] | None = None,
    max_depth: int = 2,
) -> list[WebPageEntry]:
    existing_by_url: dict[str, WebPageEntry] = {}
    if existing_manifest:
        for e in existing_manifest:
            existing_by_url[_normalize_url(e.url)] = e

    async with httpx.AsyncClient(
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        # Depth 0: fetch 1x1 index page to get top-level links
        resp = await client.get(INDEX_URL, follow_redirects=True)
        resp.raise_for_status()
        index_soup = BeautifulSoup(resp.text, "html.parser")

        main = index_soup.find(id="r-main") or index_soup
        seen_urls: set[str] = {_normalize_url(INDEX_URL)}
        queue: list[tuple[str, str, int, str]] = []  # (url, label, depth, parent_url)

        for a_tag in main.find_all("a", href=True):
            href = a_tag["href"]
            abs_url = _normalize_url(urljoin(INDEX_URL, href))
            if abs_url in seen_urls:
                continue
            if not _is_student_relevant(abs_url):
                continue
            label = a_tag.get_text(strip=True) or _slug_from_url(abs_url)
            seen_urls.add(abs_url)
            queue.append((abs_url, label, 1, INDEX_URL))

        log.info("Depth 1: %d pages from 1x1 index", len(queue))

        if dry_run:
            log.info("Dry run — stopping before fetching content")
            return []

        all_entries: list[WebPageEntry] = []
        seen_hashes: set[str] = set()
        depth_2_queue: list[tuple[str, str, int, str]] = []
        counter = 0
        total_d1 = len(queue)

        for url, label, depth, parent_url in queue:
            counter += 1
            entry, soup = await _fetch_page(client, url, label, depth, parent_url)

            if entry.content_hash and entry.content_hash in seen_hashes:
                log.debug("[%d/%d] d%d %s — duplicate content, skipping", counter, total_d1, depth, entry.topic_slug)
                await asyncio.sleep(REQUEST_DELAY)
                continue
            if entry.content_hash:
                seen_hashes.add(entry.content_hash)

            old = existing_by_url.get(_normalize_url(url))
            if old and old.content_hash and old.content_hash == entry.content_hash:
                log.debug("[%d/%d] d%d %s — unchanged", counter, total_d1, depth, entry.topic_slug)
                entry.last_fetched = old.last_fetched
            else:
                status = "new" if not old else "updated"
                log.info("[%d/%d] d%d %s — %s (%d chars)", counter, total_d1, depth, entry.topic_slug, status, len(entry.content_md))

            all_entries.append(entry)

            if soup and depth < max_depth:
                child_links = _extract_child_links(soup, url, seen_urls)
                for child_url, child_label in child_links:
                    seen_urls.add(child_url)
                    depth_2_queue.append((child_url, child_label, depth + 1, url))

            await asyncio.sleep(REQUEST_DELAY)

        if depth_2_queue:
            log.info("Depth 2: %d additional pages from sub-links", len(depth_2_queue))
            total_d2 = len(depth_2_queue)
            for i, (url, label, depth, parent_url) in enumerate(depth_2_queue):
                entry, _ = await _fetch_page(client, url, label, depth, parent_url)

                if entry.content_hash and entry.content_hash in seen_hashes:
                    log.debug("[%d/%d] d%d %s — duplicate content, skipping", i + 1, total_d2, depth, entry.topic_slug)
                    await asyncio.sleep(REQUEST_DELAY)
                    continue
                if entry.content_hash:
                    seen_hashes.add(entry.content_hash)

                old = existing_by_url.get(_normalize_url(url))
                if old and old.content_hash and old.content_hash == entry.content_hash:
                    log.debug("[%d/%d] d%d %s — unchanged", i + 1, total_d2, depth, entry.topic_slug)
                    entry.last_fetched = old.last_fetched
                else:
                    status = "new" if not old else "updated"
                    log.info("[%d/%d] d%d %s — %s (%d chars)", i + 1, total_d2, depth, entry.topic_slug, status, len(entry.content_md))

                all_entries.append(entry)
                await asyncio.sleep(REQUEST_DELAY)

    ok = [e for e in all_entries if not e.error]
    failed = [e for e in all_entries if e.error]
    log.info("Scraping done: %d OK, %d failed, total %d", len(ok), len(failed), len(all_entries))
    return all_entries


def load_web_manifest(path: Path | None = None) -> list[WebPageEntry]:
    p = path or WEB_MANIFEST_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    entries = []
    for e in data.get("entries", []):
        entries.append(WebPageEntry(**{
            k: v for k, v in e.items()
            if k in WebPageEntry.__dataclass_fields__
        }))
    return entries


def save_web_manifest(entries: list[WebPageEntry], path: Path | None = None) -> None:
    p = path or WEB_MANIFEST_PATH
    data = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(entries),
        "ok_pages": len([e for e in entries if not e.error]),
        "depth_1_pages": len([e for e in entries if e.depth == 1]),
        "depth_2_pages": len([e for e in entries if e.depth == 2]),
        "entries": [asdict(e) for e in entries],
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Web manifest saved to %s (%d entries)", p, len(entries))
