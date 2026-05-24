from app.chat.citations import extract_used_citation_indices, normalize_citation_markers


class TestExtractUsedCitationIndices:
    def test_simple(self):
        assert extract_used_citation_indices("Gemäß § 14 [Quelle 1].") == {1}

    def test_multiple(self):
        assert extract_used_citation_indices("[Quelle 1] und [Quelle 3]") == {1, 3}

    def test_combined_block(self):
        assert extract_used_citation_indices("[Quelle 1, Quelle 2]") == {1, 2}

    def test_english(self):
        assert extract_used_citation_indices("[source 1]") == {1}

    def test_no_citations(self):
        assert extract_used_citation_indices("Keine Quellen hier.") == set()

    def test_not_a_citation(self):
        assert extract_used_citation_indices("[Wikipedia]") == set()

    def test_complex_block(self):
        text = "[Quelle 1, § 14 Abs. 7; Quelle 2, § 31]"
        assert extract_used_citation_indices(text) == {1, 2}


class TestNormalizeCitationMarkers:
    def test_simple(self):
        assert normalize_citation_markers("Text [Quelle 1].") == "Text <<cite:1>>."

    def test_multiple(self):
        result = normalize_citation_markers("[Quelle 1] und [Quelle 2]")
        assert result == "<<cite:1>> und <<cite:2>>"

    def test_combined_block(self):
        result = normalize_citation_markers("[Quelle 1, Quelle 2]")
        assert result == "<<cite:1>><<cite:2>>"

    def test_no_change_for_non_citations(self):
        text = "Normal text without citations."
        assert normalize_citation_markers(text) == text

    def test_preserves_surrounding_text(self):
        result = normalize_citation_markers("Gemäß § 14 [Quelle 3] ist das so.")
        assert result == "Gemäß § 14 <<cite:3>> ist das so."
