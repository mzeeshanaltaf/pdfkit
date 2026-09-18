"""Runtime configuration, read from the environment with safe local defaults."""

from __future__ import annotations

import os

APP_NAME = "PDFKit"

# Hard cap per uploaded file. Mirrored client-side so the browser can fail fast.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# How many external tool subprocesses (ghostscript, qpdf, ocrmypdf) may run at once.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))

# Wall-clock ceiling for a single subprocess job.
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "180"))

# Scratch space for per-request temp files; wiped when each request finishes.
WORK_DIR = os.getenv("WORK_DIR", "/tmp/pdfkit")


def _parse_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


CORS_ORIGINS = _parse_origins(
    os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
)
