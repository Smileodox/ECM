"""Filesystem path resolution that tolerates the dev-vs-deployed layout gap.

The regulation `manifest.json` drives BOTH the version filter (which superseded
PSTO versions to hide) AND program-name detection. In local dev it lives in
`documents/` next to the PDFs; on the deployed backend the `documents/` tree is
NOT shipped, so we fall back to a copy bundled under `backend/data/manifest.json`
(which ships with the app). If neither is present, callers log a loud miss —
silence here previously caused outdated regulations to be served.
"""
from pathlib import Path

from app.config import settings

# backend/ root = parent of the app/ package (this file is backend/app/paths.py)
BACKEND_ROOT = Path(__file__).resolve().parent.parent


def manifest_path() -> Path:
    """Resolve the regulation manifest across dev/deploy layouts.

    Order: the configured documents dir (dev: ../documents — also the ingestion
    source of truth), then the copy bundled with the backend package. Returns the
    first existing candidate, else the bundled path so misses log a stable location.
    """
    candidates = [
        Path(settings.documents_dir) / "manifest.json",
        BACKEND_ROOT / "data" / "manifest.json",
    ]
    for p in candidates:
        if p.exists():
            return p
    return candidates[-1]
