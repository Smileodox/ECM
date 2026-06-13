"""Unit tests for the deterministic grounding verifier."""

from tests.conftest import make_citation
from app.chat.grounding import verify_grounding


class TestVerifyGrounding:
    def test_no_sections_is_grounded(self):
        c = make_citation(section_id="§14", content="Die Masterarbeit umfasst 30 ECTS.")
        v = verify_grounding("Die Masterarbeit umfasst 30 ECTS.", [c], {1})
        assert v["verdict"] == "grounded"
        assert v["checked"] == []

    def test_supported_via_section_id(self):
        c = make_citation(index=1, section_id="§14", content="§ 14 regelt die Masterarbeit.")
        v = verify_grounding("Laut § 14 sind es 30 ECTS [Quelle 1].", [c], {1})
        assert v["verdict"] == "grounded"
        assert "§14" in v["checked"]
        assert v["unsupported"] == []

    def test_supported_via_content_crossref(self):
        # Answer cites §9, which appears only in the chunk content (a cross-reference).
        c = make_citation(index=1, section_id="§14", content="Siehe auch § 9 für Details.")
        v = verify_grounding("Gemäß § 9 gilt das [Quelle 1].", [c], {1})
        assert v["verdict"] == "grounded"

    def test_invented_section_ungrounded(self):
        c = make_citation(index=1, section_id="§14", content="§ 14 regelt die Masterarbeit.")
        v = verify_grounding("Laut § 99 ist das verboten [Quelle 1].", [c], {1})
        assert v["verdict"] == "ungrounded"
        assert "§99" in v["unsupported"]

    def test_partially_grounded(self):
        c = make_citation(index=1, section_id="§14", content="§ 14 Masterarbeit.")
        v = verify_grounding("§ 14 und § 77 [Quelle 1].", [c], {1})
        assert v["verdict"] == "partially_grounded"
        assert "§77" in v["unsupported"]
        assert "§14" in v["checked"]

    def test_falls_back_to_all_citations_without_markers(self):
        c = make_citation(index=1, section_id="§14", content="§ 14 Masterarbeit.")
        # No [Quelle N] markers in the answer -> verify against all retrieved citations.
        v = verify_grounding("Laut § 14 gilt das.", [c], set())
        assert v["verdict"] == "grounded"

    def test_only_checks_cited_sources(self):
        cited = make_citation(index=1, section_id="§14", content="§ 14 Masterarbeit.")
        other = make_citation(index=2, section_id="§99", content="§ 99 Sonderfall.")
        # Answer references §99 but only cites Quelle 1 -> §99 is unsupported.
        v = verify_grounding("Laut § 99 gilt das [Quelle 1].", [cited, other], {1})
        assert v["verdict"] == "ungrounded"
        assert "§99" in v["unsupported"]
