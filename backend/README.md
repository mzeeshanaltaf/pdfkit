# PDFKit backend

FastAPI service for the PDF tools that need native binaries or heavyweight
libraries (Ghostscript, qpdf, Tesseract, poppler, pdf2docx, anydoc): Compress,
OCR, Protect, Unlock, image extraction, PDF to Word and PDF to Markdown.

Run it via Docker from the repo root — those binaries are not expected to be
installed on the host:

```bash
docker compose up backend
curl localhost:8000/health
```

## Endpoints

All of them take one or more `files` parts (multipart, PDF only, 50 MB each,
20 files per request). One input comes back as a single file; several come back
as a zip. Nothing is stored: each request gets a temp directory that is deleted
once the response has been sent.

| Endpoint | Fields | Returns |
|---|---|---|
| `POST /compress` | `level` = `extreme` \| `recommended` \| `less` | PDF or ZIP, plus `X-Original-Size` / `X-Result-Size` |
| `POST /protect` | `password` | PDF or ZIP |
| `POST /unlock` | `password` (optional) | PDF or ZIP, or 422 |
| `POST /ocr` | `languages` (comma list, ≤ 3) | PDF or ZIP |
| `POST /images/extract` | `quality` = `normal` \| `high` | ZIP of JPGs |
| `POST /convert/word` | `ocr` = `off` (default) \| `auto`, `languages` | DOCX or ZIP |
| `POST /convert/markdown` | `ocr` = `auto` (default) \| `off`, `languages` | Markdown or ZIP |
| `GET /ocr/languages` | — | `[{code, name}]` |
| `GET /health` | — | `{"status": "ok"}` |

Errors are always `{"detail": "..."}`. The ones the UI is expected to branch on:

| Status | `detail` | Meaning |
|---|---|---|
| 413 | `<name> is over the 50 MB limit.` | One file too large |
| 415 | `<name> is not a PDF file.` | Failed the `%PDF-` magic-byte check |
| 422 | `password_required` | Encrypted input, no usable password given |
| 422 | `wrong_password` | A password was supplied and qpdf rejected it |
| 422 | `no_images_found` | `/images/extract` found nothing to extract |
| 422 | `needs_ocr` | The PDF is a scan and `ocr=off`, or OCR recognised nothing |
| 422 | `document_unreadable` | The converter could not parse the document |
| 422 | `document_too_complex` | The converter hit an internal resource limit |
| 400 | `password_missing` / `password_invalid` | Empty, absent, or containing a newline |
| 503 | `server_busy` | No job slot within `QUEUE_TIMEOUT_SECONDS` |
| 504 | `processing_timed_out` | The native tool exceeded its per-operation timeout |

## Layout

```
app/
├── config.py        env-driven settings: limits, per-operation timeouts, CORS
├── deps.py          save_uploads(): stream, validate, sanitise; UploadBatch owns the temp dir
├── main.py          app, CORS, router mounting
├── routers/         one thin module per endpoint — parse form, call service, respond
├── tools/
│   └── anydoc_cli.py  anydoc as a killable subprocess (see its docstring for why)
└── services/
    ├── runner.py    the ONLY place a subprocess is spawned (semaphore + timeout + sanitised stderr)
    ├── responses.py single file or zip, Content-Disposition, cleanup BackgroundTask
    ├── errors.py    password-error detection and the pypdf encrypted-input pre-check
    ├── passwords.py qpdf secret files, so a password never lands in argv
    ├── compress.py  ghostscript
    ├── protect.py   qpdf --encrypt
    ├── unlock.py    qpdf --decrypt
    ├── ocr.py       ocrmypdf + the tesseract language list + the shared `ocr` field
    ├── images.py    pdfimages + Pillow
    ├── word.py      pdf2docx, via its CLI
    ├── markdown.py  anydoc, with a per-page OCR fallback
    └── text_layer.py  reading, and revealing, the text layer OCR leaves behind
```

## Tests

The suite needs Ghostscript, qpdf, Tesseract, poppler, pdf2docx and anydoc, so it runs in its own
image — the `test` build target, which is the runtime image plus dev
dependencies and `tests/`. Fixtures are generated at run time; no binary test
assets are committed.

```bash
docker compose --profile test run --rm backend-tests            # pytest -q
docker compose --profile test run --rm backend-tests pytest -v  # or anything else
```

Running `pytest` on the host also works — every test that needs a native binary
skips itself.

See the root `README.md` for the full development workflow.
