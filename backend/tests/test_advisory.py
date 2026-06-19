"""Tests for the advisory (program-selection) path: prompt layer + guaranteed hand-off.

The advisory path ("what can I study with degree X?") is covered by neither the
answerability score gate nor the grounding verifier, so engine.chat_stream must
guarantee a not-binding disclaimer + referral. These tests exercise both the pure
prompt helpers and the end-to-end wiring (retrieval + LLM stream mocked).
"""

import json

import pytest
from unittest.mock import AsyncMock

import app.chat.engine as engine
from app.chat.prompts import build_advisory_disclaimer, build_system_prompt
from app.search.retriever import RetrievalResult
from app.search.router import QueryRoute
from tests.conftest import make_citation


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #

class TestAdvisoryDisclaimer:
    def test_de_anchors_on_studienberatung(self):
        msg = build_advisory_disclaimer(lang="de")
        assert "verbindliche Einschätzung" in msg  # calm hand-off, not an alarming caveat
        assert "Zentrale Studienberatung" in msg
        assert "International Office" not in msg  # not added unless requested

    def test_de_with_international(self):
        msg = build_advisory_disclaimer(lang="de", include_international=True)
        assert "Zentrale Studienberatung" in msg
        assert "International Office" in msg

    def test_en_uses_english_contacts(self):
        msg = build_advisory_disclaimer(lang="en", include_international=True)
        assert "binding assessment" in msg  # calm hand-off, not an alarming caveat
        assert "International Office" in msg
        assert "/en/" in msg  # International Office url_en is the English page

    def test_referral_present_emits_io_only(self):
        # When the answer already links an advising contact, only the IO pointer is added.
        msg = build_advisory_disclaimer(lang="en", include_international=True, referral_present=True)
        assert "International Office" in msg
        assert "not binding study advice" not in msg   # short pointer, not the full disclaimer
        assert "Central Student Advisory" not in msg    # Studienberatung not duplicated

    def test_never_asserts_eligibility(self):
        for lang in ("de", "en"):
            msg = build_advisory_disclaimer(lang=lang)
            assert "qualif" not in msg.lower() or "decided solely" in msg  # no "you qualify" claims


class TestAdvisoryLayer:
    def test_layer_present_with_studienangebot(self):
        p = build_system_prompt(
            "Was kann ich mit einem Bachelor in BWL studieren?",
            content_types={"studienangebot"},
            route="general",
        )
        assert "Studienwahl-Fragen" in p
        assert "Beurteile NIE verbindlich" in p

    def test_layer_absent_without_studienangebot(self):
        p = build_system_prompt(
            "Wie melde ich mich zurück?",
            content_types={"web_1x1"},
            route="general",
        )
        assert "Studienwahl-Fragen" not in p


# --------------------------------------------------------------------------- #
# End-to-end wiring
# --------------------------------------------------------------------------- #

_DE_ADVISORY = "Was kann ich mit einem Bachelor in BWL studieren?"
_EN_ADVISORY = "What can I study with a bachelor in business?"


async def _collect(gen):
    return [ev async for ev in gen]


def _data(events, event_type):
    return [json.loads(e["data"]) for e in events if e["event"] == event_type]


def _tokens(events):
    return "".join(d["content"] for d in _data(events, "token"))


def _sa_citation():
    """A studienangebot (program-catalogue) citation -> content_types == {'studienangebot'}."""
    return make_citation(
        index=1, doc_type="studienangebot", section_title="Betriebswirtschaftslehre (Master)",
        doc_name="Betriebswirtschaftslehre (Master)",
        content="Master BWL, 120 ECTS. Zulassung: einschlägiger Bachelor mit 60 ECTS BWL.",
    )


def _result(citations, confidence="solid", top_score=2.5):
    return RetrievalResult(
        citations=citations,
        low_confidence=confidence != "solid",
        confidence=confidence,
        top_score=top_score,
    )


@pytest.fixture
def advisory_net(monkeypatch):
    # GENERAL route -> retrieve_web + grounding skipped, isolating the advisory guarantee.
    monkeypatch.setattr(engine, "_is_in_domain", AsyncMock(return_value=True))
    monkeypatch.setattr(engine, "classify_route", AsyncMock(return_value=QueryRoute.GENERAL))
    monkeypatch.setattr(engine, "retrieve_web", AsyncMock(return_value=_result([_sa_citation()])))
    monkeypatch.setattr("app.chat.providers.resolve_model", lambda m: "gpt-5.4")


@pytest.mark.asyncio
async def test_advisory_appends_disclaimer_when_model_omits_referral(advisory_net, monkeypatch):
    async def _stream(*a, **k):
        for tok in ["Infrage kommen könnten ", "der Master BWL und ", "Management [Quelle 1]."]:
            yield tok
    monkeypatch.setattr("app.chat.providers.stream_chat", _stream)

    tokens = _tokens(await _collect(engine.chat_stream(_DE_ADVISORY, [], request_id="a1")))

    assert "verbindliche Einschätzung" in tokens            # guaranteed hand-off appended
    assert "Zentrale Studienberatung" in tokens             # hand-off present
    assert "International Office" not in tokens              # German query -> no IO


@pytest.mark.asyncio
async def test_advisory_no_double_referral_when_model_already_linked(advisory_net, monkeypatch):
    sb_url = "https://www.lmu.de/de/studium/wichtige-kontakte/zentrale-studienberatung/"

    async def _stream(*a, **k):
        yield "Schau dir den Master BWL an [Quelle 1]. "
        yield f"Mehr bei der [Zentrale Studienberatung]({sb_url})."
    monkeypatch.setattr("app.chat.providers.stream_chat", _stream)

    tokens = _tokens(await _collect(engine.chat_stream(_DE_ADVISORY, [], request_id="a2")))

    assert "unverbindliche Orientierung" not in tokens       # boilerplate NOT duplicated
    assert tokens.count("Zentrale Studienberatung") == 1     # model's own link kept, not doubled


@pytest.mark.asyncio
async def test_advisory_english_adds_international_office(advisory_net, monkeypatch):
    async def _stream(*a, **k):
        for tok in ["You could consider ", "the Master in Management [Quelle 1]."]:
            yield tok
    monkeypatch.setattr("app.chat.providers.stream_chat", _stream)

    tokens = _tokens(await _collect(engine.chat_stream(_EN_ADVISORY, [], request_id="a3")))

    assert "binding assessment" in tokens
    assert "International Office" in tokens                   # English query -> international applicant


@pytest.mark.asyncio
async def test_advisory_english_forces_io_even_when_studienberatung_present(advisory_net, monkeypatch):
    sb_url = "https://www.lmu.de/de/studium/wichtige-kontakte/zentrale-studienberatung/"

    async def _stream(*a, **k):
        yield "Consider the Master in Management [Quelle 1]. "
        yield f"See the [Central Student Advisory Services]({sb_url})."
    monkeypatch.setattr("app.chat.providers.stream_chat", _stream)

    tokens = _tokens(await _collect(engine.chat_stream(_EN_ADVISORY, [], request_id="a4")))

    assert "International Office" in tokens                       # IO enforced for EN even with SB present
    assert tokens.count("Central Student Advisory Services") == 1  # model's SB link not duplicated
