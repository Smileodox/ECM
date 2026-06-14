"""Unit tests for the three-band answerability gate and hand-off prompts."""

from app.search.retriever import _apply_answerability_gate, _boost_title_matches
from app.chat.prompts import build_low_confidence_notice, build_grounding_retraction
from app.chat.escalation import get_pruefungsamt_url


def _doc(section_title="", id_="x"):
    return {"id": id_, "section_title": section_title}


class TestAnswerabilityGate:
    def test_solid_band(self):
        chosen, conf, top = _apply_answerability_gate([(2.0, 2.0, _doc())])
        assert conf == "solid"
        assert top == 2.0
        assert len(chosen) == 1

    def test_uncertain_band(self):
        chosen, conf, top = _apply_answerability_gate([(1.0, 1.0, _doc())])
        assert conf == "uncertain"
        assert chosen  # provisional answer still gets sources

    def test_abstain_band(self):
        chosen, conf, top = _apply_answerability_gate([(0.3, 0.3, _doc())])
        assert conf == "abstain"
        assert chosen == []  # empty -> hard hand-off upstream

    def test_empty_input_abstains(self):
        chosen, conf, top = _apply_answerability_gate([])
        assert conf == "abstain"
        assert top == 0.0

    def test_solid_takes_priority_over_weak(self):
        ranked = [(2.0, 2.0, _doc(id_="a")), (0.4, 0.4, _doc(id_="b"))]
        chosen, conf, _ = _apply_answerability_gate(ranked)
        assert conf == "solid"
        # only the solid one is kept; sub-threshold noise is dropped
        assert len(chosen) == 1


class TestTitleBoostSeparation:
    def test_raw_score_preserved_for_gate(self):
        # raw 1.4 (uncertain), title matches -> rank boosted to 1.7 (>= solid 1.6).
        scored = [(1.4, _doc(section_title="Masterarbeit", id_="a"))]
        ranked = _boost_title_matches("masterarbeit regelung frage", scored)
        rank, raw, _doc_out = ranked[0]
        assert raw == 1.4
        assert round(rank, 2) == 1.7
        # The gate must read the RAW score -> uncertain, not faked into solid.
        _, conf, _ = _apply_answerability_gate(ranked)
        assert conf == "uncertain"

    def test_no_title_match_no_boost(self):
        scored = [(1.0, _doc(section_title="Zulassung", id_="a"))]
        ranked = _boost_title_matches("masterarbeit", scored)
        rank, raw, _ = ranked[0]
        assert rank == raw == 1.0


class TestHandoffPrompts:
    def test_low_conf_notice_de(self):
        n = build_low_confidence_notice(
            query="Welche Note brauche ich?", route="regulation",
            query_type="eligibility", lang="de",
        )
        assert "Unsichere Antwort" in n
        assert "https://" in n
        assert "Prüfungsamt" in n

    def test_low_conf_notice_en(self):
        n = build_low_confidence_notice(
            query="What grade do I need?", route="regulation",
            query_type="eligibility", lang="en",
        )
        assert "Uncertain answer" in n
        assert "https://" in n

    def test_grounding_retraction_de(self):
        r = build_grounding_retraction(route="regulation", lang="de")
        assert "Bitte prüfen" in r
        assert "https://" in r

    def test_grounding_retraction_en(self):
        r = build_grounding_retraction(route="regulation", lang="en")
        assert "Please verify" in r

    def test_pruefungsamt_url_maps_known_program(self):
        # Map populated (2026-06): a mapped program -> its faculty exam office, not the list.
        assert "isc" in get_pruefungsamt_url("Betriebswirtschaftslehre")  # ISC = business exams

    def test_pruefungsamt_url_falls_back_to_generic_when_unmapped(self):
        # Unmapped program (no verified dedicated page) -> generic list page (no invented URLs).
        assert get_pruefungsamt_url("Tiermedizin").endswith("/pruefungsaemter/")
