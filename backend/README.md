# PDFKit backend

FastAPI service for the PDF tools that need native binaries (Ghostscript, qpdf,
Tesseract, poppler): Compress, OCR, Protect, Unlock and image extraction.

Run it via Docker from the repo root — those binaries are not expected to be
installed on the host:

```bash
docker compose up backend
curl localhost:8000/health
```

See the root `README.md` for the full development workflow.
