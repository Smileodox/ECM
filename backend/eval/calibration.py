"""Threshold calibration for the three-band answerability gate.

Runs retrieval over labeled answerable (test_cases.json) + unanswerable
(unanswerable_cases.json) queries, records the raw top reranker score per case,
then sweeps (uncertain, solid) thresholds to find an operating point that maximizes
ABSTAIN-RECALL on unanswerable queries (the legal metric — hold back when we can't
answer) while keeping FALSE-ABSTENTION on answerable queries acceptably low.

Run (needs live Azure creds in .env):

    cd backend && python -m eval.calibration

Then set the chosen values in .env (RERANKER_UNCERTAIN_SCORE / RERANKER_SOLID_SCORE)
and commit eval/calibration_report.json — it's the audit artifact justifying where
the abstention boundary sits.
"""

import asyncio
import json
from pathlib import Path

from app.chat.escalation import resolve_escalation_contacts
from app.search.retriever import retrieve

EVAL_DIR = Path(__file__).parent
TEST_CASES = EVAL_DIR / "test_cases.json"
UNANSWERABLE = EVAL_DIR / "unanswerable_cases.json"
REPORT = EVAL_DIR / "calibration_report.json"

# Threshold candidates to sweep (raw Azure reranker scale is 0..4)
UNCERTAIN_GRID = [0.4, 0.6, 0.8, 1.0, 1.2]
SOLID_GRID = [1.2, 1.4, 1.6, 1.8, 2.0]


def _load_cases() -> list[dict]:
    cases = []
    for c in json.loads(TEST_CASES.read_text())["cases"]:
        c.setdefault("answerable", True)
        cases.append(c)
    if UNANSWERABLE.exists():
        for c in json.loads(UNANSWERABLE.read_text())["cases"]:
            c.setdefault("answerable", False)
            cases.append(c)
    return cases


async def _score_case(case: dict) -> dict:
    result = await retrieve(case["query"], program_name=case.get("program_name"))
    actual_contact = resolve_escalation_contacts(
        case["query"],
        case.get("route", "regulation"),
        case.get("category", "factual"),
        case.get("program_name"),
    )[0]["name_de"]
    return {
        "id": case["id"],
        "answerable": case.get("answerable", True),
        "top_score": round(result.top_score, 3),
        "confidence": result.confidence,
        "num_citations": len(result.citations),
        "expected_contact": case.get("expected_contact"),
        "actual_contact": actual_contact,
    }


def _sweep(scored: list[dict], uncertain: float, solid: float) -> dict:
    ans = [s for s in scored if s["answerable"]]
    una = [s for s in scored if not s["answerable"]]
    # abstain decision = raw top score below the uncertain floor
    abstain_recall = (
        sum(1 for s in una if s["top_score"] < uncertain) / len(una) if una else None
    )
    false_abstain = (
        sum(1 for s in ans if s["top_score"] < uncertain) / len(ans) if ans else 0.0
    )
    solid_rate = (
        sum(1 for s in ans if s["top_score"] >= solid) / len(ans) if ans else 0.0
    )
    return {
        "uncertain": uncertain,
        "solid": solid,
        "abstain_recall_unanswerable": round(abstain_recall, 3) if abstain_recall is not None else None,
        "false_abstain_answerable": round(false_abstain, 3),
        "solid_rate_answerable": round(solid_rate, 3),
    }


async def run() -> dict:
    cases = _load_cases()
    print(f"\nScoring {len(cases)} cases (answerable + unanswerable)...\n")
    scored: list[dict] = []
    for c in cases:
        try:
            s = await _score_case(c)
            tag = "ANS" if s["answerable"] else "UNA"
            print(f"  [{tag}] {s['id']:10s} top={s['top_score']:.2f} conf={s['confidence']:9s} cites={s['num_citations']}")
            scored.append(s)
        except Exception as e:  # pragma: no cover - needs live creds
            print(f"  [ERR] {c['id']}: {e}")

    labeled = [s for s in scored if s.get("expected_contact")]
    contact_acc = (
        sum(1 for s in labeled if s["actual_contact"] == s["expected_contact"]) / len(labeled)
        if labeled else None
    )

    grid = [
        _sweep(scored, unc, sol)
        for unc in UNCERTAIN_GRID
        for sol in SOLID_GRID
        if sol > unc
    ]

    report = {"scored": scored, "contact_accuracy": contact_acc, "sweep": grid}
    REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print("\nThreshold sweep — pick high abstain_recall (unanswerable) at low false_abstain (answerable):")
    ranked = sorted(
        grid,
        key=lambda g: (-(g["abstain_recall_unanswerable"] or 0), g["false_abstain_answerable"]),
    )
    for g in ranked[:12]:
        print(
            f"  unc={g['uncertain']} sol={g['solid']} | "
            f"abstain_recall={g['abstain_recall_unanswerable']} | "
            f"false_abstain={g['false_abstain_answerable']} | "
            f"solid_rate={g['solid_rate_answerable']}"
        )
    if contact_acc is not None:
        print(f"\nRight-place (contact) accuracy on labeled cases: {contact_acc:.0%}")
    print(f"\nFull report: {REPORT}\n")
    return report


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
