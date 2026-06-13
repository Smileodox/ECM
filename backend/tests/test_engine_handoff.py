"""End-to-end wiring tests for the hand-off / abstention / grounding flow.

Mocks retrieval + the LLM stream so the full chat_stream orchestration can be
exercised offline: solid answer, uncertain hand-off, abstain hand-off, and a
grounding retraction on an invented paragraph.
"""

import json

import pytest
from unittest.mock import AsyncMock

import app.chat.engine as engine
from app.search.retriever import RetrievalResult
from app.search.router import QueryRoute
from tests.conftest import make_citation

_DE_QUERY = "Wie viele ECTS-Punkte hat die Masterarbeit im Studiengang Informatik?"


async def _good_stream(*args, **kwargs):
    for tok in ["Laut § 14 ", "umfasst die Masterarbeit ", "30 ECTS [Quelle 1]."]:
        yield tok


async def _invented_stream(*args, **kwargs):
    for tok in ["Laut § 99 ", "ist das ausgeschlossen ", "[Quelle 1]."]:
        yield tok


async def _collect(gen) -> list[dict]:
    return [ev async for ev in gen]


def _data(events: list[dict], event_type: str) -> list[dict]:
    return [json.loads(e["data"]) for e in events if e["event"] == event_type]


def _tokens(events: list[dict]) -> str:
    return "".join(d["content"] for d in _data(events, "token"))


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(engine, "_is_in_domain", AsyncMock(return_value=True))
    monkeypatch.setattr(engine, "classify_route", AsyncMock(return_value=QueryRoute.REGULATION))
    monkeypatch.setattr("app.chat.providers.resolve_model", lambda m: "gpt-5.4")
    monkeypatch.setattr("app.chat.providers.stream_chat", _good_stream)


def _result(citations, confidence, top_score):
    return RetrievalResult(
        citations=citations,
        low_confidence=confidence != "solid",
        confidence=confidence,
        top_score=top_score,
    )


@pytest.mark.asyncio
async def test_solid_answer_no_notice(no_network, monkeypatch):
    cit = make_citation(index=1, section_id="§14", content="§ 14 Masterarbeit: 30 ECTS.")
    monkeypatch.setattr(engine, "retrieve", AsyncMock(return_value=_result([cit], "solid", 2.5)))

    events = await _collect(engine.chat_stream(_DE_QUERY, [], program_name="Informatik", request_id="t1"))
    tokens = _tokens(events)

    assert "Unsichere Antwort" not in tokens
    assert "Bitte prüfen" not in tokens
    metrics = _data(events, "metrics")[0]
    assert metrics["confidence"] == "solid"
    assert metrics["verification"] == "grounded"  # §14 is in the cited chunk


@pytest.mark.asyncio
async def test_uncertain_prepends_visible_notice(no_network, monkeypatch):
    cit = make_citation(index=1, section_id="§14", content="§ 14 Masterarbeit.")
    monkeypatch.setattr(engine, "retrieve", AsyncMock(return_value=_result([cit], "uncertain", 1.0)))

    events = await _collect(engine.chat_stream(_DE_QUERY, [], program_name="Informatik", request_id="t2"))
    tokens = _tokens(events)

    assert "Unsichere Antwort" in tokens          # visible banner, not a buried context hint
    assert "https://" in tokens                    # escalation contact present
    metrics = _data(events, "metrics")[0]
    assert metrics["confidence"] == "uncertain"


@pytest.mark.asyncio
async def test_abstain_hands_off_without_answering(no_network, monkeypatch):
    monkeypatch.setattr(engine, "retrieve", AsyncMock(return_value=_result([], "abstain", 0.2)))

    events = await _collect(engine.chat_stream(_DE_QUERY, [], program_name="Informatik", request_id="t3"))
    tokens = _tokens(events)

    assert "keine passenden Informationen" in tokens  # build_no_info_fallback
    assert "30 ECTS" not in tokens                     # the LLM never ran
    assert _data(events, "metrics") == []              # abstain path emits no metrics event


@pytest.mark.asyncio
async def test_grounding_retraction_on_invented_section(no_network, monkeypatch):
    cit = make_citation(index=1, section_id="§14", content="§ 14 Masterarbeit: 30 ECTS.")
    monkeypatch.setattr(engine, "retrieve", AsyncMock(return_value=_result([cit], "solid", 2.5)))
    monkeypatch.setattr("app.chat.providers.stream_chat", _invented_stream)

    events = await _collect(engine.chat_stream(_DE_QUERY, [], program_name="Informatik", request_id="t4"))
    tokens = _tokens(events)

    assert "Bitte prüfen" in tokens                    # retraction appended
    metrics = _data(events, "metrics")[0]
    assert metrics["verification"] == "ungrounded"     # §99 is in no cited source
