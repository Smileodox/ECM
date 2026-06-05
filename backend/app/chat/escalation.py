"""Topic-based escalation routing to LMU contact points."""

import re

ESCALATION_CONTACTS: dict[str, dict[str, str]] = {
    "pruefungsamt": {
        "name_de": "Prüfungsamt",
        "name_en": "Examination Office (Prüfungsamt)",
        "url": "https://www.lmu.de/de/studium/wichtige-kontakte/pruefungsaemter/",
        "url_en": "https://www.lmu.de/de/studium/wichtige-kontakte/pruefungsaemter/",
        "scope": "exam regulations, grades, thesis registration, credit transfer",
    },
    "studienberatung": {
        "name_de": "Zentrale Studienberatung",
        "name_en": "Central Student Advisory Services (Zentrale Studienberatung)",
        "url": "https://www.lmu.de/de/studium/wichtige-kontakte/zentrale-studienberatung/",
        "url_en": "https://www.lmu.de/de/studium/wichtige-kontakte/zentrale-studienberatung/",
        "scope": "general study advice, changing majors, study problems, orientation",
    },
    "studentenkanzlei": {
        "name_de": "Studentenkanzlei",
        "name_en": "Student Office (Studentenkanzlei)",
        "url": "https://www.lmu.de/de/studium/wichtige-kontakte/studentenkanzlei/",
        "url_en": "https://www.lmu.de/de/studium/wichtige-kontakte/studentenkanzlei/",
        "scope": "enrollment, re-registration, exmatriculation, certificates, address changes",
    },
    "international": {
        "name_de": "International Office",
        "name_en": "International Office",
        "url": "https://www.lmu.de/de/studium/wichtige-kontakte/international-office/",
        "url_en": "https://www.lmu.de/en/study/important-contacts/international-office/",
        "scope": "visa, international admission, exchange programs",
    },
    "studierendenwerk": {
        "name_de": "Studierendenwerk München Oberbayern",
        "name_en": "Student Services (Studierendenwerk)",
        "url": "https://www.studierendenwerk-muenchen-oberbayern.de/",
        "url_en": "https://www.studierendenwerk-muenchen-oberbayern.de/",
        "scope": "housing, BAföG/financial aid, social counseling, Mensa",
    },
    "it_servicedesk": {
        "name_de": "IT-Servicedesk der LMU",
        "name_en": "LMU IT Service Desk",
        "url": "https://www.lmu.de/it-servicedesk",
        "url_en": "https://www.lmu.de/it-servicedesk",
        "scope": "LMU account, email, eduroam, WiFi, software licenses",
    },
    "fachstudienberatung": {
        "name_de": "Fachstudienberatung",
        "name_en": "Academic Advisor for your program (Fachstudienberatung)",
        "url": "https://www.lmu.de/de/workspace-fuer-studierende/1x1-des-studiums/fachstudienberatung/",
        "url_en": "https://www.lmu.de/de/workspace-fuer-studierende/1x1-des-studiums/fachstudienberatung/",
        "scope": "subject-specific course planning, module selection, curriculum",
    },
}

# ---------------------------------------------------------------------------
# Faculty-specific Fachstudienberatung URLs
# ---------------------------------------------------------------------------

_FACULTY_FSB_URLS: dict[str, list[str]] = {
    "https://studiengangskoordination.ifi.lmu.de/": [
        "Informatik", "Medieninformatik", "Mensch-Computer-Interaktion",
        "Software Engineering", "Data Science", "Bioinformatik",
        "Computerlinguistik mit Nebenfach", "Computerlinguistik mit Profilbereich",
    ],
    "https://www.math.lmu.de/studium/fachstudium/studienberatung/index.html": [
        "Mathematik", "Finanz- und Versicherungsmathematik",
        "Theoretical and Mathematical Physics",
    ],
    "https://www.stat.lmu.de/en/studies/student-counselling/": [
        "Statistics and Data Science",
    ],
    "https://www.physik.lmu.de/de/studium/fachstudienberatung-und-kontakt/": [
        "Physics", "Astrophysics", "Meteorology", "Geophysics",
    ],
    "https://www.cup.lmu.de/de/studium/beratungs-und-ansprechstellen-an-der-fakultaet/": [
        "Chemie", "Biochemie", "Pharmaceutical Sciences",
    ],
    "https://www.bio.lmu.de/de/studium/studiengangskoordination/": [
        "Molecular and Cellular Biology", "Plant Sciences",
        "Evolution, Ecology and Systematics",
        "Human Biology - Principles of Health and Disease", "Neurosciences",
    ],
    "https://www.geo.lmu.de/geographie/de/studium/studienberatung-und-anlaufstellen/": [
        "Human Geography and Sustainability: Monitoring, Modeling and Management",
        "Umweltsysteme und Nachhaltigkeit - Monitoring, Modellierung und Management",
        "Environment and Society", "Geomaterials and Geochemistry",
        "Geobiology and Paleobiology", "Ingenieur- und Hydrogeologie",
    ],
    "https://www.econ.lmu.de/de/studium/": [
        "Economics", "Quantitative Economics", "Insurance",
    ],
    "https://www.som.lmu.de/de/studium/studierende-quereinsteigende/fachstudienberatung/": [
        "Betriebswirtschaftslehre", "Management and Digital Technologies",
        "Master of Science in Management - European Triple Degree",
        "Master of Science in Management – International Triple Degree",
        "Wirtschaftspädagogik I",
        "Wirtschaftspädagogik mit integriertem Wahlfach (Wirtschaftspädagogik II)",
    ],
    "https://www.jura.lmu.de/de/studium/fachstudienberatung/": [],
    "https://www.med.lmu.de/de/studium/kontakt/": [
        "International Health", "Public Health", "Epidemiologie",
    ],
    "https://www.vetmed.lmu.de/studium/a_bis_z/fachstudienberat/index.html": [],
    "https://www.lmu.de/kunstwissenschaften/de/studium/studienberatung/": [
        "Kunstgeschichte", "Spätantike und Byzantinische Kunstgeschichte",
        "Geschichte", "Klassische Archäologie",
        "Provinzialrömische Archäologie", "Vor- und Frühgeschichtliche Archäologie",
        "Vorderasiatische Archäologie", "Mittelalter- und Renaissancestudien",
    ],
    "https://www.philosophie.lmu.de/de/studium/studienberatung-und-studienkoordination/": [
        "Philosophie", "Antike Philosophie", "Theoretische Philosophie",
        "Logic and Philosophy of Science", "Philosophie, Politik und Wirtschaft",
    ],
    "https://www.fak11.lmu.de/studium/studienberatung/": [
        "Psychologie: Klinische Psychologie und Psychotherapie",
        "Psychologie: Wirtschafts-, Organisations- und Sozialpsychologie",
        "Psychology: Learning Sciences and Human Development",
        "Neuro-cognitive Psychology",
        "Pädagogik mit Schwerpunkt Bildungsforschung und Bildungsmanagement",
        "Prävention, Inklusion und Rehabilitation (PIR) - Gehörlosenpädagogik",
        "Prävention, Inklusion und Rehabilitation (PIR) - Gehörlosenpädagogik (Modellstudiengang)",
        "Prävention, Inklusion und Rehabilitation (PIR) - Schwerhörigenpädagogik",
        "Prävention, Inklusion und Rehabilitation (PIR) - Schwerhörigenpädagogik (Modellstudiengang)",
        "Musikpädagogik",
    ],
    "https://www.kw.lmu.de/vkrw/de/kontakt-und-beratung/": [
        "Empirische Kulturwissenschaft und Europäische Ethnologie",
        "Religions- und Kulturwissenschaft", "Religion und Philosophie in Asien",
        "Digital Cultural Heritage", "Ethnologie",
        "Ägyptologie und Koptologie", "Altorientalistik", "Byzantinistik",
    ],
    "https://www.sprachlit.lmu.de/de/studium/": [
        "Allgemeine und Vergleichende Literaturwissenschaft",
        "Germanistische Linguistik", "Germanistische Literaturwissenschaft",
        "English Studies", "Cultural and Cognitive Linguistics",
        "Romanistik", "Italienstudien", "Skandinavistik", "Slavistik",
        "Griechische Philologie", "Lateinische Philologie",
        "Albanologie", "Finnougristik", "Neogräzistik",
        "Phonetik und Sprachverarbeitung", "Phonetik und Sprachverarbeitung mit Nebenfach",
        "Vergleichende Indoeuropäische Sprachwissenschaft",
        "Deutsch als Fremdsprache", "Literarisches Übersetzen",
        "Interkulturelle Kommunikation", "Sprachtherapie",
        "Buchwissenschaft: Buch- und Medienforschung",
        "Buchwissenschaft: Verlagspraxis",
    ],
    "https://www.sw.lmu.de/de/studiengaenge/": [
        "Politikwissenschaft", "Soziologie",
        "Kommunikations- und Medienforschung", "Journalismus",
        "Journalism, Media and Globalisation", "Strategische Kommunikation",
        "Computational Social Science",
    ],
    "https://www.evtheol.lmu.de/de/die-fakultaet/ansprechpartner-innen-und-kontakt/": [],
    "https://www.kaththeol.lmu.de/de/studium/beratung-und-services/": [],
}

_FSB_OVERVIEW_URL = "https://www.lmu.de/de/workspace-fuer-studierende/1x1-des-studiums/fachstudienberatung/"

_PROGRAM_TO_FSB: dict[str, str] = {}
for _url, _programs in _FACULTY_FSB_URLS.items():
    for _prog in _programs:
        _PROGRAM_TO_FSB[_prog] = _url


def get_fsb_url(program_name: str) -> str:
    """Return the faculty-specific Fachstudienberatung URL for a program."""
    return _PROGRAM_TO_FSB.get(program_name, _FSB_OVERVIEW_URL)


# ---------------------------------------------------------------------------
# Topic-based routing
# ---------------------------------------------------------------------------

_TOPIC_OVERRIDES: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"(?:visa|aufenthalts|international|exchange|erasmus|ausland)", re.I),
     ["international"]),
    (re.compile(r"(?:bafög|bafoeg|wohnung|wohnen|mensa|cafeteria|sozialberatung|financial aid|housing)", re.I),
     ["studierendenwerk"]),
    (re.compile(r"(?:eduroam|wifi|wlan|lmu.?account|e.?mail|software.?lizenz|it.?service|vpn)", re.I),
     ["it_servicedesk"]),
    (re.compile(r"(?:rückmeldung|exmatrikulation|immatrikulation|einschreibung|semesterbeitrag|lmucard|bescheinigung|adressänderung|re.?register|re.?enroll)", re.I),
     ["studentenkanzlei"]),
    (re.compile(r"(?:modulplan|stundenplan|kursauswahl|fächerkombination|studienplan|welche.?module|which.?modules|course.?selection)", re.I),
     ["fachstudienberatung"]),
]

_ESCALATION_ROUTING: dict[str, list[str]] = {
    "regulation:eligibility": ["pruefungsamt", "fachstudienberatung"],
    "regulation:amendment": ["pruefungsamt"],
    "regulation:factual": ["pruefungsamt", "fachstudienberatung"],
    "regulation:process": ["pruefungsamt"],
    "regulation:comparison": ["fachstudienberatung", "pruefungsamt"],
    "regulation:deadline": ["pruefungsamt", "studentenkanzlei"],
    "regulation:contact": ["pruefungsamt"],
    "general:administrative": ["studentenkanzlei"],
    "general:deadline": ["studentenkanzlei"],
    "general:contact": ["studienberatung"],
    "general:process": ["studentenkanzlei", "studienberatung"],
    "general:factual": ["studienberatung"],
    "general:default": ["studienberatung"],
    "both:eligibility": ["pruefungsamt", "studentenkanzlei"],
    "both:process": ["studentenkanzlei", "pruefungsamt"],
    "both:default": ["studienberatung", "pruefungsamt"],
}


def resolve_escalation_contacts(
    query: str,
    route: str = "general",
    query_type: str = "factual",
    program_name: str | None = None,
) -> list[dict[str, str]]:
    """Return 1-2 relevant contact dicts for escalation, based on query topic."""
    contact_keys: list[str] | None = None

    for pattern, keys in _TOPIC_OVERRIDES:
        if pattern.search(query):
            contact_keys = keys
            break

    if contact_keys is None:
        key = f"{route}:{query_type}"
        contact_keys = _ESCALATION_ROUTING.get(key)
        if not contact_keys:
            contact_keys = _ESCALATION_ROUTING.get(f"{route}:default", ["studienberatung"])

    contacts = [dict(ESCALATION_CONTACTS[k]) for k in contact_keys[:2]]

    if program_name:
        fsb_url = get_fsb_url(program_name)
        for c in contacts:
            if c["name_de"] == "Fachstudienberatung":
                c["url"] = fsb_url
                c["url_en"] = fsb_url

    return contacts
