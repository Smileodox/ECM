import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

import pymupdf4llm

logger = logging.getLogger(__name__)

# Per-file parse time above which we flag the doc as a likely OCR/scanned case
SLOW_PARSE_WARN_SECONDS = 20.0


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

        # Strip running headers/footers
        text = re.sub(r"^-\s*\d+\s*-\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^Seite\s+\d+\s+von\s+\d+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^\d+\s*/\s*\d+\s*$", "", text, flags=re.MULTILINE)
        text = re.sub(r"^Stand:\s*\d{2}\.\d{2}\.\d{4}\s*$", "", text, flags=re.MULTILINE)

        # Strip excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)

        text = text.strip()
        if text:
            parsed.append(ParsedPage(text=text, page_number=page_num))

    return parsed


def parse_all_pdfs(documents_dir: str | Path) -> dict[str, list[ParsedPage]]:
    """Parse all PDFs in a directory. Returns {filename: [ParsedPage, ...]}."""
    docs_path = Path(documents_dir)
    pdf_files = sorted(docs_path.glob("*.pdf"))
    total = len(pdf_files)
    results = {}

    logger.info("Parsing %d PDFs from %s", total, docs_path)
    run_start = time.monotonic()
    slow_docs: list[tuple[str, float]] = []

    for i, pdf_file in enumerate(pdf_files, start=1):
        t0 = time.monotonic()
        try:
            pages = parse_pdf(pdf_file)
            results[pdf_file.name] = pages
            dt = time.monotonic() - t0
            if dt >= SLOW_PARSE_WARN_SECONDS:
                slow_docs.append((pdf_file.name, dt))
            # Per-doc progress line: index, timing, page count, and a running ETA
            elapsed = time.monotonic() - run_start
            eta = (elapsed / i) * (total - i)
            logger.info(
                "[%d/%d] %s — %d pages in %.1fs%s | elapsed %.0fs, eta ~%.0fs",
                i, total, pdf_file.name, len(pages), dt,
                "  <-- SLOW (likely OCR/scanned)" if dt >= SLOW_PARSE_WARN_SECONDS else "",
                elapsed, eta,
            )
        except Exception:
            logger.warning("[%d/%d] Failed to parse %s, skipping", i, total, pdf_file.name, exc_info=True)

    total_dt = time.monotonic() - run_start
    logger.info("Parsed %d/%d PDFs in %.0fs (%d slow docs)", len(results), total, total_dt, len(slow_docs))
    if slow_docs:
        slow_docs.sort(key=lambda x: x[1], reverse=True)
        logger.info("Slowest docs: %s", ", ".join(f"{n} ({d:.0f}s)" for n, d in slow_docs[:10]))

    return results
