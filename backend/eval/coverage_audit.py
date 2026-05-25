#!/usr/bin/env python3
"""Audit document coverage per program — identifies gaps in the knowledge base."""

import json
from collections import defaultdict
from pathlib import Path


def audit_coverage(manifest_path: str = "../documents/manifest.json") -> dict:
    """Analyze document coverage per program and doc_type."""
    manifest = json.loads(Path(manifest_path).read_text())
    entries = manifest.get("entries", [])

    # Build coverage matrix: program → set of doc_types
    coverage = defaultdict(lambda: defaultdict(list))
    all_programs = set()

    for entry in entries:
        for program in entry.get("programs", []):
            all_programs.add(program)
            coverage[program][entry["doc_type"]].append(entry["filename"])

    # Analyze gaps
    report = {
        "total_programs": len(all_programs),
        "total_documents": len(entries),
        "doc_type_counts": {},
        "programs_missing_psto": [],
        "programs_missing_eignung": [],
        "programs_missing_aenderung": [],
        "programs_with_multiple_psto": [],
        "full_coverage": [],  # programs with psto + eignung
        "coverage_by_program": {},
    }

    for program in sorted(all_programs):
        types = set(coverage[program].keys())
        report["coverage_by_program"][program] = {
            "doc_types": sorted(types),
            "doc_count": sum(len(v) for v in coverage[program].values()),
        }

        if "psto" not in types:
            report["programs_missing_psto"].append(program)
        if "eignung" not in types:
            report["programs_missing_eignung"].append(program)
        if "aenderung" not in types:
            report["programs_missing_aenderung"].append(program)
        if "psto" in types and "eignung" in types:
            report["full_coverage"].append(program)
        if "psto" in types and len(coverage[program]["psto"]) > 1:
            report["programs_with_multiple_psto"].append({
                "program": program,
                "psto_files": coverage[program]["psto"],
            })

    # Summary counts
    for dtype in ["psto", "eignung", "aenderung", "zulassung"]:
        report["doc_type_counts"][dtype] = sum(
            1 for e in entries if e["doc_type"] == dtype
        )

    return report


if __name__ == "__main__":
    report = audit_coverage()

    print(f"=== Coverage Audit ===")
    print(f"Programs: {report['total_programs']}")
    print(f"Documents: {report['total_documents']}")
    print(f"  PSTO: {report['doc_type_counts'].get('psto', 0)}")
    print(f"  Eignung: {report['doc_type_counts'].get('eignung', 0)}")
    print(f"  Änderung: {report['doc_type_counts'].get('aenderung', 0)}")
    print(f"  Zulassung: {report['doc_type_counts'].get('zulassung', 0)}")
    print()
    print(f"Full coverage (PSTO + Eignung): {len(report['full_coverage'])}/{report['total_programs']}")
    print()

    if report["programs_missing_psto"]:
        print(f"MISSING PSTO ({len(report['programs_missing_psto'])}):")
        for p in report["programs_missing_psto"]:
            print(f"  - {p}")
        print()

    if report["programs_missing_eignung"]:
        print(f"MISSING EIGNUNG ({len(report['programs_missing_eignung'])}):")
        for p in report["programs_missing_eignung"]:
            print(f"  - {p}")
        print()

    # Save full report as JSON
    out = Path("coverage_report.json")
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Full report saved to {out}")
