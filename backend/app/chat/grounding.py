"""Deterministic grounding / faithfulness check for generated answers.

The single most dangerous failure mode for a regulation chatbot is a confident
answer citing a paragraph (§) that appears in NO retrieved source — an invented
legal reference. This module checks, with zero LLM cost, that every § reference in
the answer is backed by the chunks the answer actually cited.

Scope (P2, deterministic): § references only — robust and paraphrase-proof. Numeric
facts (ECTS, amounts, durations) are paraphrase-prone ("six months" vs "6 Monate")
and are intentionally NOT string-checked here to avoid false positives; a nano-based
paraphrase pass can be layered on later for those.
"""

import re

from app.models import Citation

# Matches "§ 14", "§14", "§ 14a" — captures the bare number (+ optional letter).
_SECTION_RE = re.compile(r"§\s*(\d+[a-z]?)")


def _section_numbers(text: str) -> set[str]:
    return {m.group(1).lower() for m in _SECTION_RE.finditer(text or "")}


def verify_grounding(
    answer: str,
    citations: list[Citation],
    used_indices: set[int],
) -> dict:
    """Check that § references in the answer are supported by the cited sources.

    A § is "supported" if any cited chunk has it as its section_id OR mentions it in
    its content / amendment context (cross-references count). Returns:
        {"verdict": "grounded" | "partially_grounded" | "ungrounded",
         "unsupported": ["§9", ...], "checked": ["§14", ...]}
    """
    answer_sections = _section_numbers(answer)
    if not answer_sections:
        # Nothing legally load-bearing to verify deterministically (e.g. web answers).
        return {"verdict": "grounded", "unsupported": [], "checked": []}

    # Sources the answer actually cited; fall back to all retrieved if the model
    # produced § refs without explicit [Quelle N] markers.
    cited = [c for c in citations if c.index in used_indices] or citations

    supported: set[str] = set()
    for c in cited:
        supported |= _section_numbers(c.section_id)
        supported |= _section_numbers(c.content)
        supported |= _section_numbers(getattr(c, "amendment_context", "") or "")

    unsupported = sorted(answer_sections - supported, key=lambda s: (len(s), s))
    checked = sorted(answer_sections, key=lambda s: (len(s), s))

    if not unsupported:
        verdict = "grounded"
    elif len(unsupported) < len(answer_sections):
        verdict = "partially_grounded"
    else:
        verdict = "ungrounded"

    return {
        "verdict": verdict,
        "unsupported": [f"§{s}" for s in unsupported],
        "checked": [f"§{s}" for s in checked],
    }
