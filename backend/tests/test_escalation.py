from app.chat.escalation import (
    ESCALATION_CONTACTS,
    get_fsb_url,
    resolve_escalation_contacts,
)
from app.chat.prompts import build_no_info_fallback, build_system_prompt


class TestGetFsbUrl:
    def test_known_program(self):
        url = get_fsb_url("Informatik")
        assert "ifi.lmu.de" in url

    def test_math_program(self):
        url = get_fsb_url("Mathematik")
        assert "math.lmu.de" in url

    def test_unknown_program_fallback(self):
        url = get_fsb_url("Unterwasserkorbflechten")
        assert "fachstudienberatung" in url

    def test_bwl_program(self):
        url = get_fsb_url("Betriebswirtschaftslehre")
        assert "som.lmu.de" in url


class TestResolveEscalationContacts:
    def test_it_query_keyword_override(self):
        contacts = resolve_escalation_contacts("How do I connect to eduroam?")
        assert contacts[0]["name_de"] == "IT-Servicedesk der LMU"

    def test_housing_query_keyword_override(self):
        contacts = resolve_escalation_contacts("Wo finde ich eine Wohnung?")
        assert contacts[0]["name_de"] == "Studierendenwerk München Oberbayern"

    def test_bafoeg_query(self):
        contacts = resolve_escalation_contacts("Kann ich BAföG beantragen?")
        assert contacts[0]["name_de"] == "Studierendenwerk München Oberbayern"

    def test_visa_query(self):
        contacts = resolve_escalation_contacts("I need a visa for my studies")
        assert contacts[0]["name_de"] == "International Office"

    def test_rueckmeldung_query(self):
        contacts = resolve_escalation_contacts("Wie funktioniert die Rückmeldung?")
        assert contacts[0]["name_de"] == "Studentenkanzlei"

    def test_regulation_eligibility_route(self):
        contacts = resolve_escalation_contacts(
            "Welche Note brauche ich?", route="regulation", query_type="eligibility",
        )
        assert contacts[0]["name_de"] == "Prüfungsamt"

    def test_general_default(self):
        contacts = resolve_escalation_contacts(
            "Hallo", route="general", query_type="factual",
        )
        assert contacts[0]["name_de"] == "Zentrale Studienberatung"

    def test_returns_max_two(self):
        contacts = resolve_escalation_contacts("Anything")
        assert len(contacts) <= 2

    def test_program_specific_fsb_url(self):
        contacts = resolve_escalation_contacts(
            "Welche Module soll ich wählen?",
            route="regulation",
            query_type="comparison",
            program_name="Informatik",
        )
        fsb = [c for c in contacts if c["name_de"] == "Fachstudienberatung"]
        assert fsb
        assert "ifi.lmu.de" in fsb[0]["url"]

    def test_all_contacts_have_urls(self):
        for key, contact in ESCALATION_CONTACTS.items():
            assert contact["url"].startswith("https://"), f"{key} missing url"
            assert contact["url_en"].startswith("https://"), f"{key} missing url_en"


class TestBuildNoInfoFallback:
    def test_english_contains_url(self):
        msg = build_no_info_fallback(lang="en")
        assert "https://" in msg
        assert "What you can do" in msg

    def test_german_contains_url(self):
        msg = build_no_info_fallback(lang="de")
        assert "https://" in msg
        assert "Was du tun kannst" in msg

    def test_it_query_mentions_it_servicedesk(self):
        msg = build_no_info_fallback(query="eduroam problem", lang="en")
        assert "IT" in msg

    def test_program_specific_url(self):
        msg = build_no_info_fallback(
            query="Welche Module?",
            route="regulation",
            query_type="comparison",
            program_name="Informatik",
        )
        assert "ifi.lmu.de" in msg


class TestBuildSystemPromptLanguage:
    def test_english_reminder_appended(self):
        prompt = build_system_prompt("What are the requirements?")
        assert "REMINDER" in prompt
        assert "ENGLISH" in prompt

    def test_german_no_reminder(self):
        prompt = build_system_prompt("Welche Voraussetzungen gibt es?")
        assert "REMINDER" not in prompt

    def test_escalation_block_present(self):
        prompt = build_system_prompt("Test query")
        assert "Anlaufstellen" in prompt
