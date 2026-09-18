# Phase 4 — Backend Services, Routers, Tests

## Goal
All backend PDF processing (Compress, Protect, Unlock, OCR, Extract images) implemented, tested, and runnable via Docker. No frontend wiring yet — verify entirely with curl/pytest.

## Prerequisites
Phase 0 backend scaffold exists (`GET /health` works in Docker). Frontend phases are independent of this one and don't block it.

## Tasks

### 1. Config & shared deps
- `app/config.py` (extend Phase 0 stub): `MAX_UPLOAD_MB=50`, `MAX_CONCURRENT_JOBS=2`, timeouts per operation, `CORS_ORIGINS`.
- `app/deps.py` — `save_uploads()`: streams `UploadFile`(s) to a per-request `TemporaryDirectory`, rejects files >50 MB or without `%PDF-` magic bytes, sanitises filenames.
- `app/services/runner.py` — async subprocess runner (`asyncio.create_subprocess_exec`), per-op timeout, a global `asyncio.Semaphore(MAX_CONCURRENT_JOBS)`, sanitised stderr → `HTTPException`.
- `app/services/responses.py` — `file_response()`: single output → `application/pdf`, multiple → zip; `BackgroundTask` deletes the temp dir after response is sent; `Content-Disposition` filename derived from the original upload name.

### 2. Services (`app/services/`)
- `compress.py` — `gs -sDEVICE=pdfwrite -dPDFSETTINGS=/screen|/ebook|/printer` (+ image downsampling flags) for extreme/recommended/less. If the result is ≥ input size, return the original file unchanged. Sets `X-Original-Size` / `X-Result-Size` response headers.
- `protect.py` — `qpdf --encrypt <pw> <pw> 256 -- in out`, password passed via `--password-file` (never on the command line/process list where it could leak via `ps`).
- `unlock.py` — `qpdf --decrypt [--password-file] in out`. No password supplied → try owner-password-only decrypt first; qpdf "invalid password" → `422 {"detail":"password_required"}`; wrong password supplied → `422 {"detail":"wrong_password"}`.
- `ocr.py` — `ocrmypdf -l <langs> --skip-text --optimize 1 in out`; requested languages validated against `tesseract --list-langs` output before running.
- `images.py` — `pdfimages -png` → Pillow → JPEG (quality mapped from `"normal"`/`"high"`) → zip.

### 3. Routers (`app/routers/`)
Thin: parse multipart form, call service, return via `file_response()`.
| Endpoint | Fields | Returns |
|---|---|---|
| `POST /compress` | `level` = extreme/recommended/less | PDF or ZIP + size headers |
| `POST /protect` | `password` | PDF or ZIP |
| `POST /unlock` | `password` (optional) | PDF or ZIP, or 422 |
| `POST /ocr` | `languages` (comma list, ≤3) | PDF or ZIP |
| `POST /images/extract` | `quality` = normal/high | ZIP of JPGs |
| `GET /ocr/languages` | — | `[{code, name}]` |

### 4. Tests (`backend/tests/`, run inside Docker — Ghostscript/qpdf aren't installed on the local machine)
Fixtures generated on the fly, no binary test assets committed: a text PDF (pypdf), an image-only PDF (Pillow → PDF) for OCR, an encrypted PDF (qpdf, generated in the fixture itself). Cover per endpoint: happy path, oversize (>50MB) rejection, non-PDF rejection, unlock password flow (no password / correct / wrong), compress-returns-original-when-no-gain.

## Verification
- `docker compose build backend && docker compose run --rm backend pytest` — all green.
- `docker compose up backend`, then:
  - `curl localhost:8000/health` → `{"status":"ok"}`.
  - `curl -F files=@sample.pdf -F level=recommended localhost:8000/compress -o out.pdf` → valid, smaller PDF.
  - `curl localhost:8000/ocr/languages` → at least English listed.
  - Manually exercise protect → unlock (right and wrong password) and OCR on the image-only fixture (confirm text becomes selectable, e.g. via `pdftotext`).

## Definition of done
All 5 backend endpoints implemented, tested, and verified via curl against the Dockerized service; `STATUS.md` updated.
