"""Unit tests for the web content chunker."""

from app.ingestion.web_chunker import (
    _clean_title,
    _split_by_heading,
    chunk_web_page,
    H2_PATTERN,
    H3_PATTERN,
)
from app.ingestion.chunker import MAX_CHUNK_TOKENS, count_tokens


class TestCleanTitle:
    def test_plain_text(self):
        assert _clean_title("Rückmeldung") == "Rückmeldung"

    def test_strip_accordion_anchor(self):
        assert _clean_title("[Fristen](#accordionItem-123)") == "Fristen"

    def test_strip_markdown_link(self):
        assert _clean_title("[See more](https://lmu.de/info)") == "See more"

    def test_mixed_content(self):
        result = _clean_title("[Schritt 1](#accordionItem-1): Antrag stellen")
        assert "Schritt 1" in result
        assert "accordionItem" not in result

    def test_empty(self):
        assert _clean_title("") == ""


class TestSplitByHeading:
    def test_no_headings(self):
        text = "Just some plain text."
        result = _split_by_heading(text, H2_PATTERN)
        assert len(result) == 1
        assert result[0][0] == ""
        assert result[0][1] == text

    def test_single_h2(self):
        text = "## Rückmeldung\n\nText about re-registration."
        result = _split_by_heading(text, H2_PATTERN)
        assert len(result) == 1
        assert result[0][0] == "Rückmeldung"

    def test_preamble_and_headings(self):
        text = "Intro text.\n\n## Section A\n\nContent A.\n\n## Section B\n\nContent B."
        result = _split_by_heading(text, H2_PATTERN)
        assert len(result) == 3
        assert result[0][0] == ""
        assert "Intro" in result[0][1]
        assert result[1][0] == "Section A"
        assert result[2][0] == "Section B"

    def test_h3_splitting(self):
        text = "### Sub A\n\nContent A.\n\n### Sub B\n\nContent B."
        result = _split_by_heading(text, H3_PATTERN)
        assert len(result) == 2
        assert result[0][0] == "Sub A"
        assert result[1][0] == "Sub B"


class TestChunkWebPage:
    def test_empty_content(self):
        chunks = chunk_web_page("", page_title="Test", source_url="https://example.com", topic_slug="test")
        assert chunks == []

    def test_simple_page(self):
        content = "## Rückmeldung\n\nDie Rückmeldung erfolgt durch Überweisung."
        chunks = chunk_web_page(
            content,
            page_title="Rückmeldung",
            source_url="https://lmu.de/rueckmeldung",
            topic_slug="rueckmeldung",
        )
        assert len(chunks) >= 1
        assert chunks[0].doc_type == "web_1x1"
        assert chunks[0].topic_slug == "rueckmeldung"
        assert chunks[0].source_url == "https://lmu.de/rueckmeldung"
        assert "Rückmeldung" in chunks[0].section_title

    def test_multiple_h2_sections(self):
        content = "## Fristen\n\nFrist info.\n\n## Kosten\n\nKosten info."
        chunks = chunk_web_page(
            content, page_title="Test", source_url="https://example.com", topic_slug="test",
        )
        assert len(chunks) == 2
        titles = {c.section_title for c in chunks}
        assert "Fristen" in titles
        assert "Kosten" in titles

    def test_external_links_appended(self):
        content = "## Info\n\nSome content."
        links = [{"label": "Studierendenwerk", "url": "https://studierendenwerk.de"}]
        chunks = chunk_web_page(
            content,
            page_title="Test",
            source_url="https://example.com",
            topic_slug="test",
            external_links=links,
        )
        combined_content = " ".join(c.content for c in chunks)
        assert "Studierendenwerk" in combined_content

    def test_chunk_index_sequential(self):
        content = "## A\n\nText A.\n\n## B\n\nText B.\n\n## C\n\nText C."
        chunks = chunk_web_page(
            content, page_title="Test", source_url="https://example.com", topic_slug="test",
        )
        indices = [c.chunk_index for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_h3_subsections(self):
        content = (
            "## Hauptthema\n\n"
            "### Unterthema A\n\nInhalt A.\n\n"
            "### Unterthema B\n\nInhalt B."
        )
        chunks = chunk_web_page(
            content, page_title="Test", source_url="https://example.com", topic_slug="test",
        )
        assert len(chunks) >= 1
        has_combined_title = any(">" in c.section_title for c in chunks)
        assert has_combined_title or len(chunks) == 1

    def test_page_title_fallback(self):
        content = "Just plain text without any headings."
        chunks = chunk_web_page(
            content, page_title="Fallback Title", source_url="https://example.com", topic_slug="test",
        )
        assert len(chunks) == 1
        assert chunks[0].section_title == "Fallback Title"
