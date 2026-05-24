import re


_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("aenderung", re.compile(
        r"[äa]nderung\s+der\s+(studien|pr[üu]fungs)|[äa]nderungssatzung|[äa]nderungsordnung",
        re.IGNORECASE,
    )),
    ("psto", re.compile(
        r"pr[üu]fungs-?\s*(und\s*)?studienordnung|pr[üu]fungsordnung|studienordnung|\bpsto\b",
        re.IGNORECASE,
    )),
    ("eignung", re.compile(
        r"eignungssatzung|eignungsverfahren|eignungsfeststellung|eingangsqualifikation",
        re.IGNORECASE,
    )),
    ("zulassung", re.compile(
        r"zulassungsordnung|zulassungssatzung|qualifikation.{0,20}zulassung|zulassung.{0,30}master",
        re.IGNORECASE,
    )),
]


def classify_doc_type(link_text: str, url: str) -> str:
    for doc_type, pattern in _PATTERNS:
        if pattern.search(link_text) or pattern.search(url):
            return doc_type
    return "other"
