"""
Scenario-based integration tests — real student questions, multi-turn, LLM-as-judge.

Run with:
    PYTHONPATH=. uv run pytest tests/test_scenarios.py -m integration -v

Requires: backend running on localhost:8000
"""

import json
from collections import defaultdict

import httpx
import pytest

BASE_URL = "http://localhost:8000"
TIMEOUT = 60.0

JUDGE_SYSTEM = """Du bist Qualitätsprüfer eines LMU-Studienberatungs-Chatbots.
Prüfe die Chatbot-Antwort anhand des angegebenen Kriteriums.
Antworte NUR als JSON (kein Text davor oder danach):
{"pass": true/false, "score": 1-5, "reason": "max 1 Satz Begründung"}

Bewertungshinweise:
- Streng bei falschen Fakten oder komplett falschen Anlaufstellen
- Großzügig wenn die Antwort korrekt an ein Amt eskaliert (das ist eine valide Antwort)
- score=1 (komplett falsch/irrelevant) bis 5 (vollständig korrekt)
- pass=true ab score >= 3"""


# ---------------------------------------------------------------------------
# Infrastructure
# ---------------------------------------------------------------------------

async def _parse_sse(response: httpx.Response) -> dict[str, list]:
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


async def _chat(
    client: httpx.AsyncClient,
    message: str,
    history: list[dict] | None = None,
    program_name: str | None = None,
) -> dict[str, list]:
    payload: dict = {"message": message, "history": history or []}
    if program_name:
        payload["program_name"] = program_name
    async with client.stream("POST", "/api/chat", json=payload) as response:
        assert response.status_code == 200, f"HTTP {response.status_code}"
        return await _parse_sse(response)


def _content(events: dict[str, list]) -> str:
    return "".join(e["content"] for e in events.get("token", []) if "content" in e)


def _assert_chat_ok(events: dict[str, list]) -> None:
    """Full structural check — use for queries that should produce a real answer."""
    for ev in ("pre_citations", "citations", "token", "done", "metrics"):
        assert ev in events, f"Missing SSE event: {ev}"
    assert len(_content(events)) > 20, "Response content too short"


def _assert_terminal(events: dict[str, list]) -> None:
    """Minimal check for paths where abstain/rejection may suppress token/metrics."""
    assert "done" in events, "Missing done event"
    assert "error" not in events, f"Error event present: {events.get('error')}"


async def _judge(question: str, answer: str, criteria: str) -> dict:
    from app.config import settings
    from openai import AsyncAzureOpenAI

    client = AsyncAzureOpenAI(
        api_key=settings.azure_openai_api_key,
        azure_endpoint=settings.azure_openai_endpoint,
        api_version=settings.azure_openai_api_version,
    )
    resp = await client.chat.completions.create(
        model=settings.azure_openai_mini_deployment,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": (
                    f"Frage: {question}\n\n"
                    f"Chatbot-Antwort:\n{answer or '(keine Antwort)'}\n\n"
                    f"Kriterium: {criteria}"
                ),
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_completion_tokens=150,
    )
    try:
        return json.loads(resp.choices[0].message.content)
    except (json.JSONDecodeError, IndexError, KeyError) as exc:
        pytest.skip(f"Judge returned invalid response: {exc}")


# ---------------------------------------------------------------------------
# 1. Regulation Queries (PSTO / Eignungssatzung)
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_ects_master_informatik():
    q = "Wie viele ECTS umfasst der Masterstudiengang Informatik?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort eine konkrete ECTS-Gesamtzahl (z.B. 120) für den Master Informatik genannt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_masterarbeit_credits():
    q = "Wie viele ECTS hat die Masterarbeit im Studiengang Informatik?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_chat_ok(events)
    citations = events.get("citations", [{}])[0].get("citations", [])
    doc_types = {c.get("doc_type") for c in citations}
    assert doc_types & {"psto", "aenderung"}, f"Expected psto/aenderung citation, got: {doc_types}"
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort die ECTS-Punkte für die Masterarbeit im Informatik-Studiengang genannt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_pruefungsversuche_limit():
    q = "Wie viele Prüfungsversuche habe ich für Klausuren im Master Informatik?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort eine maximale Anzahl an Prüfungsversuchen genannt oder explizit auf die Prüfungsordnung (§) verwiesen?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_admission_requirements_routes_to_eignung():
    # BWL hat eine indexierte Eignungssatzung; Bioinformatik ist ein LMU/TUM-Jointdegree
    # ohne eigene LMU-Eignungssatzung im CMS und daher ungeeignet für diesen Test.
    q = "Was sind die Zugangsvoraussetzungen für den Master BWL?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Betriebswirtschaftslehre")
    _assert_chat_ok(events)
    citations = events.get("citations", [{}])[0].get("citations", [])
    doc_types = {c.get("doc_type") for c in citations}
    assert doc_types & {"eignung", "psto"}, f"Expected eignung or psto citation, got: {doc_types}"
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort konkrete Zugangsvoraussetzungen für den Master BWL genannt (z.B. Mindestnote, Vorstudium, Eignungsverfahren)?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_notenberechnung():
    q = "Wie wird die Abschlussnote im Master Informatik berechnet?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort erklärt, wie sich die Abschlussnote zusammensetzt (z.B. Modulnoten, Gewichtung, Masterarbeit)?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_thesis_late_submission():
    q = "Was passiert wenn ich die Masterarbeit nicht fristgerecht abgebe?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort Konsequenzen für eine verspätete Abgabe der Masterarbeit genannt (z.B. nicht bestanden, Fristverlängerung, Folgeversuch)?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


# ---------------------------------------------------------------------------
# 2. General / Admin Queries
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_rueckmeldung():
    q = "Wie melde ich mich für das Sommersemester zurück?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort den Rückmeldeprozess erklärt (Frist, Semesterbeitrag) und/oder auf die Studentenkanzlei verwiesen?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_bafog():
    q = "Wie beantrage ich BAföG als Masterstudent an der LMU?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort auf das Studierendenwerk oder die BAföG-Beratung als zuständige Stelle für BAföG-Anträge verwiesen?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_it_account():
    q = "Mein LMU-Account funktioniert nicht, an wen wende ich mich?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort den IT-Servicedesk der LMU als Anlaufstelle für Account-Probleme genannt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_beurlaubung():
    q = "Kann ich mein Studium für ein Semester unterbrechen (Beurlaubung)?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort erklärt, wie Beurlaubung funktioniert (Antrag, Gründe, Fristen) und/oder auf die Studentenkanzlei verwiesen?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_immatrikulationsbescheinigung():
    q = "Wo bekomme ich eine Immatrikulationsbescheinigung?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort erklärt, wo/wie man eine Immatrikulationsbescheinigung bekommt (z.B. online-Portal oder Studentenkanzlei)?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_anrechnung_externe_kurse():
    q = "Kann ich Kurse von einer anderen Universität für meinen Master anrechnen lassen?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort den Anrechnungsprozess erklärt und/oder das Prüfungsamt als zuständige Stelle erwähnt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


# ---------------------------------------------------------------------------
# 3. Multi-Turn Conversations
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_program_context_carry_over():
    """Program set in history should inform the follow-up answer (no program_name in payload)."""
    t1_q = "Ich studiere Informatik im Master."
    t1_a = "Verstanden, ich helfe dir gerne mit Fragen zu deinem Master Informatik."
    t2_q = "Wie viele ECTS brauche ich, um zur Abschlussarbeit zugelassen zu werden?"
    history = [
        {"role": "user", "content": t1_q},
        {"role": "assistant", "content": t1_a},
    ]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, t2_q, history=history)  # intentionally no program_name
    _assert_chat_ok(events)
    v = await _judge(
        f"[Gesprächskontext: Nutzer studiert Master Informatik]\n{t2_q}",
        _content(events),
        "Hat die Antwort die Frage im Kontext des Master Informatik behandelt — entweder mit konkreten ECTS-Anforderungen ODER mit dem Hinweis, dass diese Information nicht verlässlich verfügbar ist und einer Weiterleitung ans Prüfungsamt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_follow_up_program_switch():
    """T2 implicitly switches program — query rewrite must resolve the new one."""
    t1_q = "Wie viele ECTS umfasst der Master Informatik?"
    t1_a = "Der Master Informatik umfasst 120 ECTS-Punkte."
    t2_q = "Und beim BWL-Master?"
    history = [
        {"role": "user", "content": t1_q},
        {"role": "assistant", "content": t1_a},
    ]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, t2_q, history=history)
    _assert_chat_ok(events)
    v = await _judge(
        f"[Kontext: Vorherige Frage war zu Informatik-ECTS]\n{t2_q}",
        _content(events),
        "Hat die Antwort die ECTS-Anzahl für den BWL-Master (Betriebswirtschaftslehre) genannt — nicht nochmals nur für Informatik?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_paragraph_drilldown():
    """T2 asks about a different § — answer must differ from T1."""
    t1_q = "Was regelt §14 der Prüfungsordnung Informatik?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        t1_events = await _chat(client, t1_q, program_name="Informatik")
    _assert_chat_ok(t1_events)
    t1_content = _content(t1_events)

    t2_q = "Und was regelt §15?"
    history = [
        {"role": "user", "content": t1_q},
        {"role": "assistant", "content": t1_content},
    ]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        t2_events = await _chat(client, t2_q, history=history, program_name="Informatik")
    _assert_chat_ok(t2_events)
    t2_content = _content(t2_events)

    assert t1_content[:100] != t2_content[:100], (
        "T2 answer appears identical to T1 — query rewrite may have failed"
    )
    v = await _judge(
        f"[Kontext: T1 fragte nach §14]\n{t2_q}",
        t2_content,
        "Hat die Antwort auf §15 eingegangen und andere Inhalte als §14 geliefert?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_multiturn_english():
    """Full English conversation — language detection and English response on both turns."""
    t1_q = "I need information about re-enrollment for next semester."
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        t1_events = await _chat(client, t1_q)
    _assert_chat_ok(t1_events)
    lang_events = t1_events.get("language", [])
    if lang_events:
        assert lang_events[0].get("lang") == "en", f"Expected lang=en, got: {lang_events[0]}"

    t1_content = _content(t1_events)
    t2_q = "What documents do I need to submit for this?"
    history = [
        {"role": "user", "content": t1_q},
        {"role": "assistant", "content": t1_content},
    ]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        t2_events = await _chat(client, t2_q, history=history)
    _assert_chat_ok(t2_events)
    v = await _judge(
        t2_q,
        _content(t2_events),
        "Is the answer in English and does it address what is required for re-enrollment — "
        "either listing specific documents OR correctly stating that no documents are needed (e.g. just a bank transfer)?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_multiturn_admin_then_specific():
    """Generic admin question followed by a specific regulation follow-up."""
    t1_q = "Ich möchte meine Note für ein Modul anfechten."
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        t1_events = await _chat(client, t1_q, program_name="Informatik")
    _assert_chat_ok(t1_events)
    t1_content = _content(t1_events)

    t2_q = "Gibt es dafür eine Frist?"
    history = [
        {"role": "user", "content": t1_q},
        {"role": "assistant", "content": t1_content},
    ]
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        t2_events = await _chat(client, t2_q, history=history, program_name="Informatik")
    _assert_chat_ok(t2_events)
    v = await _judge(
        f"[Kontext: Nutzer möchte Modulnote anfechten]\n{t2_q}",
        _content(t2_events),
        "Hat die Antwort Fristen oder Zeiträume für die Anfechtung einer Prüfungsnote erwähnt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


# ---------------------------------------------------------------------------
# 4. Edge Cases & Rejection
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_out_of_scope_politics():
    q = "Wer hat die letzte Bundestagswahl gewonnen?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_terminal(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort die Frage korrekt abgelehnt oder erklärt, dass sie außerhalb des LMU-Studienbereichs liegt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_out_of_scope_cooking():
    q = "Erkläre mir wie man Spaghetti Bolognese kocht."
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_terminal(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort die Frage korrekt abgelehnt oder erklärt, dass sie außerhalb des LMU-Studienbereichs liegt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_english_admission_query():
    q = "What are the admission requirements for the Master in Computer Science at LMU?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    lang_events = events.get("language", [])
    if lang_events:
        assert lang_events[0].get("lang") == "en", f"Expected lang=en, got: {lang_events[0]}"
    v = await _judge(
        q,
        _content(events),
        "Is the answer in English and does it address admission requirements for the Computer Science Master at LMU?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_short_ambiguous_query():
    q = "ECTS?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_terminal(events)
    content = _content(events)
    assert len(content) > 10, "Expected some content even for a short query"
    v = await _judge(
        q,
        content,
        "Gibt die Antwort irgendeine sinnvolle Information über ECTS im LMU-Studienkontext?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_fachwechsel_routing():
    """Degree-switch query should draw on both regulation and general info."""
    q = "Ich möchte von BWL auf Volkswirtschaftslehre wechseln, was muss ich tun?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort den Prozess eines Studiengangswechsels erklärt und auf die zuständige Stelle (Studentenkanzlei, Studienberatung oder ähnliches) verwiesen?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_stipendien():
    q = "Gibt es Stipendien für Masterstudenten an der LMU?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q)
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort Stipendienmöglichkeiten oder relevante Beratungsstellen (z.B. Studierendenwerk, Deutschlandstipendium) für LMU-Masterstudenten erwähnt?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"


@pytest.mark.integration
async def test_erasmus():
    q = "Wie kann ich als Informatik-Student ein Auslandssemester über Erasmus machen?"
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        events = await _chat(client, q, program_name="Informatik")
    _assert_chat_ok(events)
    v = await _judge(
        q,
        _content(events),
        "Hat die Antwort den Erasmus-Prozess oder die zuständige Stelle für Auslandsaufenthalte erwähnt (z.B. International Office, Auslandsbeauftragter)?",
    )
    assert v["pass"], f"Judge: {v['reason']} (score={v['score']})"
