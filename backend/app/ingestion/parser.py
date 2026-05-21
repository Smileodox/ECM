import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf4llm


@dataclass
class ParsedPage:
    text: str
    page_number: int  # 1-based


def parse_pdf(pdf_path: str | Path) -> list[ParsedPage]:
    """Parse a PDF into per-page Markdown text using PyMuPDF4LLM."""
    pages = pymupdf4llm.to_markdown(str(pdf_path), page_chunks=True)

    parsed = []
    for page_data in pages:
        page_num = page_data["metadata"]["page_number"]  # already 1-based
        text = page_data["text"]

        # Strip running headers/footers like "- 12 -"
        text = re.sub(r"^-\s*\d+\s*-\s*$", "", text, flags=re.MULTILINE)

        # Strip excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        text = text.strip()
        if text:
            parsed.append(ParsedPage(text=text, page_number=page_num))

    return parsed


def parse_all_pdfs(documents_dir: str | Path) -> dict[str, list[ParsedPage]]:
    """Parse all PDFs in a directory. Returns {filename: [ParsedPage, ...]}."""
    docs_path = Path(documents_dir)
    results = {}

    for pdf_file in sorted(docs_path.glob("*.pdf")):
        results[pdf_file.name] = parse_pdf(pdf_file)

    return results
