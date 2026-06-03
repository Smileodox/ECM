import pytest
from unittest.mock import patch

from tests.conftest import make_citation
from app.search.retriever import (
    _filter_superseded,
    _prefer_amendment_sections,
    _enforce_diversity,
    _reciprocal_rank_fusion,
    _build_filter,
    MAX_CHUNKS_PER_DOC,
)


class TestFilterSuperseded:
    def test_removes_blocked(self):
        c1 = make_citation(doc_filename="allowed.pdf")
        c2 = make_citation(doc_filename="blocked.pdf")

        class FakeRegistry:
            def is_allowed(self, fn):
                return fn != "blocked.pdf"

        with patch("app.search.version_registry.get_registry", return_value=FakeRegistry()):
            result = _filter_superseded([c1, c2])
        assert len(result) == 1
        assert result[0].doc_filename == "allowed.pdf"

    def test_keeps_all_if_none_blocked(self):
        c1 = make_citation(doc_filename="a.pdf")
        c2 = make_citation(doc_filename="b.pdf")

        class FakeRegistry:
            def is_allowed(self, fn):
                return True

        with patch("app.search.version_registry.get_registry", return_value=FakeRegistry()):
            result = _filter_superseded([c1, c2])
        assert len(result) == 2


class TestPreferAmendmentSections:
    def test_prefers_aenderung_over_psto(self):
        psto = make_citation(section_id="§14", doc_type="psto", program_name="Informatik")
        aenderung = make_citation(section_id="§14", doc_type="aenderung", program_name="Informatik")
        result = _prefer_amendment_sections([psto, aenderung])
        assert len(result) == 1
        assert result[0].doc_type == "aenderung"

    def test_keeps_both_if_different_sections(self):
        psto = make_citation(section_id="§14", doc_type="psto", program_name="Informatik")
        aenderung = make_citation(section_id="§5", doc_type="aenderung", program_name="Informatik")
        result = _prefer_amendment_sections([psto, aenderung])
        assert len(result) == 2

    def test_keeps_both_if_different_programs(self):
        psto = make_citation(section_id="§14", doc_type="psto", program_name="Informatik")
        aenderung = make_citation(section_id="§14", doc_type="aenderung", program_name="BWL")
        result = _prefer_amendment_sections([psto, aenderung])
        assert len(result) == 2

    def test_no_aenderung_keeps_all(self):
        c1 = make_citation(section_id="§14", doc_type="psto")
        c2 = make_citation(section_id="§14", doc_type="psto", doc_filename="other.pdf")
        result = _prefer_amendment_sections([c1, c2])
        assert len(result) == 2

    def test_eignung_superseded_by_amendment(self):
        eignung = make_citation(section_id="§3", doc_type="eignung")
        aenderung = make_citation(section_id="§3", doc_type="aenderung")
        result = _prefer_amendment_sections([eignung, aenderung])
        assert len(result) == 1
        assert result[0].doc_type == "aenderung"

    def test_zulassung_superseded_by_amendment(self):
        zulassung = make_citation(section_id="§5", doc_type="zulassung")
        aenderung = make_citation(section_id="§5", doc_type="aenderung")
        result = _prefer_amendment_sections([zulassung, aenderung])
        assert len(result) == 1
        assert result[0].doc_type == "aenderung"


class TestEnforceDiversity:
    def test_limits_per_document(self):
        citations = [
            make_citation(doc_filename="doc1.pdf", reranker_score=3.0 - i * 0.1)
            for i in range(5)
        ]
        result = _enforce_diversity(citations)
        assert len(result) == MAX_CHUNKS_PER_DOC

    def test_keeps_highest_scored(self):
        citations = [
            make_citation(doc_filename="doc1.pdf", reranker_score=float(i))
            for i in range(5)
        ]
        result = _enforce_diversity(citations)
        scores = [c.reranker_score for c in result]
        assert scores == sorted(scores, reverse=True)

    def test_different_docs_not_limited(self):
        citations = [
            make_citation(doc_filename=f"doc{i}.pdf", reranker_score=2.0)
            for i in range(5)
        ]
        result = _enforce_diversity(citations)
        assert len(result) == 5


class TestReciprocalRankFusion:
    def test_merges_two_lists(self):
        list1 = [(3.0, {"id": "a"}), (2.0, {"id": "b"})]
        list2 = [(3.0, {"id": "b"}), (2.0, {"id": "c"})]
        result = _reciprocal_rank_fusion([list1, list2])
        ids = [doc["id"] for _, doc in result]
        assert "b" in ids
        assert "a" in ids
        assert "c" in ids
        assert ids[0] == "b"  # b appears in both lists → highest RRF score

    def test_empty_lists(self):
        result = _reciprocal_rank_fusion([[], []])
        assert result == []

    def test_single_list(self):
        result = _reciprocal_rank_fusion([[(2.0, {"id": "a"})]])
        assert len(result) == 1


class TestBuildFilter:
    def test_no_filters(self):
        assert _build_filter(None, None) is None

    def test_doc_type_only(self):
        assert _build_filter("psto", None) == "doc_type eq 'psto'"

    def test_program_only(self):
        assert _build_filter(None, "Informatik") == "program_name eq 'Informatik'"

    def test_both(self):
        result = _build_filter("psto", "Informatik")
        assert "doc_type eq 'psto'" in result
        assert "program_name eq 'Informatik'" in result
        assert " and " in result

    def test_escapes_quotes(self):
        result = _build_filter("ps'to", None)
        assert "ps''to" in result
