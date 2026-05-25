"""
Integration tests against a running backend on localhost:8000.

Run with:
    PYTHONPATH=. uv run pytest tests/test_integration.py -m integration -v

Requires: backend running (`uv run uvicorn app.main:app --port 8000`)
"""

import asyncio
import json
from collections import defaultdict

import httpx
import pytest

BASE_URL = "http://localhost:8000"
TIMEOUT = 45.0  # Azure roundtrip + gpt-4o can take 8-12s; stream up to 30s


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _parse_sse(response: httpx.Response) -> dict[str, list]:
    """Parse an SSE stream into {event_name: [parsed_data, ...]}."""
    events: dict[str, list] = defaultdict(list)
    current_event = ""
    async for line in response.aiter_lines():
        if line.startswith("event:"):
            current_event = line[6:].strip()
        elif line.startswith("data:"):
            raw = line[5:].strip()
            try:
                events[current_event].append(json.loads(raw))
            except json.JSONDecodeError:
                pass
    return dict(events)


@pytest.mark.integration
async def test_health_ok():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        r = await client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok", f"Health check degraded: {body}"
    assert body["openai_ok"] is True
    assert body["search_ok"] is True


@pytest.mark.integration
async def test_programs_returns_list():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        r = await client.get("/api/programs")
    assert r.status_code == 200
    programs = r.json()["programs"]
    assert isinstance(programs, list)
    assert len(programs) > 50, f"Expected >50 programs, got {len(programs)}"


@pytest.mark.integration
async def test_chat_basic_stream():
    """Full SSE stream for a simple factual query — all required events present."""
    payload = {
        "message": "Wie viele ECTS umfasst der Master Informatik?",
        "history": [],
        "program_name": "Informatik",
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            assert response.status_code == 200
            events = await _parse_sse(response)

    # Required events must be present
    assert "pre_citations" in events, "Missing pre_citations event"
    assert "citations" in events, "Missing citations event"
    assert "token" in events, "Missing token events (no content streamed)"
    assert "done" in events, "Missing done event"
    assert "metrics" in events, "Missing metrics event"

    # Tokens must have built up some content
    content = "".join(e["content"] for e in events["token"] if "content" in e)
    assert len(content) > 20, f"Response too short: {repr(content)}"

    # Citations must have at least one entry with a section_id
    citations = events["citations"][0].get("citations", [])
    assert len(citations) >= 1, "No citations returned"
    assert citations[0].get("section_id"), "First citation missing section_id"


@pytest.mark.integration
async def test_chat_follow_up_query_rewrite():
    """Follow-up message should be resolved via query rewrite and produce a response."""
    history = [
        {"role": "user", "content": "Wie viele ECTS umfasst der Master Informatik?"},
        {"role": "assistant", "content": "Der Master Informatik umfasst 120 ECTS."},
    ]
    payload = {
        "message": "Und beim BWL-Master?",
        "history": history,
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            assert response.status_code == 200
            events = await _parse_sse(response)

    assert "token" in events
    content = "".join(e["content"] for e in events["token"] if "content" in e)
    assert len(content) > 10, "Follow-up produced no content"


@pytest.mark.integration
async def test_chat_eligibility_query_routes_to_eignung():
    """Eligibility queries should prefer Eignungssatzung documents (doc_type=eignung)."""
    payload = {
        "message": "Was sind die Zugangsvoraussetzungen für den Master Informatik?",
        "history": [],
        "program_name": "Informatik",
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        async with client.stream("POST", "/api/chat", json=payload) as response:
            assert response.status_code == 200
            events = await _parse_sse(response)

    citations = events.get("citations", [{}])[0].get("citations", [])
    if citations:
        doc_types = {c.get("doc_type") for c in citations}
        assert "eignung" in doc_types or "psto" in doc_types, f"Unexpected doc_types: {doc_types}"


@pytest.mark.integration
async def test_feedback_accepted():
    payload = {
        "message_id": "integration-test-001",
        "rating": "up",
        "query": "Test query",
        "comment": "Integration test feedback",
    }
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        r = await client.post("/api/feedback", json=payload)
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.integration
async def test_ingest_requires_auth():
    """POST /api/ingest without a key must return 401 or 503."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        r = await client.post("/api/ingest")
    assert r.status_code in (401, 503), f"Expected 401/503, got {r.status_code}"


@pytest.mark.integration
async def test_ingest_wrong_key_returns_401():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        r = await client.post(
            "/api/ingest",
            headers={"X-Ingest-Key": "definitely-wrong-key-12345"},
        )
    assert r.status_code == 401


@pytest.mark.integration
async def test_rate_limit_chat():
    """Fire 12 parallel chat requests — at least one should get 429."""
    payload = {
        "message": "Was ist ECTS?",
        "history": [],
    }

    async def _single(client: httpx.AsyncClient) -> int:
        # Only read the first byte — we care about the status code, not the body
        async with client.stream("POST", "/api/chat", json=payload) as r:
            return r.status_code

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        results = await asyncio.gather(*[_single(client) for _ in range(12)])

    status_codes = list(results)
    assert 429 in status_codes, (
        f"Expected at least one 429 from 12 parallel requests, got: {status_codes}"
    )
