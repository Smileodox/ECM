import json
import pytest
from pathlib import Path
from unittest.mock import patch
from app.models import Citation


@pytest.fixture
def mock_manifest(tmp_path):
    manifest = {
        "entries": [
            {"filename": "bwl-2018-ps00.pdf", "doc_type": "psto", "programs": ["Betriebswirtschaftslehre"], "source_url": ""},
            {"filename": "bwl-2024-ps00.pdf", "doc_type": "psto", "programs": ["Betriebswirtschaftslehre"], "source_url": ""},
            {"filename": "bwl-2024-ps01.pdf", "doc_type": "aenderung", "programs": ["Betriebswirtschaftslehre"], "source_url": ""},
            {"filename": "bwl-2020-ps01.pdf", "doc_type": "aenderung", "programs": ["Betriebswirtschaftslehre"], "source_url": ""},
            {"filename": "info-2022-ps00.pdf", "doc_type": "psto", "programs": ["Informatik"], "source_url": ""},
            {"filename": "info-2022-ps01.pdf", "doc_type": "aenderung", "programs": ["Informatik"], "source_url": ""},
            {"filename": "info-eignung-2022.pdf", "doc_type": "eignung", "programs": ["Informatik"], "source_url": ""},
            {"filename": "info-zulassung-2019.pdf", "doc_type": "zulassung", "programs": ["Informatik"], "source_url": ""},
        ]
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def make_citation(**overrides) -> Citation:
    defaults = dict(
        index=1,
        section_id="§1",
        section_title="Test",
        page_number=1,
        doc_name="Test Doc",
        doc_filename="test.pdf",
        program_name="Informatik",
        content="test content",
        doc_type="psto",
        reranker_score=2.0,
        chunk_index=0,
    )
    defaults.update(overrides)
    return Citation(**defaults)
