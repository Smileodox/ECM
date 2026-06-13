"""Liveness check for every escalation / referral URL the bot can emit.

These URLs are hard-coded in app.chat.escalation; LMU restructures faculty pages over
time, so a dead link is silently served to a student exactly when they need the contact.
This smoke test catches hard breakage (404 / 5xx / dead host / soft-404 landing pages).

Run from backend/:  PYTHONPATH=. python -m eval.check_links
Exit code: 0 if all OK (403 = warning, treated as pass since LMU bot-blocks some pages).

CAVEAT: a server 200 here does NOT guarantee the page renders in a real browser
(CDNs can geo-block or require JS). This catches the common rot, not every failure mode.
"""

import sys

import httpx

from app.chat.escalation import (
    ESCALATION_CONTACTS,
    _FACULTY_FSB_URLS,
    _FACULTY_PRUEFUNGSAMT_URLS,
    _FSB_OVERVIEW_URL,
    _PRUEFUNGSAMT_OVERVIEW_URL,
)

_SOFT_404 = ("seite nicht gefunden", "page not found", "wurde nicht gefunden", "fehler 404", "error 404")
_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; campusLMU-linkcheck/1.0)"}


def collect_urls() -> list[str]:
    urls: set[str] = set()
    for c in ESCALATION_CONTACTS.values():
        urls.add(c["url"])
        urls.add(c["url_en"])
    urls.update(_FACULTY_FSB_URLS)
    urls.update(_FACULTY_PRUEFUNGSAMT_URLS)
    urls.add(_FSB_OVERVIEW_URL)
    urls.add(_PRUEFUNGSAMT_OVERVIEW_URL)
    return sorted(urls)


def check(client: httpx.Client, url: str) -> tuple[str, str]:
    try:
        r = client.get(url, follow_redirects=True, timeout=20.0)
    except Exception as e:  # noqa: BLE001 — report any transport failure as a dead link
        return "FAIL", f"request error: {e.__class__.__name__}"
    if r.status_code == 403:
        return "WARN", "403 (likely bot-block — verify in a browser)"
    if r.status_code != 200:
        return "FAIL", f"HTTP {r.status_code}"
    head = r.text[:3000].lower()
    hit = next((m for m in _SOFT_404 if m in head), None)
    if hit:
        return "FAIL", f"soft-404 marker {hit!r} (status 200 but error page)"
    return "OK", "200"


def main() -> int:
    urls = collect_urls()
    fails = warns = 0
    with httpx.Client(headers=_HEADERS) as client:
        for url in urls:
            status, detail = check(client, url)
            if status == "FAIL":
                fails += 1
            elif status == "WARN":
                warns += 1
            print(f"[{status:<4}] {detail:<42} {url}")
    print(f"\n{len(urls)} URLs checked: {len(urls) - fails - warns} ok, {warns} warn, {fails} fail")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
