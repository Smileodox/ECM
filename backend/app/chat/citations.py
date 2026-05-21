import re

from app.models import Citation

# Matches any [...] block containing at least one "Quelle N" or "source N"
_CITATION_BLOCK_RE = re.compile(r"\[[^\]]*(?:Quelle|[Ss]ource)\s+\d+[^\]]*\]")
# Extracts individual citation indices from within a block
_CITE_INDEX_RE = re.compile(r"(?:Quelle|[Ss]ource)\s+(\d+)")


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
    return indices


def normalize_citation_markers(text: str) -> str:
    """Replace all citation blocks with canonical <<cite:N>> markers.

    Handles: [Quelle 1], [source 2], [Quelle 1, §14 Abs. 7; Quelle 2, §31], etc.
    """

    def _replace(match: re.Match) -> str:
        return "".join(
            f"<<cite:{m.group(1)}>>"
            for m in _CITE_INDEX_RE.finditer(match.group())
        )

    return _CITATION_BLOCK_RE.sub(_replace, text)
