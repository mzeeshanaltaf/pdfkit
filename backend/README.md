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
│   ├── anydoc_cli.py  anydoc as a killable subprocess (see its docstring for why)
│   ├── pdf2docx_cli.py  pdf2docx, patched so it stops eating inter-word spaces
│   └── remote_job.py  the shim that runs a batch INSIDE a Daytona sandbox
└── services/
    ├── runner.py    the ONLY place a subprocess is spawned (semaphore + timeout + sanitised stderr)
    ├── offload.py   ships a CPU-heavy batch to a sandbox instead — see below
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

## Daytona offload (optional, off by default)

This box is 2 vCPU and 8 GB shared with eighteen other Coolify apps, and
sustained 100% CPU has twice tripped Hostinger's protective throttle. With
`DAYTONA_ENABLED=true`, the four CPU-heavy operations — **OCR, PDF to Word,
PDF to Markdown and Compress** — are shipped to a throwaway 4 vCPU Daytona
sandbox instead, run there by `app/tools/remote_job.py`, and their outputs
pulled back. The VPS does nothing in between but relay progress. Everything
else (Protect, Unlock, image extraction) stays local: they are sub-second
`qpdf` calls where a round trip would dominate.

It is a flag, not a fork. `DAYTONA_ENABLED=false` is a complete rollback with
no code change, and the local path it falls back to is the one that has been
correct since the project started. A batch also runs locally whenever
offloading is not *possible* — the operation is not in `DAYTONA_OPERATIONS`,
the batch is under `DAYTONA_MIN_FILES` / `DAYTONA_MIN_BYTES`, every sandbox
slot is busy, or Daytona failed before producing anything. None of those are
errors; they are the ordinary answer.

The exception, and the rule worth knowing before debugging anything here: a
**document** failure (a 422 from an encrypted PDF) is never retried locally.
It would fail identically, having also burned the round trip. And once any
file of a batch has produced a result, a lost sandbox is a hard 502
`remote_job_interrupted` rather than a silent local rerun, because a rerun
would duplicate work that is already billed.

`app/services/offload.py` is the whole feature; nothing outside it imports
`daytona`. All the knobs are in `.env.example` under the `DAYTONA_*` heading,
each with a one-line comment.

### The snapshot

Daytona's stock snapshots carry no Ghostscript, Tesseract or OCRmyPDF, so
offloading cannot work without a snapshot of our own. It is the `toolchain`
stage of this `Dockerfile` — the same apt packages and the same locked
dependency set the backend image itself is built from, with application code
deliberately left out so `app/` can be uploaded per job and the snapshot only
goes stale when the *toolchain* moves.

`.github/workflows/snapshot.yml` builds it, on a push touching `Dockerfile`,
`pyproject.toml` or `uv.lock`, and on manual dispatch. **The name is the
content**: `pdfkit-toolchain-<12 hex>` over exactly those three files, so two
runs on unchanged inputs are a no-op. See the workflow for the rest; it is not
duplicated here.

Nothing updates `DAYTONA_SNAPSHOT` for you. After a toolchain change, take the
new name from the workflow run's summary and set it in Coolify by hand. Until
you do, sandbox creation fails against the old name and every batch falls back
to the VPS — correct results, just slower — which is the intended failure mode:
a name pointing at "latest" could otherwise move a running deploy onto a
toolchain that no longer matches its lockfile.

By hand, from `backend/`:

```bash
python scripts/build_snapshot.py --print-name          # no API call
DAYTONA_API_KEY=... uv run --with daytona python scripts/build_snapshot.py \
    --name "$(python scripts/build_snapshot.py --print-name)" --skip-existing
... --verify   # throwaway sandbox, checks gs/qpdf/tesseract/ocrmypdf
... --warm     # create and delete one sandbox, so Daytona keeps it active
```

Daytona deactivates a snapshot after roughly two weeks unused; the workflow's
weekly cron runs `--warm` to prevent that, and at runtime `provision()` also
wakes a sleeping snapshot and retries **once** before falling back.

### If it is suspected of misbehaving

1. **`GET /health`** — `sandboxes` is how many this process currently has
   open. It is a local counter, never a Daytona round trip, so it can lag a
   failed `dispose` by design. Flat at 0 while the feature is off; flat at 0
   *between* jobs when it is on and healthy.
2. **The backend log.** Every fallback says why, at WARNING: `provision
   failed` (bad or deactivated snapshot name, or Daytona down), `could not
   stage the job`, `all N remote slots are busy`. A silent fallback is the one
   thing this feature is not allowed to do.
3. **`DAYTONA_FALLBACK_LOCAL=false`** turns every Daytona failure into a
   visible 502 instead of a successful local run that hides it. This is the
   fastest way to tell "Daytona broke" apart from "the document was bad", and
   it is a rollout setting, not a production one.
4. **The Daytona dashboard.** Outside an active job there should be nothing
   there. Anything left over is swept on the next backend start (the log says
   how many), and cannot outlive `DAYTONA_TTL_MINUTES` regardless.
5. **`scripts/verify_offload.py`** runs the real matrix against the real
   account: output and error parity against the local path, fallback,
   cancellation, and the sharding numbers. See its docstring — and run
   `timings` from the VPS, not a workstation, before believing its verdict.

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
