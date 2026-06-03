"""Generate per-document summaries for overview questions."""

import logging
import time

import tiktoken as _tiktoken
from openai import AzureOpenAI, RateLimitError

from app.config import settings
from app.ingestion.chunker import Chunk, count_tokens
from app.ingestion.parser import ParsedPage

logger = logging.getLogger(__name__)

MAX_INPUT_TOKENS = 2000

_SUMMARY_SYSTEM = """Du bist ein Experte für deutsche Hochschulrechtsdokumente. Erstelle eine strukturierte Zusammenfassung des folgenden Dokuments. Die Zusammenfassung soll folgendes Format haben:

Dokumenttyp: [PSTO / Eignungssatzung / Zulassungsordnung / Änderungssatzung]
Studiengang: [Name und Abschluss, z.B. "Informatik (Master of Science)"]
Regelstudienzeit: [Falls angegeben]
ECTS gesamt: [Falls angegeben]
Wesentliche Inhalte: [3-5 Stichpunkte zu den wichtigsten Regelungen]
Besonderheiten: [Falls vorhanden, z.B. Änderungen gegenüber Vorgängerversion]

Schreibe nur die Zusammenfassung, nichts sonst. Maximal 150 Wörter."""


def _get_openai_client() -> AzureOpenAI:
    return AzureOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        api_version=settings.azure_openai_api_version,
        max_retries=0,
    )


def generate_summary(pages: list[ParsedPage]) -> str | None:
    first_pages_text = "\n\n".join(p.text for p in pages[:3])
    tokens = count_tokens(first_pages_text)
    if tokens > MAX_INPUT_TOKENS:
        enc = _tiktoken.get_encoding("cl100k_base")
        first_pages_text = enc.decode(enc.encode(first_pages_text)[:MAX_INPUT_TOKENS])

    client = _get_openai_client()
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=settings.azure_openai_mini_deployment,
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM},
                    {"role": "user", "content": first_pages_text},
                ],
                temperature=0.1,
                max_completion_tokens=300,
            )
            return response.choices[0].message.content.strip()
        except RateLimitError as e:
            retry_after = 60
            if hasattr(e, "response") and e.response is not None:
                retry_after = int(e.response.headers.get("retry-after", 60))
            logger.warning("Rate limited generating summary (attempt %d/3), waiting %ds...", attempt + 1, retry_after)
            time.sleep(retry_after)
        except Exception:
            logger.warning("Failed to generate summary", exc_info=True)
            return None
    return None


def generate_summary_chunk(
    pages: list[ParsedPage],
    doc_filename: str,
    doc_name: str,
    source_url: str = "",
    doc_type: str = "",
    program_name: str = "",
    chunk_index: int = 0,
) -> Chunk | None:
    summary = generate_summary(pages)
    if not summary:
        return None

    return Chunk(
        content=summary,
        doc_name=doc_name,
        doc_filename=doc_filename,
        section_id="summary",
        section_title="Dokumentübersicht",
        absatz=None,
        page_number=1,
        part="",
        sub_part="",
        source_url=source_url,
        chunk_index=chunk_index,
        doc_type=doc_type,
        program_name=program_name,
    )
