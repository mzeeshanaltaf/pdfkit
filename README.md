# PDFKit

A self-hosted, iLovePDF-style web app with 12 PDF tools. Pick files → configure in
the right sidebar → one big button → download. No accounts, no stored files:
everything is per-request and ephemeral.

Five tools run entirely in the browser (nothing is uploaded); the rest go to a small
FastAPI service that shells out to Ghostscript, qpdf, Tesseract, pdf2docx and anydoc.
Compress also carries two passes of its own, because Ghostscript can do neither: a
font subsetter (a Word document with one emoji in it embeds several megabytes of
unused font) and a content-stream rewriter (pdfwrite makes a vector PDF *bigger*).

| Runs in the browser | Runs on the backend |
|---|---|
| Merge, Split, Rotate, Organize, Page Numbers | Compress, OCR, Protect, Unlock, PDF→Word, PDF→Markdown |

PDF→JPG is the mixed case: page rendering happens in the browser, while extracting the
images already embedded in a document uses the backend.

OCR ships 14 Tesseract models — Arabic, Chinese (Simplified), Dutch, English, French,
German, Hindi, Italian, Japanese, Portuguese, Russian, Spanish, Swedish, Urdu — and up to
three can be combined on one document. Adding a fifteenth is one `tesseract-ocr-<code>`
line in `backend/Dockerfile` (plus a `LANGUAGE_NAMES` entry so it shows a real name
instead of its code); the picker reads `GET /ocr/languages`, so no frontend change. Each
model costs roughly 0.5-6 MB of image size.

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
| `MAX_OCR_LANGUAGES` | backend | `3` | Most languages one OCR request may combine; the picker mirrors this number |
| `MAX_CONCURRENT_JOBS` | backend | `2` | Concurrent heavy jobs — subprocesses (Ghostscript/qpdf/OCR) and compression's in-process stream rewrite share the limit |
| `JOB_TIMEOUT_SECONDS` | backend | `180` | Wall-clock ceiling for one job; per-operation overrides exist, e.g. `OCR_TIMEOUT_SECONDS` (600), `WORD_TIMEOUT_SECONDS` (300), `MARKDOWN_TIMEOUT_SECONDS` (120) |
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
