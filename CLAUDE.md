# campusLMU Chatbot PoC

## What this is
RAG chatbot for LMU student support — answers questions about Prüfungs- und Studienordnungen, Zulassungsordnungen, and Eignungsverfahren with source citations. Built for the campusLMU team as a PoC.

## Stack
- **Backend**: FastAPI (`backend/app/`) — Python, Azure OpenAI (gpt-4o + text-embedding-3-small), Azure AI Search
- **Frontend**: Next.js 16 + React 19 + Tailwind (`frontend/src/`) — chat UI with inline citation chips and citation drawer
- **Deployed on**: Azure App Service (both backend and frontend)
- **GitHub**: https://github.com/Smileodox/ECM

## Architecture
1. **Scraping** (offline): CMS Search API → program pages → PDF links → download to `documents/` + `manifest.json`
2. **Ingestion** (offline): PDF → PyMuPDF4LLM markdown → §-aware chunking (800 tok) → embeddings → Azure AI Search index (`campuslmu-regulations-v2`)
3. **Query** (runtime): User question → (English? translate to German) → hybrid search (vector + BM25 + semantic reranker) with doc_type/program_name filters → top 10 chunks → gpt-4o generates answer with `[Quelle N]` citations → SSE streaming to frontend

## Key directories
- `backend/app/scraper/` — fetcher.py (CMS Search API), downloader.py, classify.py, manifest.py
- `backend/app/ingestion/` — parser.py, chunker.py, indexer.py
- `backend/app/chat/` — engine.py, prompts.py, citations.py
- `backend/app/search/` — retriever.py (hybrid search with filtering & cross-lingual)
- `backend/app/routers/` — chat.py (SSE streaming), ingest.py
- `frontend/src/components/` — ChatWindow, MessageBubble, CitationChip, CitationDrawer
- `documents/` — 358 PDFs (198 PSTO, 90 Eignung, 68 Änderung, 2 Zulassung) + manifest.json

## Index schema (campuslmu-regulations-v2)
Key fields: `content`, `content_vector`, `doc_name`, `doc_filename`, `source_url`, `section_id`, `section_title`, `absatz`, `page_number`, `part`, `doc_type` (filterable), `program_name` (filterable+searchable)

## Dev commands
```bash
# Backend (always use uv, never pip)
cd backend && uv venv && uv pip install -r requirements.txt && uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm install && npm run dev

# Run scraper
cd backend && python -m app.scraper --resume

# Ingest documents (needs .env with Azure credentials)
curl -X POST http://localhost:8000/api/ingest
```

## What still needs to happen
- **Set up .env** with Azure credentials (lost in recovery incident 2026-05-21)
- **Run ingestion** against the new v2 index: `POST /api/ingest`
- **End-to-end testing** with German and English queries

## Conventions
- No Co-Authored-By in commits
- Keep commit messages short and minimal
- German UI, English code
- Only use `uv` for Python package management, never pip/venv directly
