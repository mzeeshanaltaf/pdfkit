# Phase 0 — Scaffold

## Goal
Empty-but-runnable skeleton: git repo, Next.js frontend, FastAPI backend, docker-compose, README. Nothing tool-specific yet.

## Tasks
1. `git init` at repo root. Add `.gitignore` covering `node_modules`, `.next`, `__pycache__`, `.venv`, `*.pyc`, `.env*`, `/backend/.venv`.
2. Frontend scaffold:
   - `npx create-next-app@latest frontend` — TypeScript, Tailwind, App Router, `src/` dir **off**, `@/*` import alias.
   - `npx shadcn@latest init` inside `frontend/`.
   - Add shadcn components: button, card, input, select, checkbox, radio-group, dialog, tooltip, badge, separator, tabs, dropdown-menu, progress, sonner, label, switch, popover.
   - Install deps: `pdf-lib`, `pdfjs-dist`, `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`, `jszip`, `react-dropzone`, `lucide-react`, `file-saver`.
   - `next.config.ts`: `output: "standalone"`.
   - Postinstall script to copy `pdfjs-dist/build/pdf.worker.min.mjs` → `public/pdf.worker.min.mjs`.
   - `.env.local`: `NEXT_PUBLIC_API_URL=http://localhost:8000`.
3. Backend scaffold:
   - `uv init backend`, Python 3.12.
   - Deps: `fastapi`, `uvicorn[standard]`, `python-multipart`, `ocrmypdf`, `pillow`, `pypdf`; dev: `pytest`, `httpx`.
   - Minimal `app/main.py` with CORS middleware (`CORS_ORIGINS` env) and `GET /health` → `{status: ok}`.
   - `app/config.py` stub: `MAX_UPLOAD_MB=50`, `MAX_CONCURRENT_JOBS=2`, `CORS_ORIGINS`.
4. Dockerfiles:
   - `frontend/Dockerfile` — multi-stage Node 22 alpine, `ARG NEXT_PUBLIC_API_URL`, `next build`, runs standalone server on 3000.
   - `backend/Dockerfile` — `python:3.12-slim-bookworm`, installs `ghostscript qpdf tesseract-ocr tesseract-ocr-eng poppler-utils`, installs deps via `uv`, non-root user, `/tmp/pdfkit` work dir, `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1`.
5. `docker-compose.yml` at root: `frontend` (3000), `backend` (8000).
6. Root `README.md`: local dev instructions, env vars, deploy notes (stub, fill in more during Phase 7).

## Out of scope
No tool logic, no shared UI components beyond what create-next-app/shadcn generate.

## Verification
- `docker compose build` succeeds for both services.
- `docker compose up backend` then `curl localhost:8000/health` → `{"status":"ok"}`.
- `cd frontend && npm run dev` — default Next.js page loads at localhost:3000.
- `git status` shows a clean, sensible tree (no `node_modules`/`.venv` tracked).

## Definition of done
Both apps build and run independently; repo is committed; `STATUS.md` updated to Phase 0 complete.
