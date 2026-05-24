from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, urlunparse


@dataclass
class PdfEntry:
    source_url: str
    filename: str
    doc_type: str = "other"
    programs: list[str] = field(default_factory=list)
    link_text: str = ""
    downloaded: bool = False
    file_size_bytes: int = 0


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse(parsed._replace(query="", fragment="")).rstrip("/")


def deduplicate(entries: list[PdfEntry]) -> list[PdfEntry]:
    by_url: dict[str, PdfEntry] = {}
    for entry in entries:
        key = _normalize_url(entry.source_url)
        if key in by_url:
            existing = by_url[key]
            for prog in entry.programs:
                if prog not in existing.programs:
                    existing.programs.append(prog)
            if not existing.link_text and entry.link_text:
                existing.link_text = entry.link_text
            if existing.doc_type == "other" and entry.doc_type != "other":
                existing.doc_type = entry.doc_type
        else:
            by_url[key] = entry
    return list(by_url.values())


def load_manifest(path: Path) -> list[PdfEntry]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [PdfEntry(**e) for e in data.get("entries", [])]


def save_manifest(entries: list[PdfEntry], path: Path) -> None:
    data = {
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "total_pdfs": len(entries),
        "entries": [asdict(e) for e in entries],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
