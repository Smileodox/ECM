import re

from app.models import Citation

_AMENDMENT_PREFIX_RE = re.compile(r"\[Änderungssatzung:[^\]]*\]\s*")
_SECTION_HEADING_RE = re.compile(
    r"^##\s+(?:\*\*)?§\s*\d+[^\n]*(?:\*\*)?\s*\n*",
    re.MULTILINE,
)
_ELLIPSIS_MARKER_RE = re.compile(r"\[\.{3}\]\s*")

# Matches any [...] block containing at least one "Quelle N" or "source N"
_CITATION_BLOCK_RE = re.compile(r"\[[^\]]*(?:Quelle|[Ss]ource)\s+\d+[^\]]*\]")
# Extracts individual citation indices from within a block
_CITE_INDEX_RE = re.compile(r"(?:Quelle|[Ss]ource)\s+(\d+)")
# Matches bare "Quelle N" / "Source N" not already inside [...] — LLM sometimes
# omits the brackets despite instructions; normalize these as a fallback.
_BARE_CITATION_RE = re.compile(r"(?<!\[)(?:Quelle|[Ss]ource)\s+(\d+)(?!\s*(?:\d|\]))")


def format_citation_label(citation: Citation) -> str:
    """Format a citation for display: '§14 Masterarbeit, Abs. 3, S. 12'."""
    parts = [f"{citation.section_id} {citation.section_title}"]
    if citation.absatz:
        parts.append(citation.absatz)
    parts.append(f"S. {citation.page_number}")
    return ", ".join(parts)


def extract_used_citation_indices(text: str) -> set[int]:
    """Extract all citation indices from generated text, regardless of format."""
    indices: set[int] = set()
    for block in _CITATION_BLOCK_RE.finditer(text):
        for m in _CITE_INDEX_RE.finditer(block.group()):
            indices.add(int(m.group(1)))
    for m in _BARE_CITATION_RE.finditer(text):
        indices.add(int(m.group(1)))
    return indices


def strip_for_display(content: str) -> str:
    """Strip amendment prefix, section headings, and overlap markers for frontend display."""
    content = _AMENDMENT_PREFIX_RE.sub("", content)
    content = _ELLIPSIS_MARKER_RE.sub("", content)
    content = _SECTION_HEADING_RE.sub("", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return content.strip()


def normalize_citation_markers(text: str) -> str:
    """Replace all citation blocks with canonical <<cite:N>> markers.

    Handles: [Quelle 1], [source 2], [Quelle 1, §14 Abs. 7; Quelle 2, §31], etc.
    Also handles bare "Quelle N" without brackets as a fallback.
    """

    def _replace_block(match: re.Match) -> str:
        return "".join(
            f"<<cite:{m.group(1)}>>"
            for m in _CITE_INDEX_RE.finditer(match.group())
        )

    def _replace_bare(match: re.Match) -> str:
        return f"<<cite:{match.group(1)}>>"

    text = _CITATION_BLOCK_RE.sub(_replace_block, text)
    text = _BARE_CITATION_RE.sub(_replace_bare, text)
    return text
