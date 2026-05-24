"""Dynamic few-shot example selection based on query type."""

import re

_QUERY_TYPES = {
    "amendment": re.compile(
        r"(?:änderung|geändert|aktualisiert|neufassung|übergangs|alte.+neue|"
        r"änderungssatzung|was hat sich geändert|seit wann gilt)",
        re.IGNORECASE,
    ),
    "eligibility": re.compile(
        r"(?:eignung|zulassung|voraussetzung|anforderung|bewerbung|zugang|"
        r"eignungsverfahren|aptitude|admission|aufnahme|"
        r"requirement|prerequisite|qualification|eligible)",
        re.IGNORECASE,
    ),
    "process": re.compile(
        r"(?:wie melde|wie bewerbe|wie kann ich|was muss ich|anmeldung|ablauf|"
        r"schritt|verfahren|beantragen|einreichen|anrechnung|"
        r"how do i|how can i|how to|register|apply|submit|enroll)",
        re.IGNORECASE,
    ),
    "comparison": re.compile(
        r"(?:unterschied|vergleich|differenz|anders als|im gegensatz|versus|vs\.|"
        r"unterscheidet sich|bachelor und master|pflicht.+wahlpflicht)",
        re.IGNORECASE,
    ),
    "factual": re.compile(
        r"(?:wie viele|wie lang|wie hoch|wie oft|wann|welche|was ist|was sind|"
        r"ects|credits|semester|regelstudienzeit|note|bearbeitungszeit)",
        re.IGNORECASE,
    ),
}

EXAMPLES = {
    "factual": [
        {
            "q": "Wie viele ECTS hat die Masterarbeit in Informatik?",
            "a": "Die Masterarbeit im Masterstudiengang Informatik umfasst **30 ECTS-Punkte** gemäß § 14 Abs. 1 [Quelle 1]. Die Bearbeitungszeit beträgt sechs Monate (§ 14 Abs. 3 [Quelle 1]).",
        },
        {
            "q": "Wie lang ist die Regelstudienzeit im Master BWL?",
            "a": "Die Regelstudienzeit im Masterstudiengang Betriebswirtschaftslehre beträgt **vier Semester** (§ 5 Abs. 1 [Quelle 1]). Insgesamt sind 120 ECTS-Punkte zu erwerben.",
        },
    ],
    "process": [
        {
            "q": "Wie melde ich mich zur Masterarbeit an?",
            "a": "Die Anmeldung zur Masterarbeit erfolgt in folgenden Schritten:\n\n1. **Thema und Betreuer finden**: Wähle einen prüfungsberechtigten Betreuer gemäß § 14 Abs. 2 [Quelle 1].\n2. **Anmeldung beim Prüfungsamt**: Reiche das ausgefüllte Anmeldeformular zusammen mit der Betreuungsbestätigung ein (§ 14 Abs. 4 [Quelle 1]).\n3. **Bearbeitungszeitraum**: Ab Anmeldung hast du sechs Monate Bearbeitungszeit (§ 14 Abs. 3 [Quelle 1]).\n\nBei Fragen zum genauen Ablauf wende dich an dein Prüfungsamt.",
        },
        {
            "q": "Wie läuft die Anrechnung von externen Leistungen?",
            "a": "Die Anrechnung externer Leistungen ist in § 4 [Quelle 1] geregelt:\n\n1. **Antrag stellen** beim Prüfungsausschuss mit Nachweisen über die erbrachte Leistung.\n2. **Gleichwertigkeit prüfen**: Der Prüfungsausschuss prüft, ob Inhalt, Umfang und Anforderungen gleichwertig sind (§ 4 Abs. 1 [Quelle 1]).\n3. **Entscheidung**: Die Entscheidung ergeht in der Regel innerhalb von vier Wochen.\n\nFür Details empfehle ich einen Termin beim Prüfungsamt.",
        },
    ],
    "comparison": [
        {
            "q": "Was ist der Unterschied zwischen Pflicht- und Wahlpflichtmodulen?",
            "a": "Der wesentliche Unterschied:\n\n- **Pflichtmodule** (§ 6 [Quelle 1]): Müssen von allen Studierenden belegt werden. Sie bilden den Kern des Studiengangs.\n- **Wahlpflichtmodule** (§ 7 [Quelle 2]): Hier kannst du aus einem vorgegebenen Katalog wählen. Die Mindestanzahl an ECTS aus Wahlpflichtmodulen ist in der PSTO festgelegt.\n\nBeide zählen gleichermaßen zur Gesamtnote und zu den erforderlichen ECTS-Punkten.",
        },
    ],
    "amendment": [
        {
            "q": "Wurde § 5 der PSTO Informatik geändert?",
            "a": "Ja, § 5 wurde durch die Änderungssatzung vom 15.03.2024 neu gefasst [Quelle 2]. Die Änderung betrifft die Regelstudienzeit, die von 4 auf 3 Semester verkürzt wurde (§ 5 Abs. 1 [Quelle 2]). Alle anderen Paragraphen der ursprünglichen PSTO von 2017 [Quelle 1] gelten unverändert weiter.",
        },
        {
            "q": "Gilt die Änderung auch für Studierende die vor 2024 angefangen haben?",
            "a": "Ob eine Änderungssatzung auch für bereits immatrikulierte Studierende gilt, regelt die **Übergangsbestimmung** in der jeweiligen Änderungssatzung. Leider finde ich in den mir vorliegenden Quellen keine explizite Übergangsregelung zu dieser Frage [Quelle 1]. Bitte wende dich an das Prüfungsamt, um deine individuelle Situation zu klären.",
        },
    ],
    "eligibility": [
        {
            "q": "Welche Voraussetzungen brauche ich für den Master Informatik?",
            "a": "Für die Zulassung zum Masterstudiengang Informatik benötigst du laut Eignungssatzung [Quelle 1]:\n\n1. **Bachelorabschluss** in Informatik oder einem verwandten Fach mit mindestens 180 ECTS (§ 2 Abs. 1 [Quelle 1]).\n2. **Notendurchschnitt**: In der Regel mindestens 2,5 oder besser (§ 3 [Quelle 1]).\n3. **Eignungsverfahren**: Ggf. ein Auswahlgespräch (§ 4 [Quelle 1]).\n\nDie genauen Anforderungen können je nach Studiengang variieren.",
        },
    ],
    "fallback": [
        {
            "q": "Wo finde ich Informationen zu Stipendien?",
            "a": "Dazu habe ich leider keine Information in den mir vorliegenden Dokumenten gefunden. Die PSTOs und Eignungssatzungen regeln Prüfungs- und Zulassungsfragen, aber keine Stipendien. Bitte wende dich an die **Zentrale Studienberatung** oder das **Stipendienreferat** der LMU.",
        },
    ],
}


def classify_query(query: str) -> str:
    for qtype, pattern in _QUERY_TYPES.items():
        if pattern.search(query):
            return qtype
    return "factual"


def get_few_shot_examples(query: str, max_examples: int = 2) -> list[dict]:
    """Select the most relevant few-shot examples for a query."""
    qtype = classify_query(query)
    examples = EXAMPLES.get(qtype, EXAMPLES["factual"])
    return examples[:max_examples]


def format_few_shot_block(examples: list[dict]) -> str:
    """Format few-shot examples for injection into the system prompt."""
    if not examples:
        return ""
    blocks = []
    for ex in examples:
        blocks.append(f"**Frage:** {ex['q']}\n**Antwort:** {ex['a']}")
    return "\n\n".join(blocks)
