"""Runtime configuration, read from the environment with safe local defaults."""

from __future__ import annotations

import os

APP_NAME = "PDFKit"

# Hard cap per uploaded file. Mirrored client-side so the browser can fail fast.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024

# Ceiling on how many files one request may carry, so a single caller cannot
# occupy a worker for MAX_FILES_PER_REQUEST * the per-file timeout.
MAX_FILES_PER_REQUEST = int(os.getenv("MAX_FILES_PER_REQUEST", "20"))

# How many external tool subprocesses (ghostscript, qpdf, ocrmypdf) may run at once.
MAX_CONCURRENT_JOBS = int(os.getenv("MAX_CONCURRENT_JOBS", "2"))

# Wall-clock ceiling for a single subprocess job. Per operation, because OCR is
# minutes-scale on a scanned document while qpdf is milliseconds-scale.
JOB_TIMEOUT_SECONDS = int(os.getenv("JOB_TIMEOUT_SECONDS", "180"))
TIMEOUTS: dict[str, int] = {
    "compress": int(os.getenv("COMPRESS_TIMEOUT_SECONDS", "180")),
    "protect": int(os.getenv("PROTECT_TIMEOUT_SECONDS", "60")),
    "unlock": int(os.getenv("UNLOCK_TIMEOUT_SECONDS", "60")),
    "ocr": int(os.getenv("OCR_TIMEOUT_SECONDS", "600")),
    "images": int(os.getenv("IMAGES_TIMEOUT_SECONDS", "180")),
    "probe": int(os.getenv("PROBE_TIMEOUT_SECONDS", "20")),
}

# How long a request may wait for a free job slot before giving up with 503.
QUEUE_TIMEOUT_SECONDS = int(os.getenv("QUEUE_TIMEOUT_SECONDS", "60"))

# Most languages a single OCR request may ask for. Each one costs a full pass.
MAX_OCR_LANGUAGES = int(os.getenv("MAX_OCR_LANGUAGES", "3"))

# Scratch space for per-request temp files; wiped when each request finishes.
WORK_DIR = os.getenv("WORK_DIR", "/tmp/pdfkit")


def timeout_for(operation: str) -> int:
    """Seconds allowed for one subprocess of the named operation."""
    return TIMEOUTS.get(operation, JOB_TIMEOUT_SECONDS)


def _parse_origins(raw: str) -> list[str]:
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


CORS_ORIGINS = _parse_origins(
    os.getenv("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
)
