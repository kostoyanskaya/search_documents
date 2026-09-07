# DocMind — AI Document Search Agent

DocMind is a full-featured RAG (Retrieval-Augmented Generation) application that helps users find the right document based on their queries or input data. The agent retrieves the most relevant excerpts, passes them to an LLM as grounded context, and returns a response along with precise citations from the sources it relies on—rather than letting the model guess or fabricate information. For example, DocMind allows users to upload up to 50 documents at once. The system will automatically find the relevant document among them, display its title, pinpoint exactly where the requested information is located within it, and provide a clear answer with the source attribution.


![DocMind screenshot](docs/screenshot.png)

## What it does

1. A user uploads one or more documents (`.pdf`, `.docx`, `.csv`, `.xlsx`, `.xls`).
2. The backend extracts the text, splits it into chunks, and embeds each chunk into a
   vector store.
3. The user types a question in plain language.
4. The backend retrieves the most semantically relevant chunks, passes them to an LLM
   with strict "answer only from this context" instructions, and returns a grounded
   answer.
5. Every answer is shown together with the source documents and excerpts it came from,
   so the user can verify it.

Each user only ever sees their own documents — data belonging to different users is
fully isolated, and nothing is ever written to disk (see [Privacy & Security](#privacy--security)
below).

## Tech stack

**Backend**
- [FastAPI](https://fastapi.tiangolo.com/) — async Python web framework
- [LangChain](https://www.langchain.com/) + [LangGraph](https://www.langchain.com/langgraph) — RAG pipeline orchestration (retrieve → generate graph)
- [ChromaDB](https://www.trychroma.com/) (ephemeral, in-memory client) — vector store
- [Sentence-Transformers](https://www.sbert.net/) (`intfloat/multilingual-e5-small`) — local, multilingual text embeddings
- DeepSeek / OpenAI-compatible Chat Completions API (via `langchain-openai`) — answer generation
- `pypdf`, `python-docx`, `pandas` + `openpyxl` — text extraction from PDF / DOCX / CSV / XLSX
- Pydantic + `pydantic-settings` — request/response validation and configuration

**Frontend**
- [React 18](https://react.dev/) + [TypeScript](https://www.typescriptlang.org/)
- [Vite](https://vitejs.dev/) — dev server and build tool
- Plain CSS (no UI framework) — custom design system
- `fetch` API with cookie-based session auth

## Architecture highlights

- **No accounts, no persistent storage.** Each browser gets an anonymous, unguessable
  session identifier in an `httpOnly` cookie. All documents, extracted text, and vector
  embeddings live only in the backend process's memory and are scoped to that session
  ID — they are never written to disk.
- **Automatic cleanup.** A background task purges any session that has been idle longer
  than a configurable TTL. Users can also wipe their own data instantly via a
  "Clear my data" button.
- **Non-blocking under concurrent users.** File processing and LLM calls run in a
  thread pool so that one user's request never blocks another user's request on the
  same server process.

## Project structure

```
search_documents/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app, CORS, background cleanup task
│   │   ├── core/
│   │   │   ├── config.py        # environment-based settings
│   │   │   └── session.py       # anonymous session cookie + TTL cleanup
│   │   ├── models/
│   │   │   └── schemas.py       # Pydantic request/response models
│   │   ├── services/
│   │   │   ├── document_registry.py  # in-memory document metadata store
│   │   │   ├── file_processing.py    # text extraction (PDF/DOCX/CSV/XLSX)
│   │   │   ├── vector_store.py       # ChromaDB (ephemeral) indexing & search
│   │   │   ├── llm.py                # LLM client factory
│   │   │   └── rag_agent.py          # LangGraph retrieve → generate pipeline
│   │   └── routers/
│   │       ├── documents.py     # upload / list / delete documents
│   │       ├── query.py         # ask a question
│   │       └── session.py       # clear all data for the current session
│   ├── requirements.txt
│   └── .env.example
└── frontend/
    ├── src/
    │   ├── api/client.ts         # typed fetch wrapper for the backend API
    │   ├── components/           # Icon, Sidebar, Workspace, AnswerModal, ...
    │   ├── hooks/                # useSimulatedProgress
    │   ├── types/                # shared TypeScript types
    │   └── App.tsx
    ├── package.json
    └── .env.example
```

## Prerequisites

- Python 3.10+
- Node.js 18+ and npm
- An API key for a Chat Completions-compatible LLM provider (DeepSeek or OpenAI)

## Getting started

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd search_documents
```

### 2. Backend setup

```bash
cd backend
python -m venv venv

# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# then open .env and set your LLM_API_KEY
```

Start the API server (single worker — required by the in-memory architecture, see
[Known limitations](#known-limitations)):

```bash
uvicorn app.main:app --reload --workers 1
```

The API is now available at `http://localhost:8000`. Interactive API docs are at
`http://localhost:8000/docs`.

### 3. Frontend setup

In a new terminal:

```bash
cd frontend
npm install

cp .env.example .env
# .env only needs VITE_API_URL, which already defaults to http://localhost:8000
```

```bash
npm run dev
```

Open `http://localhost:5173` in your browser.

### 4. Try it out

1. Upload a PDF, DOCX, CSV, or XLSX file from the sidebar.
2. Wait for its status to change to "Indexed".
3. Ask a question about its contents in the search box.

## Configuration reference (backend `.env`)

| Variable                    | Description                                             | Default                            |
|------------------------------|-----------------------------------------------------------|-------------------------------------|
| `LLM_PROVIDER`                | `deepseek` or `openai` (selects base URL + default model) | `deepseek`                          |
| `LLM_API_KEY`                 | API key for the chosen LLM provider                       | *(required)*                        |
| `LLM_MODEL`                   | Overrides the provider's default model                    | *(provider default)*                |
| `LLM_BASE_URL`                | Overrides the provider's default API base URL             | *(provider default)*                |
| `EMBEDDING_MODEL`             | Sentence-Transformers model used for embeddings            | `intfloat/multilingual-e5-small`    |
| `MAX_UPLOAD_MB`                | Max size per uploaded file, in MB                          | `200`                               |
| `MAX_FILES_PER_UPLOAD`        | Max number of files per upload request                     | `40`                                |
| `RETRIEVAL_TOP_K`             | Number of chunks retrieved per question                    | `8`                                  |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | Text splitting parameters                                  | `900` / `150`                       |
| `CORS_ORIGINS`                | Comma-separated list of allowed frontend origins            | `http://localhost:5173`             |
| `SESSION_TTL_HOURS`           | Hours of inactivity before a session is auto-deleted        | `4`                                  |
| `SESSION_COOKIE_SECURE`       | Set to `True` when serving over HTTPS in production          | `False`                              |
| `CLEANUP_INTERVAL_MINUTES`    | How often the background cleanup job runs                    | `15`                                 |

## API overview

| Method | Endpoint                     | Description                                   |
|--------|-------------------------------|------------------------------------------------|
| POST   | `/api/documents/upload`       | Upload one or more documents                    |
| GET    | `/api/documents`              | List the current session's documents            |
| DELETE | `/api/documents/{doc_id}`     | Delete a single document                        |
| POST   | `/api/query`                  | Ask a question about the indexed documents      |
| DELETE | `/api/session`                | Immediately wipe all data for the current session |
| GET    | `/api/health`                 | Health check                                    |

Full interactive documentation is auto-generated by FastAPI at `/docs`.

## Privacy & Security

- **Nothing touches the disk.** Uploaded files are read straight into memory, text is
  extracted from bytes (never written to a temp file), and both the document registry
  and the vector index are plain in-process data structures — not files or databases on
  disk.
- **Per-user isolation.** Every document, chunk, and vector is tagged with an opaque,
  cryptographically random session ID (`secrets.token_urlsafe(32)`) stored in an
  `httpOnly`, `SameSite=Lax` cookie. Every read/write is filtered by that ID, so one
  user can never see or delete another user's data.
- **Automatic expiry.** Idle sessions are purged by a background task after
  `SESSION_TTL_HOURS`. Restarting the backend process also clears all data immediately.

## Known limitations

- **Single-process only.** The in-memory design intentionally trades horizontal
  scalability for privacy: run the backend with `--workers 1` and a single instance.
  Scaling out would require moving session/document state to a shared store (e.g.
  Redis) and encrypting data at rest — a natural next step, not implemented here by
  design.
- **No true "delete on tab close".** Browsers do not reliably notify servers when a
  tab is closed, so data lifetime is bounded by the idle TTL and the explicit
  "Clear my data" action instead.
- **CPU-bound embedding step.** Because of Python's GIL, concurrent uploads share a
  single CPU core for the embedding step; heavy concurrent load will be processed
  correctly but sequentially in terms of raw CPU time.


## License

This project is a personal portfolio piece. All rights reserved — no license is
granted to copy, modify, redistribute, or reuse this code, in whole or in part,
without the author's explicit written permission.

This repository does not accept external contributions (pull requests, patches, or
added files). It is shared for review and demonstration purposes only.
