# PDFKit — Phase 1 Plan (iLovePDF clone, 10 tools)

## Context

Greenfield project in `E:\Projects\Claude Code\2_Tools\PDFToolkit` (currently only the `iLovePDF/` screenshot folder). Goal: a self-hosted web app offering ten PDF tools with a workflow modelled on iLovePDF (pick files → configure in a right sidebar → big CTA → download). UI takes inspiration from the screenshots but does not copy them.

Decisions already made with the user:

| Decision | Choice |
|---|---|
| Stack | Next.js (App Router, TS, Tailwind, shadcn/ui) frontend + separate Python FastAPI backend |
| Processing | Hybrid: Merge, Split, Rotate, Organize, Page Numbers, PDF→JPG (page mode) in the browser; Compress, OCR, Protect, Unlock, PDF→JPG (extract-images mode) on the backend |
| Deployment | Coolify on Hostinger VPS, Docker (two services) |
| Scope extras | Landing page with tool grid. No accounts, no stored files. |
| OCR languages | English only (UI built to accept a list from the backend so more can be added later) |
| Upload limit | 50 MB per file for backend tools |
| App name | **PDFKit** (single constant, easy to change) |

Local machine has Node 24, Python 3.12, uv, Docker. Ghostscript/qpdf are NOT installed locally, so the backend always runs via Docker (locally and in prod).

---

## Repository layout

```
PDFToolkit/
├── frontend/                 Next.js 15 app
├── backend/                  FastAPI app (uv-managed)
├── docker-compose.yml        local dev + Coolify "Docker Compose" resource
├── iLovePDF/                 reference screenshots (keep)
├── .gitignore, README.md
```

Initialise a git repo at the root (single repo, two Dockerfiles).

---

## Frontend (`frontend/`)

### Setup
- `npx create-next-app@latest frontend` (TS, Tailwind, App Router, src dir off, `@/*` alias), then `npx shadcn@latest init`.
- shadcn components: button, card, input, select, checkbox, radio-group, dialog, tooltip, badge, separator, tabs, dropdown-menu, progress, sonner (toasts), label, switch, popover.
- Dependencies: `pdf-lib`, `pdfjs-dist`, `@dnd-kit/core`, `@dnd-kit/sortable`, `@dnd-kit/utilities`, `jszip`, `react-dropzone`, `lucide-react`, `file-saver` (or a small download helper).
- `next.config.ts`: `output: "standalone"`. Postinstall script copies `pdfjs-dist/build/pdf.worker.min.mjs` to `public/pdf.worker.min.mjs`; set `GlobalWorkerOptions.workerSrc = "/pdf.worker.min.mjs"`.
- All tool workspaces are loaded with `next/dynamic` + `{ ssr: false }` (per global CLAUDE.md hydration rule; they use `crypto.randomUUID()`, canvas, File objects).
- Env: `NEXT_PUBLIC_API_URL` (build-time; `http://localhost:8000` in dev).

### Routes
| Route | Tool | Files | Runs |
|---|---|---|---|
| `/` | Landing: hero + 10 tool cards | | |
| `/merge-pdf` | Merge | many | browser |
| `/split-pdf` | Split | one | browser |
| `/compress-pdf` | Compress | many | backend |
| `/pdf-to-jpg` | PDF → JPG | many | browser (pages) / backend (extract images) |
| `/organize-pdf` | Organize | many | browser |
| `/rotate-pdf` | Rotate | many | browser |
| `/add-page-numbers` | Page Numbers | many | browser |
| `/protect-pdf` | Protect | many | backend |
| `/unlock-pdf` | Unlock | many | backend |
| `/ocr-pdf` | OCR | many | backend |

`lib/tools.ts` is the single registry: `{ id, slug, name, tagline, description, icon, accent, multiple, ctaLabel }`. Landing grid, header nav, per-page `generateMetadata`, and the "continue to another tool" list on the result screen all read from it.

### Shared workspace components (`components/tool/`)
- `ToolShell.tsx` — state machine `select → configure → processing → done | error`. Owns the file list (`{ id, file, name, size, pageCount, thumbnail, rotation, error }`), add/remove, and the CTA. Renders the three-column layout from the screenshots: main canvas (file/page grid) + fixed-width right sidebar (title, options, CTA button pinned to bottom). Responsive: sidebar stacks below the grid under `lg`.
- `FileDropzone.tsx` — full-page "Select PDF files" + drag-and-drop (react-dropzone), enforces `.pdf`, multiplicity, and 50 MB for backend tools.
- `FileGrid.tsx` / `FileCard.tsx` — sortable (dnd-kit) file cards with first-page thumbnail, name, size, remove button, optional per-card action overlay (rotate icon for Rotate tool).
- `PageGrid.tsx` / `PageCard.tsx` — page thumbnails (for Organize, Split preview, Page Numbers preview); sortable; hover actions (rotate, delete); lazy-render thumbnails via IntersectionObserver for large docs.
- `AddFilesButton.tsx` — floating "+" with count badge, `SortButton.tsx` (A→Z / Z→A).
- `OptionsSidebar.tsx` — title, info callout, children, CTA.
- `ProcessingView.tsx` — upload progress bar (XHR) then indeterminate "Processing…".
- `ResultView.tsx` — download button, size before/after where relevant, "Start over", "Continue to: …" tool links.
- Encrypted-PDF guard: when `pdf-lib`/`pdf.js` throws a password error on a browser-side tool, show "This PDF is password protected" with a link to `/unlock-pdf`.

### Browser-side PDF engines (`lib/pdf/`)
- `load.ts` — load `File` → `PDFDocument` (pdf-lib) and `PDFDocumentProxy` (pdf.js); detects encryption.
- `thumbnails.ts` — render page N to a small JPEG data URL via pdf.js canvas; cached per file+page+rotation.
- `merge.ts` — `PDFDocument.create()`, `copyPages` in user order.
- `split.ts` — inputs: `{ mode: "ranges" | "fixed" | "pages", ranges: [{from,to}], every: N, pages: "1,3-5", mergeOutput: boolean }`. Produces one PDF or a ZIP (jszip). Includes a range-expression parser (`"1,3-5,8"`) with validation against page count.
- `rotate.ts` — apply delta (90/180/270) to every page: `page.setRotation(degrees(current + delta))`.
- `organize.ts` — input is an ordered list `[{ fileId, pageIndex, rotation }]` across one or more files (files labelled A, B, C with per-file colour); builds a new document. Supports reorder, rotate, delete, sort, reset, and "insert blank page".
- `pageNumbers.ts` — options: `mode` single/facing, `position` (9-cell grid), `margin` small/recommended/big, `firstNumber`, `fromPage`/`toPage`, `template` (`{n}` / `Page {n}` / `Page {n} of {N}` / custom with `{n}` `{N}`), `font` Helvetica/Times/Courier, `size`, bold/italic (font variants), underline (drawn line), `color` hex. Facing mode mirrors horizontal position on even pages. Accounts for page rotation when computing coordinates. UI shows a red dot on each thumbnail at the chosen position (as in screenshot).
- `pdfToJpg.ts` — render each page with pdf.js at scale 2 (Normal, ≈144 dpi, q 0.85) or 3 (High, ≈216 dpi, q 0.92), `canvas.toBlob("image/jpeg")`, zip when >1 image.
- `zip.ts`, `download.ts` — helpers.

### Backend client (`lib/api.ts`)
- `uploadAndProcess(endpoint, files, fields, { onProgress })` using XHR for upload progress; returns `{ blob, filename, headers }`. Handles `422 password_required` for Unlock (opens per-file password dialog and retries), and surfaces error JSON `{ detail }` as toasts.

### Per-tool option panels (`components/tools/<tool>/`)
1. **Merge** — file order via drag, sort button, info callout. CTA "Merge PDF".
2. **Split** — tabs Range | Pages. Range: mode Custom (list of from/to ranges, "Add range", remove) or Fixed (every N pages); checkbox "Merge all ranges in one PDF". Pages: Extract all / Select pages (`1,3-5`) with same merge checkbox. Preview groups thumbnails per range (first … last). CTA "Split PDF". (Size mode is premium on iLovePDF; omitted.)
3. **Compress** — 3 radio cards: Extreme / Recommended (default) / Less. Result shows per-file "X% smaller".
4. **PDF to JPG** — mode cards Page to JPG (shows "N JPG will be created") / Extract images; quality Normal (default) / High. Page mode → browser; Extract → backend.
5. **Organize** — sidebar lists files (A: name, B: name) with colour chips and "Reset all"; page grid with reorder/rotate/delete, sort asc/desc, insert blank page. CTA "Organize".
6. **Rotate** — sidebar RIGHT / LEFT buttons apply to all files; hovering a file card shows a rotate icon for per-file rotation; thumbnail rotates live; "Reset all". Output: one PDF or ZIP.
7. **Page Numbers** — file selector dropdown (when multiple) for preview; options as listed above. CTA "Add page numbers".
8. **Protect** — password + repeat, show/hide toggles, CTA disabled until both match and non-empty (screenshot shows disabled state).
9. **Unlock** — callout "Just press the unlock button"; if backend replies `password_required`, dialog asks for the password for that file, retries; wrong password shows inline error.
10. **OCR** — multi-select of languages (max 3) populated from `GET /ocr/languages`; callout about accuracy. CTA "Apply OCR".

### Landing page
Hero (name, one-line pitch, "All tools run privately in your browser where possible"), grid of 10 `ToolCard`s (icon, name, tagline), footer. Distinct palette (single accent token in Tailwind theme; not iLovePDF red) — use the `frontend-design` skill when building UI.

---

## Backend (`backend/`)

### Setup
- `uv init`, Python 3.12, deps: `fastapi`, `uvicorn[standard]`, `python-multipart`, `ocrmypdf`, `pillow`, `pypdf` (for page counts/validation), dev: `pytest`, `httpx`.
- System binaries (Dockerfile, `python:3.12-slim-bookworm`): `ghostscript`, `qpdf`, `tesseract-ocr`, `tesseract-ocr-eng`, `poppler-utils` (for `pdfimages`). `ocrmypdf` installed via uv so it is current.
- Runs as non-root user; `/tmp/pdfkit` work dir.

### Structure
```
backend/app/
├── main.py            FastAPI app, CORS (CORS_ORIGINS env), /health, routers
├── config.py          MAX_UPLOAD_MB=50, MAX_CONCURRENT_JOBS=2, timeouts, CORS_ORIGINS
├── deps.py            save_uploads(): streams UploadFile(s) to a per-request TemporaryDirectory,
│                      rejects >50 MB or non-%PDF- magic bytes, sanitises filenames
├── services/
│   ├── runner.py      async subprocess runner (asyncio.create_subprocess_exec), timeout,
│                      global Semaphore(MAX_CONCURRENT_JOBS), sanitised error → HTTPException
│   ├── responses.py   file_response(): single → application/pdf, many → zip; BackgroundTask
│                      deletes temp dir; Content-Disposition with original-name-based filename
│   ├── compress.py    gs -sDEVICE=pdfwrite -dPDFSETTINGS=/screen|/ebook|/printer (+ image
│                      downsampling flags). If result ≥ input size, return the original.
│                      Sets X-Original-Size / X-Result-Size headers.
│   ├── protect.py     qpdf --encrypt <pw> <pw> 256 -- in out (password via --password-file)
│   ├── unlock.py      qpdf --decrypt [--password-file] in out. No password → try owner-only
│                      decrypt; qpdf "invalid password" → 422 {"detail":"password_required"};
│                      wrong password → 422 {"detail":"wrong_password"}
│   ├── ocr.py         ocrmypdf -l <langs> --skip-text --optimize 1 in out; langs validated
│                      against `tesseract --list-langs`
│   └── images.py      pdfimages -png → Pillow → JPEG (quality by "normal"/"high") → zip
└── routers/           compress.py, protect.py, unlock.py, ocr.py (+ GET /ocr/languages),
                       images.py — thin: parse form, call service, return response
```

### Endpoints (all `POST multipart/form-data`, `files: list[UploadFile]`)
| Endpoint | Fields | Returns |
|---|---|---|
| `/compress` | `level` = extreme/recommended/less | PDF or ZIP + size headers |
| `/protect` | `password` | PDF or ZIP |
| `/unlock` | `password` (optional) | PDF or ZIP, or 422 |
| `/ocr` | `languages` (comma list, ≤3) | PDF or ZIP |
| `/images/extract` | `quality` = normal/high | ZIP of JPGs |
| `GET /ocr/languages` | | `[{code, name}]` |
| `GET /health` | | `{status: ok}` |

### Tests (`backend/tests/`, run inside Docker)
Fixtures generate PDFs on the fly: a text PDF (pypdf), an image-only PDF (Pillow → PDF) for OCR, and an encrypted PDF (qpdf). Tests per endpoint: happy path, oversize rejection, non-PDF rejection, unlock password flow, compress-returns-original when no gain.

---

## Docker & deployment

- `frontend/Dockerfile` — multi-stage Node 22 alpine, `next build` with `ARG NEXT_PUBLIC_API_URL`, runs standalone server on 3000.
- `backend/Dockerfile` — as above, `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1` (concurrency handled by async + semaphore).
- `docker-compose.yml` — `frontend` (3000) and `backend` (8000); dev uses `docker compose up backend` + `npm run dev` for hot reload.
- Coolify: add as a **Docker Compose** resource from the GitHub repo; domains `pdfkit.zeeshanai.cloud` → frontend:3000 and `api.pdfkit.zeeshanai.cloud` → backend:8000; env `NEXT_PUBLIC_API_URL` (build-time), `CORS_ORIGINS`. Use the `add-app-to-coolify` skill for the deploy step. Verify Traefik does not cap request bodies below 50 MB.
- README: local dev, env vars, deploy notes.

---

## Implementation order

1. Scaffold: git init, frontend (create-next-app + shadcn), backend (uv, FastAPI hello, Dockerfile), docker-compose, README.
2. Shared UI: layout/header/footer, tool registry, landing page, `ToolShell`, dropzone, file grid + thumbnails, result/download view.
3. Browser tools in this order (each reusing the shell): Merge → Rotate → Split → PDF to JPG (page mode) → Organize → Page Numbers.
4. Backend services + routers + tests: compress, protect, unlock, ocr, images.
5. Wire backend tools in UI: Compress, Protect, Unlock, OCR, PDF to JPG extract mode; upload progress; error handling.
6. Polish: responsive layout, per-tool metadata, encrypted-file guard, empty/error states, favicon.
7. Deploy to Coolify.

---

## Verification

- **Backend**: `docker compose build backend && docker compose run --rm backend pytest`. Then `docker compose up backend`, `curl localhost:8000/health`, and `curl -F files=@sample.pdf -F level=recommended localhost:8000/compress -o out.pdf`.
- **Frontend**: `npm run lint && npm run build` clean; `npm run dev` with `NEXT_PUBLIC_API_URL=http://localhost:8000`.
- **Manual matrix** with three sample PDFs kept in `frontend/test-fixtures/` (multi-page text PDF, scanned image-only PDF, password-protected PDF):
  - Merge two files, reorder, sort → open output, page order correct.
  - Split: custom ranges → ZIP contents; fixed every 2; pages "1,3-5" merged → single PDF.
  - Rotate right twice then reset; per-file rotate → verify in viewer.
  - Organize two files: reorder, delete, rotate, blank page → output matches grid.
  - Page numbers: bottom-right, "Page {n} of {N}", facing mode, from page 2 → text present, mirrored on even pages.
  - PDF→JPG normal/high → image dimensions differ; extract images → ZIP has embedded images.
  - Compress all three levels → sizes shrink, extreme < recommended < less; opens fine.
  - Protect with password → file prompts for password in a viewer; Unlock it (with and without password paths).
  - OCR the scanned PDF → text selectable/searchable afterwards.
  - Encrypted PDF dropped on Merge → guard message links to Unlock.
  - Non-PDF and >50 MB upload rejected with clear message.
- **Prod**: after Coolify deploy, repeat Compress and OCR through the public domain (checks CORS and body-size limits).
