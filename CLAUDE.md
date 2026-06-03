# campusLMU Chatbot PoC

## What this is
RAG chatbot for LMU student support — answers questions about study regulations (PSTOs, Eignungssatzungen, Zulassungsordnungen) AND general student topics from the LMU "1x1 des Studiums" (fees, enrollment, deadlines, campus services, etc.). Built for the campusLMU team as a PoC.

## Stack
- **Backend**: FastAPI (`backend/app/`) — Python, Azure OpenAI (gpt-5.4 main + gpt-5.4-nano utility + text-embedding-3-small), Azure AI Search, Azure Cache for Redis
- **Frontend**: Next.js 16 + React 19 + Tailwind (`frontend/src/`) — chat UI with inline citation chips and citation drawer
- **Deployed on**: Azure App Service (both backend and frontend)
- **GitHub**: https://github.com/Smileodox/ECM

## Architecture (dual-index)
1. **Regulation pipeline** (offline): CMS Search API → program pages → PDF links → download to `documents/` + `manifest.json` → PyMuPDF4LLM markdown → §-aware chunking (800 tok) → embeddings → Azure AI Search index (`campuslmu-regulations-v2`)
2. **Web pipeline** (offline): LMU 1x1 index page → depth-2 crawl of ~220 sub-pages → markdownify → H2/H3-aware chunking → embeddings → Azure AI Search index (`campuslmu-web-v1`)
3. **Query** (runtime): User question → query router (REGULATION/GENERAL/BOTH) → search appropriate index(es) → RRF fusion → layered system prompt → gpt-5.4 generates answer with `[Quelle N]` citations → SSE streaming to frontend

## Key directories
- `backend/app/scraper/` — fetcher.py (CMS Search API), web_scraper.py (1x1 HTML pages), downloader.py, classify.py, manifest.py
- `backend/app/ingestion/` — parser.py, chunker.py (§-aware), web_chunker.py (H2/H3-aware), indexer.py (both indices)
- `backend/app/chat/` — engine.py, prompts.py (layered prompt), citations.py, few_shot.py
- `backend/app/search/` — retriever.py (regulation + web retrieval), router.py (query classification), version_registry.py
- `backend/app/routers/` — chat.py (SSE streaming), ingest.py
- `frontend/src/components/` — ChatWindow, MessageBubble, CitationChip (regulation + web styles), CitationDrawer
- `documents/` — 360 PDFs (198 PSTO, 91 Eignung, 68 Änderung, 2 Zulassung) + manifest.json
- `backend/data/` — web_manifest.json (scraped 1x1 pages)

## Index schemas
- **campuslmu-regulations-v2**: `content`, `content_vector`, `doc_name`, `doc_filename`, `source_url`, `section_id`, `section_title`, `absatz`, `page_number`, `part`, `doc_type` (filterable), `program_name` (filterable+searchable)
- **campuslmu-web-v1**: `content`, `content_vector`, `doc_name`, `source_url`, `section_title`, `chunk_index`, `doc_type`, `topic_slug` (filterable+facetable)

## Dev commands
```bash
# Backend (always use uv, never pip)
cd backend && uv venv && uv pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Run regulation scraper
cd backend && python -m app.scraper --resume

# Run web scraper (1x1 pages, depth-2)
cd backend && python -m app.scraper.web_scraper_cli

# Ingest documents (needs .env with Azure credentials)
curl -X POST http://localhost:8000/api/ingest
```

## What still needs to happen
- **Web content ingestion endpoint** — like /api/ingest but for web chunks → campuslmu-web-v1 index
- **Azure Managed Identity** — replace admin API keys with managed identity
- **Application Insights / APM** — latency tracking, error monitoring
- **CI/CD secrets** — GitHub Actions workflow exists, needs Azure credentials
- **Load testing** with realistic concurrent user load

## Conventions
- No Co-Authored-By in commits
- Keep commit messages short and minimal
- English UI, English code
- Only use `uv` for Python package management, never pip/venv directly
