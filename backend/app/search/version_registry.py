"""Document version registry — determines which documents are current vs. superseded."""

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

_YEAR_4DIGIT = re.compile(r"-(\d{4})-[a-z]+\d{2}\.pdf$")
_YEAR_2DIGIT = re.compile(r"-(\d{2})-[a-z]+\d{2}\.pdf$")
_YEAR_EMBEDDED = re.compile(r"[a-z](\d{4})-[a-z]+\d{2}\.pdf$")


def extract_year_from_filename(filename: str) -> int | None:
    m = _YEAR_4DIGIT.search(filename)
    if m:
        return int(m.group(1))
    m = _YEAR_EMBEDDED.search(filename)
    if m:
        return int(m.group(1))
    m = _YEAR_2DIGIT.search(filename)
    if m:
        y = int(m.group(1))
        return 2000 + y if y < 50 else 1900 + y
    return None


@dataclass
class _ProgramDocs:
    psto: list[tuple[str, int | None]] = field(default_factory=list)
    aenderung: list[tuple[str, int | None]] = field(default_factory=list)


class VersionRegistry:
    def __init__(self, allowed: set[str], blocked: set[str]):
        self._allowed = allowed
        self._blocked = blocked

    def is_allowed(self, doc_filename: str) -> bool:
        if doc_filename in self._blocked:
            return False
        return True

    def get_blocked_filenames(self) -> set[str]:
        return set(self._blocked)

    @staticmethod
    def build_from_manifest(manifest_path: Path) -> "VersionRegistry":
        data = json.loads(manifest_path.read_text())
        entries = data.get("entries", [])

        by_program: dict[str, _ProgramDocs] = defaultdict(_ProgramDocs)

        for entry in entries:
            filename = entry["filename"]
            doc_type = entry.get("doc_type", "")
            programs = entry.get("programs", [])

            if doc_type not in ("psto", "aenderung"):
                continue

            year = extract_year_from_filename(filename)
            for prog in programs:
                if doc_type == "psto":
                    by_program[prog].psto.append((filename, year))
                else:
                    by_program[prog].aenderung.append((filename, year))

        allowed: set[str] = set()
        blocked: set[str] = set()

        for prog, docs in by_program.items():
            psto_years = [y for _, y in docs.psto if y is not None]
            newest_year = max(psto_years) if psto_years else None

            for filename, year in docs.psto:
                if newest_year is None:
                    allowed.add(filename)
                elif year == newest_year:
                    allowed.add(filename)
                elif year is None:
                    logger.warning("Could not extract year from %s — allowing but manual review recommended", filename)
                    allowed.add(filename)
                else:
                    blocked.add(filename)

            for filename, year in docs.aenderung:
                if newest_year is None:
                    allowed.add(filename)
                elif year is not None and year >= newest_year:
                    allowed.add(filename)
                else:
                    blocked.add(filename)

        # Eignung + Zulassung are always allowed (not added to blocked)
        all_filenames = {e["filename"] for e in entries}
        eignung_zulassung = all_filenames - allowed - blocked
        allowed |= eignung_zulassung

        logger.info(
            "Version registry: %d programs, %d allowed, %d blocked",
            len(by_program), len(allowed), len(blocked),
        )
        return VersionRegistry(allowed, blocked)


_registry: VersionRegistry | None = None


def get_registry() -> VersionRegistry:
    global _registry
    if _registry is None:
        manifest_path = Path(settings.documents_dir) / "manifest.json"
        _registry = VersionRegistry.build_from_manifest(manifest_path)
    return _registry


def invalidate_registry() -> None:
    global _registry
    _registry = None
