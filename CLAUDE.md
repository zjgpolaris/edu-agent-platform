# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

EduAgent is a K-12 Chinese/history AI teaching platform. The current implementation is a two-service app:

- `backend/`: FastAPI API for history-character chat, essay grading, debate, and history games. Agent logic uses LangGraph-style state graphs plus RAG over a Chroma vector store.
- `frontend/`: Next.js 14 App Router UI for the learning center, history character chat, and history games.
- `knowledge_base/` and `textbooks/`: history corpus and structured textbook materials used by RAG/game generation.
- `scripts/` and `build_index.py`: one-off data ingestion/OCR/indexing utilities.
- `eval/`: smoke tests for agent behavior.

## Common commands

Run from the repository root unless noted.

```bash
# Install dependencies
pip install -r backend/requirements.txt
npm install --prefix frontend

# Start backend + frontend together
npm run dev

# Start services separately
npm run dev:backend
npm run dev:frontend

# Frontend
npm run build --prefix frontend
npm run lint --prefix frontend
npm run start --prefix frontend

# Rebuild history RAG vector index from knowledge_base/history/corpus.json
python3 build_index.py

# Convert structured textbook YAML into corpus/index inputs, then rebuild index
python3 scripts/parse_textbook.py
python3 build_index.py

# Agent smoke test
python3 eval/history_character_smoke.py

# Run one Python test/smoke file
python3 path/to/file.py
```

Notes:

- `scripts/dev.sh` loads `.env.local` from the project root, sets `PYTHONPATH=backend`, starts FastAPI on `http://localhost:8000`, and starts Next.js on `http://localhost:3000`.
- `npm run dev:backend` currently uses `/Users/cengjiguang/.local/python3.12/bin/python3`; override with `PYTHON_BIN=... npm run dev` for the combined script if needed.
- The frontend reads `NEXT_PUBLIC_API_BASE_URL` and defaults to `http://localhost:8000`.
- No pytest/Jest/Vitest config is currently present; use the smoke scripts and frontend build/lint commands as the available checks.

## Environment and LLM configuration

Backend LLM calls go through `backend/llm_config.py`, which invokes `backend/zode_client.js` as a Node helper. The helper supports:

- Anthropic-compatible requests using `ANTHROPIC_AUTH_TOKEN` or `ANTHROPIC_API_KEY`, with optional `ANTHROPIC_BASE_URL`.
- Bailian/DashScope OpenAI-compatible requests when `LLM_PROVIDER=bailian` or `LLM_PROVIDER=dashscope`, using `BAILIAN_API_KEY` or `DASHSCOPE_API_KEY` and optional `BAILIAN_BASE_URL`.

Model environment variables include `LLM_MODEL_FAST`, `LLM_MODEL_QUALITY`, `LLM_MODEL_FALLBACK`, `LLM_MODEL_REASONING`, plus Anthropic defaults `ANTHROPIC_MODEL_FAST`, `ANTHROPIC_MODEL_QUALITY`, `ANTHROPIC_MODEL_FALLBACK`, and `ANTHROPIC_MODEL_REASONING`.

## Backend architecture

`backend/api/main.py` is the FastAPI entry point. It defines request/response models, CORS, SSE framing, and routes under:

- `/api/history/character/*` for character recommendation and streaming/non-streaming character chat.
- `/api/history/games/*`, `/api/history/card-game/*`, and `/api/history/multiplayer/*` for history game flows.
- `/api/chinese/essay/grade` and `/api/history/debate/start` for prototype essay/debate agents.
- `/api/debug/llm/health` for checking model connectivity.

Agent modules live in `backend/agents/`. Important flows:

- `history_character.py`: retrieves facts from RAG, generates a first-person teaching simulation, verifies it with a quality model, and emits a fact-card. Streaming chat emits SSE events: `sources`, `delta`, `status`, `final`, and `fact_card`.
- `history_games.py`: owns game definitions and in-memory round records for timeline/card-game modes, delegating LLM generation to `timeline_question_generator.py` and `card_game.py`.
- `multiplayer_game.py` plus `multiplayer_*` helpers implement the “时间巨轮” multiplayer game and AI player behavior.
- `essay_grader.py` and `debate_supervisor.py` are graph-based prototype agents.

Session chat history is in `backend/session_store.py`. It prefers Redis on localhost if `redis` is importable, otherwise falls back to an in-memory store with a one-hour TTL.

## RAG and data flow

`backend/rag/knowledge_base.py` builds and loads Chroma collections from JSON corpus files. The history collection is built from `knowledge_base/history/corpus.json` into `.chroma` by `build_index.py`.

The embedding model path is hard-coded to `/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5` and runs on CPU. Query text is prefixed for BGE retrieval with `为这个句子生成表示以用于检索相关文章：`.

Textbook tooling:

- `textbooks/structured/*.yaml` contains manually structured history textbook data.
- `textbooks/structured/README.md` documents the YAML shape and the `python3 scripts/parse_textbook.py && python3 build_index.py` conversion flow.
- `scripts/ocr_pdf.py`, `parse_pdf_corpus.py`, `pdf_to_yaml.py`, and `generate_textbook_yaml.py` are ingestion helpers for raw PDFs/OCR.

## Frontend architecture

The frontend is a Next.js 14 App Router app in `frontend/app/` with TypeScript strict mode enabled.

- `app/page.tsx`: learning-center landing page.
- `app/history-character/page.tsx`: client-heavy character chat UI; it handles presets, recommendation, SSE streaming, source display, and verification status.
- `app/history-games/page.tsx` + `HistoryGamesClient.tsx`: game hall loaded from the backend.
- `app/history-games/timeline/`, `card-game/`, and `multiplayer/`: individual game experiences.
- `app/globals.css`: global styling for all pages.

The frontend mostly calls the backend directly with `fetch` using `NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000"`. For UI work, run the app and verify the relevant page manually in the browser, especially streaming chat/game state transitions.

## Documentation conventions

Development docs under `docs/` use timestamp-prefixed kebab-case filenames such as `202606081425-textbook-reader-highlight-notes-dev.md`. Preserve that convention when creating new docs in `docs/`.

## Schema documentation

`SCHEMA.md` in the project root documents the complete project structure, API endpoints, data models, and core features. **When adding or modifying features, you must update `SCHEMA.md` to keep it synchronized with the codebase.**

Update checklist:
- Update directory structure if new files/folders are added
- Update API endpoint list if new routes are added
- Update data models if database schemas change
- Update core features section if new functionality is added
- Update test list if new smoke tests are added
