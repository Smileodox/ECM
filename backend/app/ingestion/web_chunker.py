"""Chunker for HTML-derived markdown content (LMU 1x1 web pages).

Splits on H2/H3 headings instead of §-sections. Reuses Chunk dataclass
and sentence-splitting logic from the regulation chunker.
"""
from __future__ import annotations

import re

from app.ingestion.chunker import Chunk, MAX_CHUNK_TOKENS, TARGET_CHUNK_TOKENS, count_tokens, _hard_split

H2_PATTERN = re.compile(r"^##\s+(.+)$", re.MULTILINE)
H3_PATTERN = re.compile(r"^###\s+(.+)$", re.MULTILINE)


def _split_by_heading(text: str, pattern: re.Pattern) -> list[tuple[str, str]]:
    """Split text by a heading pattern. Returns [(heading_title, section_text), ...]."""
    matches = list(pattern.finditer(text))
    if not matches:
        return [("", text)]

    sections: list[tuple[str, str]] = []

    preamble = text[:matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))

    for i, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections.append((title, body))

    return sections


def chunk_web_page(
    content_md: str,
    *,
    page_title: str,
    source_url: str,
    topic_slug: str,
) -> list[Chunk]:
    if not content_md.strip():
        return []

    h2_sections = _split_by_heading(content_md, H2_PATTERN)
    chunks: list[Chunk] = []
    chunk_idx = 0

    for h2_title, h2_body in h2_sections:
        h2_tokens = count_tokens(h2_body)

        if h2_tokens <= MAX_CHUNK_TOKENS:
            chunks.append(_make_chunk(
                content=h2_body,
                section_title=h2_title or page_title,
                source_url=source_url,
                topic_slug=topic_slug,
                page_title=page_title,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1
            continue

        h3_sections = _split_by_heading(h2_body, H3_PATTERN)

        if len(h3_sections) <= 1:
            for part in _hard_split(h2_body, MAX_CHUNK_TOKENS):
                heading_prefix = f"## {h2_title}\n\n" if h2_title else ""
                chunks.append(_make_chunk(
                    content=heading_prefix + part if not part.startswith("## ") else part,
                    section_title=h2_title or page_title,
                    source_url=source_url,
                    topic_slug=topic_slug,
                    page_title=page_title,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1
            continue

        for h3_title, h3_body in h3_sections:
            h3_tokens = count_tokens(h3_body)

            if h3_tokens <= MAX_CHUNK_TOKENS:
                combined_title = f"{h2_title} > {h3_title}" if h2_title and h3_title else (h2_title or h3_title or page_title)
                chunks.append(_make_chunk(
                    content=h3_body,
                    section_title=combined_title,
                    source_url=source_url,
                    topic_slug=topic_slug,
                    page_title=page_title,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1
            else:
                heading_prefix = f"## {h2_title}\n\n### {h3_title}\n\n" if h3_title else f"## {h2_title}\n\n"
                for part in _hard_split(h3_body, MAX_CHUNK_TOKENS):
                    combined_title = f"{h2_title} > {h3_title}" if h2_title and h3_title else (h2_title or h3_title or page_title)
                    chunks.append(_make_chunk(
                        content=heading_prefix + part if not part.startswith("#") else part,
                        section_title=combined_title,
                        source_url=source_url,
                        topic_slug=topic_slug,
                        page_title=page_title,
                        chunk_index=chunk_idx,
                    ))
                    chunk_idx += 1

    return chunks


def _make_chunk(
    *,
    content: str,
    section_title: str,
    source_url: str,
    topic_slug: str,
    page_title: str,
    chunk_index: int,
) -> Chunk:
    return Chunk(
        content=content,
        doc_name=page_title,
        doc_filename=topic_slug,
        section_id="",
        section_title=section_title,
        absatz=None,
        page_number=0,
        part="",
        sub_part="",
        source_url=source_url,
        chunk_index=chunk_index,
        doc_type="web_1x1",
        program_name="",
        topic_slug=topic_slug,
    )


def chunk_all_web_pages(
    pages: list[dict],
) -> list[Chunk]:
    """Chunk all scraped web pages.

    Args:
        pages: List of dicts with keys: content_md, title, url, topic_slug
    """
    all_chunks: list[Chunk] = []
    for page in pages:
        if not page.get("content_md"):
            continue
        chunks = chunk_web_page(
            content_md=page["content_md"],
            page_title=page["title"],
            source_url=page["url"],
            topic_slug=page["topic_slug"],
        )
        all_chunks.extend(chunks)
    return all_chunks
