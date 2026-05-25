import hashlib
import re
from dataclasses import dataclass

import tiktoken

from app.ingestion.parser import ParsedPage

_enc = tiktoken.get_encoding("cl100k_base")

# --- Regex patterns for PyMuPDF4LLM markdown output ---
# Matches section headings like: ## **§ 1 Gegenstand des Studiengangs und Zweck der Masterprüfung**
# Also handles: ## **§ 13 (nicht belegt)** and ## **§ 1** (title-less, common in Änderungssatzungen)
SECTION_HEADING_PATTERN = re.compile(
    r"^##\s+\*\*§\s*(\d+)\s*(.*?)\*\*\s*$", re.MULTILINE
)
# Matches Absatz markers: "(1)", "(2)" at the start of a line
ABSATZ_PATTERN = re.compile(r"^\((\d+)\)", re.MULTILINE)
# Matches part headers like: ## **I. Allgemeines**
PART_PATTERN = re.compile(
    r"^##\s+\*\*(I{1,3}V?|IV|V|VI)\.\s+(.+?)\*\*\s*$", re.MULTILINE
)
# Table of contents indicator
TOC_PATTERN = re.compile(r"Inhaltsübersicht", re.IGNORECASE)
AENDERUNG_TITLE_PATTERN = re.compile(
    r"(?:Satzung\s+zur\s+)?Änderung\s+der\s+(Prüfungs-?\s*(?:und\s+)?Studienordnung|Eignungssatzung|Zulassungsordnung).+?(?:für\s+den\s+\w+studiengang\s+)?(.+?)\s*\((\d{4})\)",
    re.IGNORECASE | re.DOTALL,
)
AENDERUNG_MODIFIED_SECTIONS_PATTERN = re.compile(
    r"§\s*(\d+)\s+(?:erhält|wird|entfällt|lautet)", re.IGNORECASE,
)

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
    doc_type: str = ""  # psto | eignung | zulassung | aenderung
    program_name: str = ""  # e.g. "Informatik"

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


def _last_sentences(text: str, n: int = 2) -> str:
    """Extract the last n sentences from text for overlap context."""
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    picked = sentences[-n:] if len(sentences) > n else []
    return " ".join(picked)


def _split_section_by_absatz(section: _SectionBlock) -> list[tuple[str, str | None]]:
    """Split a section's body into Absatz groups with overlap context.

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
    prev_group_text = ""

    preamble = body[:absatz_positions[0][0]].strip()
    preamble_has_content = bool(preamble) and count_tokens(preamble) > count_tokens(section.heading) + 5

    if preamble_has_content:
        groups.append((preamble, "Einleitung"))
        prev_group_text = preamble

    current_texts: list[str] = [preamble] if (preamble and not preamble_has_content) else []
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
            group_text = "\n\n".join(current_texts)
            groups.append((group_text, label))
            # Start new group with heading + overlap from previous group
            overlap = _last_sentences(group_text)
            new_start: list[str] = [section.heading]
            if overlap:
                new_start.append(f"[...] {overlap}")
            new_start.append(absatz_text)
            current_texts = new_start
            prev_group_text = group_text
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


def _extract_aenderung_context(pages: list[ParsedPage]) -> str:
    """For Änderungssatzungen, extract which original document and sections are modified."""
    first_pages_text = " ".join(p.text for p in pages[:3])

    title_match = AENDERUNG_TITLE_PATTERN.search(first_pages_text)
    if not title_match:
        return ""

    original_doc_type = title_match.group(1).strip()
    original_year = title_match.group(3)

    modified_sections = sorted(set(
        f"§{m.group(1)}" for m in AENDERUNG_MODIFIED_SECTIONS_PATTERN.finditer(first_pages_text)
    ))

    parts = [f"[Änderungssatzung: Ändert die {original_doc_type} (Fassung {original_year})."]
    if modified_sections:
        parts.append(f"Geänderte Paragraphen: {', '.join(modified_sections)}.")
    parts.append("Die nicht genannten Paragraphen der Ursprungsordnung gelten unverändert weiter.]")
    return " ".join(parts)


def _split_on_sentences(text: str, max_tokens: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for sent in sentences:
        sent_tokens = count_tokens(sent)
        if current and current_tokens + sent_tokens > max_tokens:
            chunks.append(" ".join(current))
            current = [sent]
            current_tokens = sent_tokens
        else:
            current.append(sent)
            current_tokens += sent_tokens
    if current:
        chunks.append(" ".join(current))
    return chunks if chunks else [text]


def _hard_split(text: str, max_tokens: int) -> list[str]:
    """Split text into chunks of at most max_tokens, splitting on paragraph then sentence boundaries."""
    if count_tokens(text) <= max_tokens:
        return [text]
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0
    for para in paragraphs:
        para_tokens = count_tokens(para)
        if para_tokens > max_tokens:
            if current:
                chunks.append("\n\n".join(current))
                current = []
                current_tokens = 0
            chunks.extend(_split_on_sentences(para, max_tokens))
        elif current and current_tokens + para_tokens > max_tokens:
            chunks.append("\n\n".join(current))
            current = [para]
            current_tokens = para_tokens
        else:
            current.append(para)
            current_tokens += para_tokens
    if current:
        chunks.append("\n\n".join(current))
    return chunks if chunks else [text]


def chunk_document(
    pages: list[ParsedPage],
    doc_filename: str,
    source_url: str = "",
    doc_type: str = "",
    program_name: str = "",
) -> list[Chunk]:
    """Chunk a parsed document into section-aware chunks with metadata."""
    doc_name = _extract_doc_name(pages)
    full_text, boundaries = _build_full_text(pages)
    sections = _split_into_sections(full_text, boundaries)

    aenderung_prefix = ""
    if doc_type == "aenderung":
        aenderung_prefix = _extract_aenderung_context(pages)

    chunks: list[Chunk] = []
    chunk_idx = 0

    for section in sections:
        section_content = (aenderung_prefix + "\n\n" + section.body) if aenderung_prefix else section.body
        tokens = count_tokens(section_content)

        if tokens <= MAX_CHUNK_TOKENS:
            chunks.append(Chunk(
                content=section_content,
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
                doc_type=doc_type,
                program_name=program_name,
            ))
            chunk_idx += 1
        else:
            # Split by Absatz groups
            groups = _split_section_by_absatz(section)
            for text, absatz_label in groups:
                chunk_content = (aenderung_prefix + "\n\n" + text) if aenderung_prefix else text
                sub_chunks = _hard_split(chunk_content, MAX_CHUNK_TOKENS)
                for sc in sub_chunks:
                    chunks.append(Chunk(
                        content=sc,
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
                        doc_type=doc_type,
                        program_name=program_name,
                    ))
                    chunk_idx += 1

    return chunks


def chunk_all_documents(
    parsed_docs: dict[str, list[ParsedPage]],
    url_map: dict[str, str] | None = None,
    doc_type_map: dict[str, str] | None = None,
    program_map: dict[str, str] | None = None,
    generate_summaries: bool = False,
) -> list[Chunk]:
    """Chunk all parsed documents."""
    all_chunks: list[Chunk] = []
    for filename, pages in parsed_docs.items():
        source_url = (url_map or {}).get(filename, "")
        doc_type = (doc_type_map or {}).get(filename, "")
        program_name = (program_map or {}).get(filename, "")
        doc_chunks = chunk_document(
            pages, filename,
            source_url=source_url,
            doc_type=doc_type,
            program_name=program_name,
        )
        if generate_summaries and doc_chunks:
            from app.ingestion.summarizer import generate_summary_chunk
            summary = generate_summary_chunk(
                pages,
                doc_filename=filename,
                doc_name=doc_chunks[0].doc_name,
                source_url=source_url,
                doc_type=doc_type,
                program_name=program_name,
                chunk_index=len(doc_chunks),
            )
            if summary:
                doc_chunks.append(summary)
        all_chunks.extend(doc_chunks)
    return all_chunks
