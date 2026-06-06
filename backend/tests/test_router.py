"""Unit tests for the query router (keyword fast-path)."""

import pytest
from app.search.router import (
    QueryRoute,
    _REGULATION_KEYWORDS,
    _GENERAL_KEYWORDS,
    _BOTH_KEYWORDS,
)


# We test the keyword logic directly to avoid needing an LLM in unit tests.
# The async classify_route function falls back to LLM only when no keywords match.


def _keyword_classify(query: str) -> QueryRoute:
    """Reproduce the keyword fast-path from classify_route (sync, no LLM)."""
    has_regulation = bool(_REGULATION_KEYWORDS.search(query))
    has_general = bool(_GENERAL_KEYWORDS.search(query))
    has_both = bool(_BOTH_KEYWORDS.search(query))

    if has_both:
        return QueryRoute.BOTH
    if has_regulation and not has_general:
        return QueryRoute.REGULATION
    if has_general and not has_regulation:
        return QueryRoute.GENERAL
    if has_regulation and has_general:
        return QueryRoute.BOTH
    return None  # would go to LLM


class TestRegulationKeywords:
    def test_ects(self):
        assert _keyword_classify("Wie viele ECTS hat die Masterarbeit?") == QueryRoute.REGULATION

    def test_paragraph_reference(self):
        assert _keyword_classify("Was sagt § 14 der PSTO?") == QueryRoute.REGULATION

    def test_thesis(self):
        assert _keyword_classify("How long is the master thesis?") == QueryRoute.REGULATION

    def test_exam(self):
        assert _keyword_classify("When is the next exam?") == QueryRoute.REGULATION

    def test_psto(self):
        assert _keyword_classify("PSTO Informatik 2023") == QueryRoute.REGULATION

    def test_eignung(self):
        assert _keyword_classify("Eignungssatzung Informatik") == QueryRoute.REGULATION

    def test_notenberechnung(self):
        assert _keyword_classify("Wie funktioniert die Notenberechnung?") == QueryRoute.REGULATION


class TestGeneralKeywords:
    def test_rueckmeldung(self):
        assert _keyword_classify("Wie funktioniert die Rückmeldung?") == QueryRoute.GENERAL

    def test_semesterticket(self):
        assert _keyword_classify("Wo bekomme ich mein Semesterticket?") == QueryRoute.GENERAL

    def test_bibliothek(self):
        assert _keyword_classify("Öffnungszeiten der Bibliothek?") == QueryRoute.GENERAL

    def test_stipendium(self):
        assert _keyword_classify("Kann ich ein Stipendium bekommen?") == QueryRoute.GENERAL

    def test_beurlaubung(self):
        assert _keyword_classify("Wie beantrage ich eine Beurlaubung?") == QueryRoute.GENERAL

    def test_bescheinigung(self):
        assert _keyword_classify("Wo bekomme ich eine Bescheinigung?") == QueryRoute.GENERAL

    def test_wohnung(self):
        assert _keyword_classify("Ich suche eine Wohnung in München") == QueryRoute.GENERAL

    def test_career_service(self):
        assert _keyword_classify("Was bietet der Career Service?") == QueryRoute.GENERAL

    def test_erasmus(self):
        assert _keyword_classify("Kann ich mit Erasmus ins Ausland?") == QueryRoute.GENERAL


class TestBothKeywords:
    def test_fachwechsel(self):
        assert _keyword_classify("Wie funktioniert ein Fachwechsel?") == QueryRoute.BOTH

    def test_bewerbung(self):
        assert _keyword_classify("Wie ist der Bewerbungsprozess?") == QueryRoute.BOTH

    def test_zulassung(self):
        assert _keyword_classify("Zulassungsbeschränkung Informatik") == QueryRoute.BOTH

    def test_anerkennung(self):
        assert _keyword_classify("Wie funktioniert die Anerkennung von Leistungen?") == QueryRoute.BOTH

    def test_studiengangswechsel(self):
        assert _keyword_classify("Ich möchte einen Studiengangswechsel machen") == QueryRoute.BOTH

    def test_studiengang_wechseln_goes_to_llm(self):
        # "Studiengang wechseln" (split words) doesn't match the compound keyword — falls back to LLM
        assert _keyword_classify("Ich möchte den Studiengang wechseln") is None


class TestMixedKeywords:
    def test_regulation_and_general_gives_both(self):
        result = _keyword_classify("Wie ist die Rückmeldung für die Prüfung geregelt?")
        assert result == QueryRoute.BOTH

    def test_both_keyword_overrides_regulation(self):
        assert _keyword_classify("Fachwechsel PSTO") == QueryRoute.BOTH

    def test_no_keywords_returns_none(self):
        result = _keyword_classify("Hallo, wie geht es dir?")
        assert result is None

    def test_english_general(self):
        assert _keyword_classify("How do I get health insurance?") is None  # no German keywords → LLM fallback
