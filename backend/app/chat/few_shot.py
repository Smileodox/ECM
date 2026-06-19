"""Dynamic few-shot example selection based on query type."""

import re

_QUERY_TYPES = {
    "amendment": re.compile(
        r"(?:änderung|geändert|aktualisiert|neufassung|übergangs|alte.+neue|"
        r"änderungssatzung|was hat sich geändert|seit wann gilt|neue fassung|"
        r"amendment|updated|revised|revision)",
        re.IGNORECASE,
    ),
    "eligibility": re.compile(
        r"(?:eignung|eignungsverfahren|eignungssatzung|eignungsprüfung|"
        r"zulassung|zulassungsvoraussetzung|zulassungsbedingung|zulassungsordnung|"
        r"voraussetzung|aufnahmevoraussetzung|zugangsvoraussetzung|"
        r"anforderung|bewerb|aufnahme|"
        r"aptitude|admission|requirement|prerequisite|qualification|eligible|"
        r"wie komme ich rein|kann ich mich bewerben|bin ich zugelassen)",
        re.IGNORECASE,
    ),
    "administrative": re.compile(
        r"(?:rückmeldung|exmatrikulation|exmatrikulieren|immatrikulation|"
        r"adressänderung|adresse ändern|beurlaubung|krankenversicherung|"
        r"semesterbeitrag|beiträge|gebühren|semesterticket|lmucard|"
        r"bescheinigung|online.?selbstbedienung|datenschutz|"
        r"re.?register|re.?enroll|health insurance|semester ticket)",
        re.IGNORECASE,
    ),
    "deadline": re.compile(
        r"(?:frist(?:en)?|deadline|termin|bis wann|ab wann|"
        r"semestertermin|vorlesungszeit|vorlesungsbeginn|semesterende|"
        r"when is|when does|when do i need)",
        re.IGNORECASE,
    ),
    "contact": re.compile(
        r"(?:wo (?:finde|ist|kann)|kontakt|ansprech(?:partner|person|partnerin)|"
        r"an wen|anlaufstelle|studienberatung|prüfungsamt|studentenkanzlei|"
        r"where can i|who do i|who can i|whom|contact person)",
        re.IGNORECASE,
    ),
    "process": re.compile(
        r"(?:wie melde|wie bewerbe|wie kann ich|was muss ich|anmeldung|ablauf|"
        r"schritt|verfahren|beantragen|einreichen|anrechnung|frist|deadline|"
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
    "administrative": [
        {
            "q": "Wie melde ich mich fürs nächste Semester rück?",
            "a": "Die Rückmeldung erfolgt durch Überweisung des Semesterbeitrags auf das Konto der LMU [Quelle 1]:\n\n1. **Betrag überweisen**: Aktuell 97,00 € an den Freistaat Bayern.\n2. **Matrikelnummer angeben**: Deine Matrikelnummer muss im Verwendungszweck stehen.\n3. **Frist beachten**: Die Rückmeldung muss bis zum angegebenen Stichtag erfolgen.\n4. **LMUcard validieren** nach erfolgreicher Rückmeldung.\n\nBei verspäteter Rückmeldung droht die Exmatrikulation [Quelle 1].",
        },
    ],
    "deadline": [
        {
            "q": "Bis wann muss ich mich rückmelden?",
            "a": "Die Rückmeldefrist für das Sommersemester endet in der Regel Anfang Februar, für das Wintersemester Ende Juli [Quelle 1]. Den genauen Stichtag findest du auf der LMU-Seite zu Terminen für Studierende oder in deinem persönlichen Beitragskonto online.",
        },
    ],
    "contact": [
        {
            "q": "Wo bekomme ich eine Immatrikulationsbescheinigung?",
            "a": "Immatrikulationsbescheinigungen kannst du über die **Online-Selbstbedienungsfunktionen** der LMU selbst herunterladen und ausdrucken [Quelle 1]. Für amtliche Bescheinigungen mit Siegel wende dich an die **Studentenkanzlei** (Geschwister-Scholl-Platz 1) [Quelle 2].",
        },
    ],
    "fallback": [
        {
            "q": "Wo finde ich Informationen zu Stipendien?",
            "a": "Informationen zu Stipendien und Studienfinanzierung findest du auf der LMU-Seite zu Studienfinanzierung [Quelle 1]. Für eine persönliche Beratung kannst du dich an die **Zentrale Studienberatung** oder das **Stipendienreferat** der LMU wenden.",
        },
    ],
}


EXAMPLES_EN = {
    "factual": [
        {
            "q": "How many ECTS credits does the master thesis in Computer Science have?",
            "a": "The master thesis (Masterarbeit) in the Computer Science (Informatik) master's program is worth **30 ECTS credits** according to § 14 Abs. 1 [Quelle 1]. The processing time (Bearbeitungszeit) is six months (§ 14 Abs. 3 [Quelle 1]).",
        },
        {
            "q": "What is the standard duration of the BWL master's program?",
            "a": "The standard duration of study (Regelstudienzeit) for the Business Administration (Betriebswirtschaftslehre) master's program is **four semesters** (§ 5 Abs. 1 [Quelle 1]), totaling 120 ECTS credits.",
        },
    ],
    "process": [
        {
            "q": "How do I register for my master thesis?",
            "a": "To register for your master thesis (Masterarbeit), follow these steps:\n\n1. **Find a topic and supervisor**: Choose an eligible supervisor (prüfungsberechtigter Betreuer) according to § 14 Abs. 2 [Quelle 1].\n2. **Register at the examination office (Prüfungsamt)**: Submit the completed registration form together with the supervision confirmation (§ 14 Abs. 4 [Quelle 1]).\n3. **Processing period**: You have six months from registration (§ 14 Abs. 3 [Quelle 1]).\n\nFor detailed procedural questions, contact your [examination office (Prüfungsamt)](https://www.lmu.de/de/studium/wichtige-kontakte/pruefungsaemter/).",
        },
        {
            "q": "How does the credit transfer process work?",
            "a": "Credit transfer (Anrechnung) for external coursework is governed by § 4 [Quelle 1]:\n\n1. **Submit an application** to the examination board (Prüfungsausschuss) with documentation of the completed coursework.\n2. **Equivalence review**: The board assesses whether content, scope, and requirements are equivalent (§ 4 Abs. 1 [Quelle 1]).\n3. **Decision**: The decision is typically made within four weeks.\n\nFor details, I recommend scheduling an appointment at your [examination office (Prüfungsamt)](https://www.lmu.de/de/studium/wichtige-kontakte/pruefungsaemter/).",
        },
    ],
    "comparison": [
        {
            "q": "What is the difference between mandatory and elective modules?",
            "a": "The key difference:\n\n- **Mandatory modules (Pflichtmodule)** (§ 6 [Quelle 1]): Must be completed by all students. They form the core of the program.\n- **Elective modules (Wahlpflichtmodule)** (§ 7 [Quelle 2]): You choose from a predefined catalog. The minimum ECTS from elective modules is specified in the PSTO.\n\nBoth count equally toward your final grade and total ECTS credits.",
        },
    ],
    "amendment": [
        {
            "q": "Was § 5 of the Computer Science PSTO amended?",
            "a": "Yes, § 5 was amended by the amendment statute (Änderungssatzung) of 15 March 2024 [Quelle 2]. The change affects the standard duration of study (Regelstudienzeit), which was reduced from 4 to 3 semesters (§ 5 Abs. 1 [Quelle 2]). All other paragraphs of the original 2017 PSTO [Quelle 1] remain unchanged.",
        },
    ],
    "eligibility": [
        {
            "q": "What are the requirements for the Computer Science master's program?",
            "a": "According to the aptitude regulations (Eignungssatzung) [Quelle 1], you need:\n\n1. **Bachelor's degree** in Computer Science or a related field with at least 180 ECTS (§ 2 Abs. 1 [Quelle 1]).\n2. **Grade average**: Typically 2.5 or better (§ 3 [Quelle 1]).\n3. **Aptitude assessment** (Eignungsverfahren): Possibly an interview (§ 4 [Quelle 1]).\n\nExact requirements may vary by program.",
        },
    ],
    "administrative": [
        {
            "q": "How do I re-register for the next semester?",
            "a": "Re-registration (Rückmeldung) is done by transferring the semester fee to the LMU account [Quelle 1]:\n\n1. **Transfer the amount**: Currently €97.00 to Freistaat Bayern.\n2. **Include your student ID number** (Matrikelnummer) in the transfer reference.\n3. **Meet the deadline**: Re-registration must be completed by the specified date.\n4. **Validate your LMUcard** after successful re-registration.\n\nLate re-registration may result in exmatriculation (Exmatrikulation) [Quelle 1].",
        },
    ],
    "deadline": [
        {
            "q": "When is the re-registration deadline?",
            "a": "The re-registration deadline (Rückmeldefrist) for the summer semester is typically early February, and for the winter semester late July [Quelle 1]. You can find the exact date on the LMU page for student deadlines (Semestertermine) or in your personal fee account online.",
        },
    ],
    "contact": [
        {
            "q": "Where can I get a certificate of enrollment?",
            "a": "You can download and print certificates of enrollment (Immatrikulationsbescheinigungen) via the LMU **online self-service portal** (Online-Selbstbedienung) [Quelle 1]. For officially stamped certificates, contact the [Student Office (Studentenkanzlei)](https://www.lmu.de/de/studium/wichtige-kontakte/studentenkanzlei/) at Geschwister-Scholl-Platz 1 [Quelle 2].",
        },
    ],
    "fallback": [
        {
            "q": "Where can I find information about scholarships?",
            "a": "Information about scholarships and study financing (Studienfinanzierung) is available on the LMU page for study financing [Quelle 1]. For personal advice, you can contact the [Central Student Advisory Services (Zentrale Studienberatung)](https://www.lmu.de/de/studium/wichtige-kontakte/zentrale-studienberatung/).",
        },
    ],
}


def classify_query(query: str) -> str:
    matched = [qtype for qtype, pattern in _QUERY_TYPES.items() if pattern.search(query)]
    # If amendment AND eligibility both match, the query spans both doc types —
    # don't restrict by either (fall back to unfiltered "factual" search)
    if "amendment" in matched and "eligibility" in matched:
        return "factual"
    return matched[0] if matched else "factual"


def get_few_shot_examples(query: str, max_examples: int = 2, lang: str = "de") -> list[dict]:
    """Select the most relevant few-shot examples for a query."""
    qtype = classify_query(query)
    source = EXAMPLES_EN if lang == "en" else EXAMPLES
    examples = source.get(qtype, source["factual"])
    return examples[:max_examples]


def format_few_shot_block(examples: list[dict], lang: str = "de") -> str:
    """Format few-shot examples for injection into the system prompt."""
    if not examples:
        return ""
    q_label = "Question" if lang == "en" else "Frage"
    a_label = "Answer" if lang == "en" else "Antwort"
    blocks = []
    for ex in examples:
        blocks.append(f"**{q_label}:** {ex['q']}\n**{a_label}:** {ex['a']}")
    return "\n\n".join(blocks)
