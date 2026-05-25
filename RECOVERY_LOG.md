# chatbot_poc Recovery — 2026-05-21

## Was passiert ist
- `chatbot_poc` sollte von `~/Documents/LMU/MMT/Semester-2/ECM/` nach `~/localdocs/lmu/ecm/` verschoben werden
- Claude Code Sandbox hat den Copy nach außen blockiert, aber den `rm -rf` innerhalb des Working Directory durchgelassen → Daten weg

## Recovery
- Backend + Frontend über Azure Kudu API (`api/zip/site/wwwroot/`) von **Vehicle Aftermarket Subscription** (`381a8ac7`) runtergeladen
- Resource Group: `rg-chatbot-poc`, Apps: `app-chatbot-backend`, `app-chatbot-frontend`
- PIM-Elevation auf Contributor war nötig (Reader reicht nicht für Kudu)
- Backend kam als `output.tar.zst` (Oryx Build), Frontend direkt als Source

## Was recovered wurde
- **Backend**: FastAPI app — chat engine, ingestion pipeline, search retriever, routers (`app/`)
- **Frontend**: Next.js/TS — Chat UI mit Citations, Streaming (`src/`)
- Alles gepusht auf https://github.com/Smileodox/ECM

## Was NICHT recovered wurde
- `documents/` Ordner (262 Einträge) — war lokal, nicht deployed
- `.claude/` Projektconfig
- `.env` / lokale Secrets
- Git History (war kein Repo vorher)
