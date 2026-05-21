import hashlib
import re
from dataclasses import dataclass

import tiktoken

from app.ingestion.parser import ParsedPage

_enc = tiktoken.get_encoding("cl100k_base")

# --- Regex patterns for PyMuPDF4LLM markdown output ---
# Matches section headings like: ## **§ 1 Gegenstand des Studiengangs und Zweck der Masterprüfung**
# Also handles: ## **§ 13 (nicht belegt)**
SECTION_HEADING_PATTERN = re.compile(
    r"^##\s+\*\*§\s*(\d+)\s+(.+?)\*\*\s*$", re.MULTILINE
)
# Matches Absatz markers: "(1)", "(2)" at the start of a line
ABSATZ_PATTERN = re.compile(r"^\((\d+)\)", re.MULTILINE)
# Matches part headers like: ## **I. Allgemeines**
PART_PATTERN = re.compile(
    r"^##\s+\*\*(I{1,3}V?|IV|V|VI)\.\s+(.+?)\*\*\s*$", re.MULTILINE
)
# Table of contents indicator
TOC_PATTERN = re.compile(r"Inhaltsübersicht", re.IGNORECASE)

MAX_CHUNK_TOKENS = 800
TARGET_CHUNK_TOKENS = 600


@dataclass
class Chunk:
    content: str
    doc_name: str
    doc_filename: str
    section_id: str  # e.g. "§14"
    section_title: str  # e.g. "Masterarbeit"
    absatz: str | None  # e.g. "Abs. 1-3" or None
    page_number: int
    part: str  # e.g. "III. Masterprüfung"
    sub_part: str  # e.g. ""
    source_url: str = ""
    chunk_index: int = 0

    @property
    def id(self) -> str:
        raw = f"{self.doc_filename}:{self.section_id}:{self.absatz}:{self.chunk_index}"
        return hashlib.md5(raw.encode()).hexdigest()

    @property
    def token_count(self) -> int:
        return len(_enc.encode(self.content))


@dataclass
class _SectionBlock:
    """Intermediate representation of a parsed §-section."""
    section_id: str
    section_title: str
    heading: str  # e.g. "## **§ 14 Masterarbeit**"
    body: str
    page_number: int
    part: str


def count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _extract_doc_name(pages: list[ParsedPage]) -> str:
    """Extract a human-readable document name from the first pages."""
    for page in pages[:3]:
        # Look for bold title patterns from PyMuPDF4LLM
        match = re.search(
            r"\*\*((?:Prüfungs-?\s*und\s*)?(?:Studien|Zulassungs|Eignungs\w*)(?:ordnung|satzung).+?)\*\*",
            page.text,
            re.DOTALL,
        )
        if match:
            name = match.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            return name

        # Fallback: plain text
        match = re.search(
            r"((?:Prüfungs-?\s*und\s*)?(?:Studien|Zulassungs|Eignungs\w*)(?:ordnung|satzung).+?)(?:\n\n|Vom\s)",
            page.text,
            re.DOTALL,
        )
        if match:
            name = match.group(1).strip()
            name = re.sub(r"\s+", " ", name)
            return name

    return "Unbekanntes Dokument"


def _is_toc_page(page: ParsedPage) -> bool:
    """Check if a page is a table of contents page."""
    return bool(TOC_PATTERN.search(page.text))


def _build_full_text(pages: list[ParsedPage]) -> tuple[str, list[tuple[int, int]]]:
    """Concatenate all non-TOC pages and track page boundaries.

    Returns (full_text, [(char_offset, page_number), ...]).
    Also skips the title page (page 1) if it has no § content.
    """
    parts: list[str] = []
    boundaries: list[tuple[int, int]] = []
    offset = 0

    for page in pages:
        if _is_toc_page(page):
            continue
        # Skip title page (usually page 1) if it has no section content
        if page.page_number == 1 and not SECTION_HEADING_PATTERN.search(page.text):
            continue
        boundaries.append((offset, page.page_number))
        parts.append(page.text)
        offset += len(page.text) + 1  # +1 for the joining newline

    return "\n".join(parts), boundaries


def _page_for_offset(offset: int, boundaries: list[tuple[int, int]]) -> int:
    """Find the page number for a given character offset."""
    page_num = boundaries[0][1] if boundaries else 1
    for boundary_offset, boundary_page in boundaries:
        if boundary_offset <= offset:
            page_num = boundary_page
        else:
            break
    return page_num


def _split_into_sections(full_text: str, boundaries: list[tuple[int, int]]) -> list[_SectionBlock]:
    """Split the full text into §-section blocks."""
    # Find all § section headings
    section_starts: list[tuple[int, int, str, str, str]] = []
    # (match_start, section_num, title, heading_text, section_id)

    for match in SECTION_HEADING_PATTERN.finditer(full_text):
        section_num = int(match.group(1))
        title = match.group(2).strip()
        heading = match.group(0).strip()
        section_id = f"§{section_num}"
        section_starts.append((match.start(), section_num, title, heading, section_id))

    if not section_starts:
        return []

    # Track current part context
    current_part = ""
    sections: list[_SectionBlock] = []

    for i, (pos, _num, title, heading, section_id) in enumerate(section_starts):
        # End of this section = start of next section heading, or end of text
        end_pos = section_starts[i + 1][0] if i + 1 < len(section_starts) else len(full_text)
        body = full_text[pos:end_pos].strip()

        # Check for part headers in the text before this section
        if i == 0:
            preceding = full_text[:pos]
        else:
            preceding = full_text[section_starts[i - 1][0]:pos]

        for part_match in PART_PATTERN.finditer(preceding):
            current_part = f"{part_match.group(1)}. {part_match.group(2).strip()}"

        page = _page_for_offset(pos, boundaries)

        sections.append(_SectionBlock(
            section_id=section_id,
            section_title=title,
            heading=heading,
            body=body,
            page_number=page,
            part=current_part,
        ))

    return sections


def _split_section_by_absatz(section: _SectionBlock) -> list[tuple[str, str | None]]:
    """Split a section's body into Absatz groups.

    Returns list of (text, absatz_label) tuples.
    """
    body = section.body
    # Find all Absatz markers
    absatz_positions: list[tuple[int, int]] = []  # (char_pos, absatz_num)
    for match in ABSATZ_PATTERN.finditer(body):
        absatz_positions.append((match.start(), int(match.group(1))))

    if not absatz_positions:
        return [(body, None)]

    groups: list[tuple[str, str | None]] = []

    # Text before the first Absatz (the heading part)
    preamble = body[:absatz_positions[0][0]].strip()

    # Group Absätze into chunks that stay within token limits
    current_texts: list[str] = [preamble] if preamble else []
    current_absatz_start: int | None = None
    current_absatz_end: int | None = None

    for i, (pos, absatz_num) in enumerate(absatz_positions):
        end_pos = absatz_positions[i + 1][0] if i + 1 < len(absatz_positions) else len(body)
        absatz_text = body[pos:end_pos].strip()

        if current_absatz_start is None:
            current_absatz_start = absatz_num

        # Check if adding this Absatz would exceed the target
        tentative = "\n\n".join(current_texts + [absatz_text])
        if count_tokens(tentative) > TARGET_CHUNK_TOKENS and current_texts:
            # Emit current group
            label = _absatz_label(current_absatz_start, current_absatz_end)
            groups.append(("\n\n".join(current_texts), label))
            # Start new group with the section heading prepended for context
            current_texts = [section.heading, absatz_text]
            current_absatz_start = absatz_num
            current_absatz_end = absatz_num
        else:
            current_texts.append(absatz_text)
            current_absatz_end = absatz_num

    # Emit remaining
    if current_texts:
        label = _absatz_label(current_absatz_start, current_absatz_end)
        groups.append(("\n\n".join(current_texts), label))

    return groups


def _absatz_label(start: int | None, end: int | None) -> str | None:
    if start is None:
        return None
    if end is None or start == end:
        return f"Abs. {start}"
    return f"Abs. {start}-{end}"


def chunk_document(
    pages: list[ParsedPage],
    doc_filename: str,
    source_url: str = "",
) -> list[Chunk]:
    """Chunk a parsed document into section-aware chunks with metadata."""
    doc_name = _extract_doc_name(pages)
    full_text, boundaries = _build_full_text(pages)
    sections = _split_into_sections(full_text, boundaries)

    chunks: list[Chunk] = []
    chunk_idx = 0

    for section in sections:
        tokens = count_tokens(section.body)

        if tokens <= MAX_CHUNK_TOKENS:
            chunks.append(Chunk(
                content=section.body,
                doc_name=doc_name,
                doc_filename=doc_filename,
                section_id=section.section_id,
                section_title=section.section_title,
                absatz=None,
                page_number=section.page_number,
                part=section.part,
                sub_part="",
                source_url=source_url,
                chunk_index=chunk_idx,
            ))
            chunk_idx += 1
        else:
            # Split by Absatz groups
            groups = _split_section_by_absatz(section)
            for text, absatz_label in groups:
                chunks.append(Chunk(
                    content=text,
                    doc_name=doc_name,
                    doc_filename=doc_filename,
                    section_id=section.section_id,
                    section_title=section.section_title,
                    absatz=absatz_label,
                    page_number=section.page_number,
                    part=section.part,
                    sub_part="",
                    source_url=source_url,
                    chunk_index=chunk_idx,
                ))
                chunk_idx += 1

    return chunks


def chunk_all_documents(
    parsed_docs: dict[str, list[ParsedPage]],
    url_map: dict[str, str] | None = None,
) -> list[Chunk]:
    """Chunk all parsed documents."""
    all_chunks: list[Chunk] = []
    for filename, pages in parsed_docs.items():
        source_url = (url_map or {}).get(filename, "")
        doc_chunks = chunk_document(pages, filename, source_url=source_url)
        all_chunks.extend(doc_chunks)
    return all_chunks
