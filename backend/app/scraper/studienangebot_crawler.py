"""Crawler for the LMU Studiengangsfinder API — fetches master program metadata."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from app.config import settings

log = logging.getLogger(__name__)

SEARCH_URL = "https://cms-search.lmu.de/search/courses_by_name_asc/execute"
MANIFEST_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "studienangebot_manifest.json"


@dataclass
class MasterProgram:
    name: str
    description: str
    degree: str
    ects: str
    duration: str
    language: str
    teaching_language: str
    start_semester: str
    admission_type: str
    admission_details: str
    detail_url: str


def _val(result: dict, key: str) -> str:
    v = result.get(key) or [""]
    return v[0].strip() if isinstance(v, list) else str(v).strip()


async def fetch_master_programs() -> list[MasterProgram]:
    auth = (settings.lmu_search_user, settings.lmu_search_pass) if settings.lmu_search_user else None
    if not auth:
        log.warning("LMU_SEARCH_USER / LMU_SEARCH_PASS not set, trying without auth")

    programs: list[MasterProgram] = []
    page = 1

    async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
        while True:
            resp = await client.get(
                SEARCH_URL,
                params={
                    "query": "*",
                    "facet.filter.Graduation_value": '"Master"',
                    "page": str(page),
                },
                auth=auth,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break

            for r in results:
                link = _val(r, "detailpage_link")
                if isinstance(r.get("detailpage_link"), list):
                    link = r["detailpage_link"][0] if r["detailpage_link"] else ""

                programs.append(MasterProgram(
                    name=_val(r, "Name_value"),
                    description=_val(r, "Description_value"),
                    degree=_val(r, "Degree_of_completion_value"),
                    ects=_val(r, "ECTS_value"),
                    duration=_val(r, "standardPeriodOfStudy_value"),
                    language=_val(r, "Language_value"),
                    teaching_language=_val(r, "teachingLanguage_value"),
                    start_semester=_val(r, "Start_of_studies_value"),
                    admission_type=_val(r, "admissionRestriction1stSemester_value"),
                    admission_details=_val(r, "studyOrientationProcedure_value"),
                    detail_url=link,
                ))
            page += 1

    log.info("Fetched %d master programs from Studiengangsfinder API", len(programs))
    return programs


def save_manifest(programs: list[MasterProgram], path: Path | None = None) -> None:
    p = path or MANIFEST_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"total": len(programs), "entries": [asdict(prog) for prog in programs]}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    log.info("Saved studienangebot manifest to %s (%d programs)", p, len(programs))


def load_manifest(path: Path | None = None) -> list[MasterProgram]:
    p = path or MANIFEST_PATH
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return [MasterProgram(**e) for e in data.get("entries", [])]
