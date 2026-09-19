# PDFKit

A self-hosted, iLovePDF-style web app with 10 PDF tools. Pick files → configure in
the right sidebar → one big button → download. No accounts, no stored files:
everything is per-request and ephemeral.

Six tools run entirely in the browser (nothing is uploaded); the rest go to a small
FastAPI service that shells out to Ghostscript, qpdf and Tesseract — plus, for
compression, a content-stream rewriter of its own, since Ghostscript makes a
vector-heavy PDF *bigger* rather than smaller.

| Runs in the browser | Runs on the backend |
|---|---|
| Merge, Split, Rotate, Organize, Page Numbers, PDF→JPG (page mode) | Compress, OCR, Protect, Unlock, PDF→JPG (extract-images mode) |

## Repository layout

```
frontend/   Next.js 16 app (App Router, TypeScript, Tailwind v4, shadcn/ui)
backend/    FastAPI app, managed with uv
docs/       PLAN.md (reference) and phases/ (the actual task breakdown)
STATUS.md   current progress — read this first
```

## Requirements

- Node 24 (Node 22 in the Docker image)
- Docker Desktop — the backend depends on Ghostscript/qpdf/Tesseract, so it always
  runs in a container, in dev as well as prod
- `uv` (only needed to edit backend dependencies or run its tests on the host)

## Local development

Frontend, on the host with hot reload:

```bash
cd frontend
npm install          # postinstall copies pdf.worker.min.mjs into public/
npm run dev          # http://localhost:3000
```

Backend, in Docker:

```bash
docker compose up backend        # http://localhost:8000
curl localhost:8000/health       # {"status":"ok"}
```

Both services together, as they run in production:

```bash
docker compose up --build
```

Backend tests (dependency resolution only — the native binaries live in the image):

```bash
cd backend && uv run pytest
```

## Environment variables

Copy `.env.example` to `.env` at the repo root for compose, and
`frontend/.env.example` to `frontend/.env.local` for `npm run dev`.

| Variable | Service | Default | Notes |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | frontend | `http://localhost:8000` | Baked in at **build** time — the Docker image must be rebuilt to change it |
| `CORS_ORIGINS` | backend | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated list of allowed origins |
| `MAX_UPLOAD_MB` | backend | `50` | Per-file cap; the frontend enforces the same number client-side |
| `MAX_CONCURRENT_JOBS` | backend | `2` | Concurrent heavy jobs — subprocesses (Ghostscript/qpdf/OCR) and compression's in-process stream rewrite share the limit |
| `JOB_TIMEOUT_SECONDS` | backend | `180` | Wall-clock ceiling for one job |
| `WORK_DIR` | backend | `/tmp/pdfkit` | Scratch space, mounted as tmpfs in compose |

## Deployment

Target is Coolify on the Hostinger VPS (`zeeshanai.cloud`), deployed as a single
**Docker Compose** resource built from this `docker-compose.yml`:

- `pdfkit.zeeshanai.cloud` → `frontend` (port 3000)
- `api.pdfkit.zeeshanai.cloud` → `backend` (port 8000)

Set `NEXT_PUBLIC_API_URL=https://api.pdfkit.zeeshanai.cloud` as a **build** argument
and `CORS_ORIGINS=https://pdfkit.zeeshanai.cloud` as a backend runtime variable.
Traefik's default request body limit needs raising to clear the 50 MB upload cap.

Full deploy steps are written up in Phase 7 (`docs/phases/`).
