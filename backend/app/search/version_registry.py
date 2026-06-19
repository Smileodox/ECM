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
_DOC_NUM = re.compile(r"^(\d+)")
_IS_EIGNUNG_AMENDMENT = re.compile(r"aend.*eign|aenderung.*eign", re.IGNORECASE)


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


def _extract_doc_num(filename: str) -> int | None:
    m = _DOC_NUM.match(filename)
    return int(m.group(1)) if m else None


@dataclass
class _ProgramDocs:
    psto: list[tuple[str, int | None]] = field(default_factory=list)
    aenderung: list[tuple[str, int | None]] = field(default_factory=list)
    eignung_base: list[tuple[str, int | None]] = field(default_factory=list)


class VersionRegistry:
    def __init__(self, allowed: set[str] | None = None, blocked: set[str] | None = None):
        self._allowed = allowed or set()
        self._blocked = blocked or set()

    def is_allowed(self, doc_filename: str) -> bool:
        if doc_filename in self._blocked:
            return False
        return True

    def get_blocked_filenames(self) -> set[str]:
        return set(self._blocked)

    @staticmethod
    def build_from_manifest(manifest_path: Path) -> "VersionRegistry":
        if not manifest_path.exists():
            logger.error(
                "Manifest not found at %s — version filtering DISABLED; superseded "
                "document versions will be served. Ensure the manifest ships with the deploy.",
                manifest_path,
            )
            return VersionRegistry()
        data = json.loads(manifest_path.read_text())
        entries = data.get("entries", [])

        by_program: dict[str, _ProgramDocs] = defaultdict(_ProgramDocs)

        for entry in entries:
            filename = entry["filename"]
            doc_type = entry.get("doc_type", "")
            programs = entry.get("programs", [])

            # Amendments to an EIGNUNGSSATZUNG are often classified doc_type="aenderung",
            # but they belong to the Eignung lineage — NOT the PSTO. They must NEVER be
            # folded into the PSTO amendment comparison, or they get blocked as "older than
            # the newest PSTO" and wrongly purged (e.g. the BWL one moving a deadline
            # Juni->Mai). Skip them entirely so they always remain allowed.
            if _IS_EIGNUNG_AMENDMENT.search(filename):
                continue
            if doc_type == "psto":
                year = extract_year_from_filename(filename)
                for prog in programs:
                    by_program[prog].psto.append((filename, year))
            elif doc_type == "aenderung":
                year = extract_year_from_filename(filename)
                for prog in programs:
                    by_program[prog].aenderung.append((filename, year))
            elif doc_type == "eignung":
                doc_num = _extract_doc_num(filename)
                for prog in programs:
                    by_program[prog].eignung_base.append((filename, doc_num))

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

        for prog, docs in by_program.items():
            if len(docs.eignung_base) > 1:
                nums = [n for _, n in docs.eignung_base if n is not None]
                newest_num = max(nums) if nums else None
                for filename, num in docs.eignung_base:
                    if newest_num is not None and num is not None and num < newest_num:
                        blocked.add(filename)
                        logger.info("Blocking superseded Eignungssatzung %s (program %s)", filename, prog)
                    else:
                        allowed.add(filename)
            else:
                for filename, _ in docs.eignung_base:
                    allowed.add(filename)

        all_filenames = {e["filename"] for e in entries}
        remaining = all_filenames - allowed - blocked
        allowed |= remaining

        logger.info(
            "Version registry: %d programs, %d allowed, %d blocked",
            len(by_program), len(allowed), len(blocked),
        )
        return VersionRegistry(allowed, blocked)


_registry: VersionRegistry | None = None


def get_registry() -> VersionRegistry:
    global _registry
    if _registry is None:
        from app.paths import manifest_path
        _registry = VersionRegistry.build_from_manifest(manifest_path())
    return _registry


def invalidate_registry() -> None:
    global _registry
    _registry = None
