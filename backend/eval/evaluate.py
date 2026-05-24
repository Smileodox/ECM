"""Evaluation pipeline for campusLMU chatbot.

Measures retrieval quality (Recall@K, MRR, Precision@K) and latency
against a ground-truth test suite. Run with: python -m eval.evaluate
"""

import asyncio
import json
import time
from pathlib import Path

from app.config import settings
from app.models import ChatMessage
from app.search.retriever import RetrievalResult, retrieve

TEST_CASES_PATH = Path(__file__).parent / "test_cases.json"
RESULTS_PATH = Path(__file__).parent / "results.json"


def load_test_cases() -> list[dict]:
    data = json.loads(TEST_CASES_PATH.read_text())
    return data["cases"]


def recall_at_k(retrieved_section_ids: list[str], expected_section_ids: list[str], k: int = 10) -> float:
    if not expected_section_ids:
        return 1.0
    retrieved_set = set(retrieved_section_ids[:k])
    expected_set = set(expected_section_ids)
    return len(retrieved_set & expected_set) / len(expected_set)


def precision_at_k(retrieved_section_ids: list[str], expected_section_ids: list[str], k: int = 5) -> float:
    if not expected_section_ids:
        return 1.0
    retrieved_top = retrieved_section_ids[:k]
    if not retrieved_top:
        return 0.0
    expected_set = set(expected_section_ids)
    hits = sum(1 for sid in retrieved_top if sid in expected_set)
    return hits / len(retrieved_top)


def mrr(retrieved_section_ids: list[str], expected_section_ids: list[str]) -> float:
    if not expected_section_ids:
        return 1.0
    expected_set = set(expected_section_ids)
    for i, sid in enumerate(retrieved_section_ids):
        if sid in expected_set:
            return 1.0 / (i + 1)
    return 0.0


def keyword_hit_rate(response_text: str, expected_keywords: list[str]) -> float:
    if not expected_keywords:
        return 1.0
    text_lower = response_text.lower()
    hits = sum(1 for kw in expected_keywords if kw.lower() in text_lower)
    return hits / len(expected_keywords)


async def evaluate_retrieval(case: dict) -> dict:
    query = case["query"]
    expected_sections = case.get("expected_section_ids", [])
    expected_doc_types = case.get("expected_doc_types", [])

    t0 = time.perf_counter()
    result: RetrievalResult = await retrieve(query)
    elapsed_ms = (time.perf_counter() - t0) * 1000

    retrieved_sections = [c.section_id for c in result.citations]
    retrieved_doc_types = [c.doc_type for c in result.citations]
    retrieved_content = " ".join(c.content for c in result.citations)

    return {
        "case_id": case["id"],
        "category": case["category"],
        "query": query,
        "num_citations": len(result.citations),
        "low_confidence": result.low_confidence,
        "retrieved_sections": retrieved_sections,
        "recall_at_10": recall_at_k(retrieved_sections, expected_sections, k=10),
        "precision_at_5": precision_at_k(retrieved_sections, expected_sections, k=5),
        "mrr": mrr(retrieved_sections, expected_sections),
        "doc_type_hit": bool(set(retrieved_doc_types) & set(expected_doc_types)) if expected_doc_types else True,
        "keyword_hit_rate": keyword_hit_rate(retrieved_content, case.get("expected_keywords", [])),
        "retrieve_ms": round(elapsed_ms, 1),
    }


async def run_eval() -> dict:
    cases = load_test_cases()
    print(f"\nRunning evaluation on {len(cases)} test cases...\n")

    results = []
    for case in cases:
        try:
            result = await evaluate_retrieval(case)
            status = "PASS" if result["recall_at_10"] > 0 or not case.get("expected_section_ids") else "MISS"
            print(f"  [{status}] {case['id']:12s} | R@10={result['recall_at_10']:.2f} | MRR={result['mrr']:.2f} | P@5={result['precision_at_5']:.2f} | {result['retrieve_ms']:6.0f}ms | {case['query'][:50]}")
            results.append(result)
        except Exception as e:
            print(f"  [ERR]  {case['id']:12s} | {e}")
            results.append({
                "case_id": case["id"],
                "category": case["category"],
                "query": case["query"],
                "error": str(e),
            })

    successful = [r for r in results if "error" not in r]
    summary = {
        "total_cases": len(cases),
        "successful": len(successful),
        "errors": len(cases) - len(successful),
        "avg_recall_at_10": _avg(successful, "recall_at_10"),
        "avg_precision_at_5": _avg(successful, "precision_at_5"),
        "avg_mrr": _avg(successful, "mrr"),
        "avg_retrieve_ms": _avg(successful, "retrieve_ms"),
        "p95_retrieve_ms": _percentile(successful, "retrieve_ms", 0.95),
        "doc_type_accuracy": _avg_bool(successful, "doc_type_hit"),
        "avg_keyword_hit_rate": _avg(successful, "keyword_hit_rate"),
    }

    by_category = {}
    for r in successful:
        cat = r["category"]
        if cat not in by_category:
            by_category[cat] = []
        by_category[cat].append(r)

    category_summary = {}
    for cat, cat_results in by_category.items():
        category_summary[cat] = {
            "count": len(cat_results),
            "avg_recall_at_10": _avg(cat_results, "recall_at_10"),
            "avg_mrr": _avg(cat_results, "mrr"),
            "avg_retrieve_ms": _avg(cat_results, "retrieve_ms"),
        }

    report = {
        "summary": summary,
        "by_category": category_summary,
        "results": results,
    }

    RESULTS_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(f"  Cases:          {summary['total_cases']} ({summary['errors']} errors)")
    print(f"  Recall@10:      {summary['avg_recall_at_10']:.2%}")
    print(f"  Precision@5:    {summary['avg_precision_at_5']:.2%}")
    print(f"  MRR:            {summary['avg_mrr']:.2%}")
    print(f"  Keyword Hit:    {summary['avg_keyword_hit_rate']:.2%}")
    print(f"  DocType Acc:    {summary['doc_type_accuracy']:.2%}")
    print(f"  Avg Latency:    {summary['avg_retrieve_ms']:.0f}ms")
    print(f"  P95 Latency:    {summary['p95_retrieve_ms']:.0f}ms")
    print(f"{'='*60}")
    print(f"\n  Full results: {RESULTS_PATH}\n")

    return report


def _avg(items: list[dict], key: str) -> float:
    vals = [r[key] for r in items if key in r]
    return sum(vals) / len(vals) if vals else 0.0


def _avg_bool(items: list[dict], key: str) -> float:
    vals = [1.0 if r.get(key) else 0.0 for r in items]
    return sum(vals) / len(vals) if vals else 0.0


def _percentile(items: list[dict], key: str, p: float) -> float:
    vals = sorted(r[key] for r in items if key in r)
    if not vals:
        return 0.0
    idx = int(len(vals) * p)
    return vals[min(idx, len(vals) - 1)]


def main():
    asyncio.run(run_eval())


if __name__ == "__main__":
    main()
