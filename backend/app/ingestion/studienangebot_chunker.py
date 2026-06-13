"""Chunker for Studiengangsfinder data.

Creates two types of chunks:
1. Grouped overview chunks — ~10 programs per chunk, grouped by admission type
2. Per-program admission detail chunks — one per program with Zugangsvoraussetzungen
"""
from __future__ import annotations

import re
import unicodedata
from collections import defaultdict

from app.ingestion.chunker import Chunk, MAX_CHUNK_TOKENS, count_tokens, _hard_split
from app.scraper.studienangebot_crawler import MasterProgram

STUDIENANGEBOT_URL = "https://www.lmu.de/de/studium/studienangebot/"
DOC_TYPE = "studienangebot"
PROGRAMS_PER_OVERVIEW_CHUNK = 10


def _slugify(name: str) -> str:
    s = name.lower()
    s = unicodedata.normalize("NFKD", s)
    s = s.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")[:80]


def _format_program_line(p: MasterProgram) -> str:
    parts = []
    if p.ects:
        parts.append(f"{p.ects} ECTS")
    if p.duration:
        parts.append(p.duration)
    if p.language:
        parts.append(p.language)
    if p.start_semester:
        parts.append(p.start_semester)
    meta = " | ".join(parts)

    lines = [f"**{p.name}** (Master {p.degree})"]
    if meta:
        lines.append(meta)
    if p.description:
        lines.append(p.description)
    return "\n".join(lines)


def _build_overview_chunks(programs: list[MasterProgram]) -> list[Chunk]:
    by_admission: dict[str, list[MasterProgram]] = defaultdict(list)
    for p in programs:
        key = p.admission_type or "Sonstige"
        by_admission[key].append(p)

    chunks: list[Chunk] = []
    chunk_idx = 0

    for admission_type, group in sorted(by_admission.items()):
        group.sort(key=lambda p: p.name)
        slug = _slugify(admission_type)

        for batch_num, i in enumerate(range(0, len(group), PROGRAMS_PER_OVERVIEW_CHUNK), 1):
            batch = group[i : i + PROGRAMS_PER_OVERVIEW_CHUNK]
            total_parts = (len(group) + PROGRAMS_PER_OVERVIEW_CHUNK - 1) // PROGRAMS_PER_OVERVIEW_CHUNK

            header = f"# Masterstudiengänge an der LMU — {admission_type}"
            if total_parts > 1:
                header += f" (Teil {batch_num}/{total_parts})"
            header += f"\n\nDie folgenden Masterstudiengänge der LMU München haben die Zulassungsart \"{admission_type}\":\n"

            body = "\n\n".join(_format_program_line(p) for p in batch)
            content = f"{header}\n{body}"

            if count_tokens(content) > MAX_CHUNK_TOKENS:
                for part in _hard_split(content, MAX_CHUNK_TOKENS):
                    chunks.append(_make_chunk(
                        content=part,
                        section_title=f"Masterstudiengänge — {admission_type}" + (f" (Teil {batch_num})" if total_parts > 1 else ""),
                        doc_filename=f"studienangebot-overview-{slug}-{batch_num}",
                        source_url=STUDIENANGEBOT_URL,
                        chunk_index=chunk_idx,
                    ))
                    chunk_idx += 1
            else:
                chunks.append(_make_chunk(
                    content=content,
                    section_title=f"Masterstudiengänge — {admission_type}" + (f" (Teil {batch_num})" if total_parts > 1 else ""),
                    doc_filename=f"studienangebot-overview-{slug}-{batch_num}",
                    source_url=STUDIENANGEBOT_URL,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1

    return chunks


def _build_admission_chunks(programs: list[MasterProgram]) -> list[Chunk]:
    chunks: list[Chunk] = []
    chunk_idx = 0

    for p in sorted(programs, key=lambda x: x.name):
        if not p.admission_details:
            continue

        parts = []
        if p.ects:
            parts.append(f"{p.ects} ECTS")
        if p.duration:
            parts.append(p.duration)
        if p.language:
            parts.append(p.language)
        if p.start_semester:
            parts.append(p.start_semester)
        meta = " | ".join(parts)

        content = f"# Zugangsvoraussetzungen: {p.name} (Master {p.degree})\n\n"
        if meta:
            content += f"{meta}\n"
        content += f"Zulassung: {p.admission_type}\n\n"
        content += f"## Zugangs- und Eignungsvoraussetzungen\n\n{p.admission_details}"
        if p.detail_url:
            content += f"\n\n→ Detailseite: {p.detail_url}"

        slug = _slugify(p.name)

        if count_tokens(content) > MAX_CHUNK_TOKENS:
            for part in _hard_split(content, MAX_CHUNK_TOKENS):
                chunks.append(_make_chunk(
                    content=part,
                    section_title=f"Zugangsvoraussetzungen: {p.name}",
                    doc_filename=f"studienangebot-admission-{slug}",
                    source_url=p.detail_url or STUDIENANGEBOT_URL,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1
        else:
            chunks.append(_make_chunk(
                content=content,
                section_title=f"Zugangsvoraussetzungen: {p.name}",
                doc_filename=f"studienangebot-admission-{slug}",
                source_url=p.detail_url or STUDIENANGEBOT_URL,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1

    return chunks


def _make_chunk(
    *,
    content: str,
    section_title: str,
    doc_filename: str,
    source_url: str,
    chunk_index: int,
) -> Chunk:
    return Chunk(
        content=content,
        doc_name="LMU Masterprogramme — Studienangebot",
        doc_filename=doc_filename,
        section_id="",
        section_title=section_title,
        absatz=None,
        page_number=0,
        part="",
        sub_part="",
        source_url=source_url,
        chunk_index=chunk_index,
        doc_type=DOC_TYPE,
        program_name="",
        topic_slug="studienangebot",
    )


def chunk_studienangebot(programs: list[MasterProgram]) -> list[Chunk]:
    overview = _build_overview_chunks(programs)
    admission = _build_admission_chunks(programs)
    return overview + admission
