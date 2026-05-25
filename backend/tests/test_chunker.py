"""Unit tests for the §-aware chunker."""

import pytest
from app.ingestion.chunker import (
    _absatz_label,
    _hard_split,
    _split_on_sentences,
    _split_section_by_absatz,
    _SectionBlock,
    count_tokens,
    MAX_CHUNK_TOKENS,
    TARGET_CHUNK_TOKENS,
)


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_single_word(self):
        assert count_tokens("Hallo") > 0

    def test_longer_text(self):
        short = count_tokens("Hallo")
        long = count_tokens("Hallo Welt, das ist ein langer Satz mit vielen Wörtern.")
        assert long > short


class TestAbsatzLabel:
    def test_none_start(self):
        assert _absatz_label(None, None) is None

    def test_single_absatz(self):
        assert _absatz_label(1, None) == "Abs. 1"
        assert _absatz_label(1, 1) == "Abs. 1"

    def test_range(self):
        assert _absatz_label(1, 3) == "Abs. 1-3"

    def test_start_equals_end(self):
        assert _absatz_label(5, 5) == "Abs. 5"


class TestSplitOnSentences:
    def test_short_text_not_split(self):
        text = "Ein kurzer Satz."
        result = _split_on_sentences(text, max_tokens=500)
        assert result == [text]

    def test_splits_at_sentence_boundary(self):
        # Build a text that's too long for one chunk when split
        long_sentence = "Dies ist ein sehr langer Satz mit vielen Wörtern. " * 20
        result = _split_on_sentences(long_sentence, max_tokens=100)
        assert len(result) > 1
        for chunk in result:
            assert count_tokens(chunk) <= 100

    def test_preserves_content(self):
        text = "Erster Satz. Zweiter Satz. Dritter Satz."
        result = _split_on_sentences(text, max_tokens=500)
        combined = " ".join(result)
        # All words should be present (join may differ from original but content preserved)
        assert "Erster" in combined
        assert "Zweiter" in combined
        assert "Dritter" in combined


class TestHardSplit:
    def test_short_text_returned_as_is(self):
        text = "Kurzer Text."
        assert _hard_split(text, MAX_CHUNK_TOKENS) == [text]

    def test_splits_on_paragraph_boundary(self):
        # Build multi-paragraph text that exceeds max_tokens
        para = "Dies ist ein Absatz mit einigem Text der Platz braucht. " * 5
        text = (para + "\n\n") * 30
        result = _hard_split(text, max_tokens=200)
        assert len(result) > 1
        for chunk in result:
            assert count_tokens(chunk) <= 200 + 20  # small tolerance

    def test_oversized_single_paragraph_split_at_sentence(self):
        # A single paragraph with no double-newlines that exceeds max_tokens
        long_para = "Einzelner Satz ohne Absatzgrenze. " * 50
        result = _hard_split(long_para.strip(), max_tokens=100)
        assert len(result) > 1
        # Each chunk must be within limit (sentence split is best-effort)
        for chunk in result:
            # Allow slight overshoot for very long individual sentences
            assert count_tokens(chunk) <= 150

    def test_empty_result_fallback(self):
        # Even if splitting fails, should return at least one chunk
        result = _hard_split("Text.", max_tokens=1000)
        assert len(result) == 1

    def test_preserves_all_content(self):
        paras = [f"Paragraph {i} mit etwas Inhalt und mehr Wörtern." for i in range(20)]
        text = "\n\n".join(paras)
        result = _hard_split(text, max_tokens=100)
        combined = " ".join(result)
        for i in range(20):
            assert f"Paragraph {i}" in combined


class TestSplitSectionByAbsatz:
    def _make_section(self, body: str) -> _SectionBlock:
        return _SectionBlock(
            section_id="§1",
            section_title="Testparagraph",
            heading="## **§ 1 Testparagraph**",
            body=body,
            page_number=1,
            part="",
        )

    def test_no_absatz_returns_full_body(self):
        section = self._make_section("Einleitungstext ohne Absatzmarkierungen.")
        groups = _split_section_by_absatz(section)
        assert len(groups) == 1
        assert groups[0][1] is None

    def test_single_absatz(self):
        body = "## **§ 1 Test**\n\n(1) Erster Absatz mit Inhalt."
        section = self._make_section(body)
        groups = _split_section_by_absatz(section)
        assert any("Abs. 1" in (g[1] or "") for g in groups)

    def test_multiple_absaetze_grouped(self):
        body = "## **§ 1 Test**\n\n" + "\n\n".join(
            f"({i}) Absatz {i} mit etwas Text." for i in range(1, 6)
        )
        section = self._make_section(body)
        groups = _split_section_by_absatz(section)
        assert len(groups) >= 1
        # Labels should be present
        labels = [g[1] for g in groups if g[1] is not None]
        assert len(labels) > 0

    def test_large_section_produces_multiple_chunks(self):
        # Each absatz is large enough that they can't all fit in one chunk
        big_absatz = "Langer Text im Absatz. " * 40
        body = "## **§ 5 Grosser Paragraph**\n\n" + "\n\n".join(
            f"({i}) {big_absatz}" for i in range(1, 8)
        )
        section = self._make_section(body)
        groups = _split_section_by_absatz(section)
        assert len(groups) > 1
