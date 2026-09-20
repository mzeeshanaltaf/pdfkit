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
    # pdf2docx rebuilds the layout page by page, so it scales with the
    # document rather than with its byte count.
    "word": int(os.getenv("WORD_TIMEOUT_SECONDS", "300")),
    "markdown": int(os.getenv("MARKDOWN_TIMEOUT_SECONDS", "120")),
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

# --- live progress -----------------------------------------------------------
#
# How many jobs the progress registry will track at once. A hard cap, because a
# registry is the one thing in this service that outlives a request: past it,
# new jobs simply run without progress rather than being refused.
MAX_TRACKED_JOBS = int(os.getenv("MAX_TRACKED_JOBS", "256"))

# A channel opened by a subscriber whose POST never arrives, and a channel whose
# job has finished, are both kept this long — the first so a slow upload still
# finds its stream, the second so a job that beat its subscriber reports "done"
# instead of hanging.
PROGRESS_PENDING_TTL_SECONDS = int(os.getenv("PROGRESS_PENDING_TTL_SECONDS", "30"))
PROGRESS_TERMINAL_TTL_SECONDS = int(os.getenv("PROGRESS_TERMINAL_TTL_SECONDS", "30"))

# An SSE comment on this interval keeps Traefik from closing an idle stream.
PROGRESS_KEEPALIVE_SECONDS = int(os.getenv("PROGRESS_KEEPALIVE_SECONDS", "15"))

MAX_STREAMS = int(os.getenv("MAX_STREAMS", "64"))
MAX_STREAMS_PER_IP = int(os.getenv("MAX_STREAMS_PER_IP", "4"))

# --- API protection ----------------------------------------------------------
#
# Shared with the Next server, which mints the tokens this service verifies.
# Unset means unauthenticated: the service still runs (and says so loudly at
# startup and on /health) rather than failing closed on a missing deploy var.
API_TOKEN_SECRET = os.getenv("API_TOKEN_SECRET", "")
# Verify-only, so the secret can be rotated without a window where live tokens
# minted a second ago stop working.
API_TOKEN_SECRET_PREVIOUS = os.getenv("API_TOKEN_SECRET_PREVIOUS", "")
API_TOKEN_TTL_SECONDS = int(os.getenv("API_TOKEN_TTL_SECONDS", "120"))
API_TOKEN_SKEW_SECONDS = int(os.getenv("API_TOKEN_SKEW_SECONDS", "60"))
API_TOKEN_AUDIENCE = os.getenv("API_TOKEN_AUDIENCE", "pdfkit-api")

# Per-IP sliding windows, as (requests, seconds). A real user running five-file
# batches makes one to three requests a minute.
RATE_LIMIT_COARSE = (
    int(os.getenv("RATE_LIMIT_COARSE_REQUESTS", "240")),
    int(os.getenv("RATE_LIMIT_COARSE_SECONDS", "60")),
)
RATE_LIMIT_JOB_BURST = (
    int(os.getenv("RATE_LIMIT_JOB_BURST_REQUESTS", "20")),
    int(os.getenv("RATE_LIMIT_JOB_BURST_SECONDS", "60")),
)
RATE_LIMIT_JOB_HOURLY = (
    int(os.getenv("RATE_LIMIT_JOB_HOURLY_REQUESTS", "120")),
    int(os.getenv("RATE_LIMIT_JOB_HOURLY_SECONDS", "3600")),
)
RATE_LIMIT_PROGRESS = (
    int(os.getenv("RATE_LIMIT_PROGRESS_REQUESTS", "60")),
    int(os.getenv("RATE_LIMIT_PROGRESS_SECONDS", "60")),
)

# How many client addresses the limiter remembers. LRU-evicted, so the worst a
# flood of unique addresses can do is forget the oldest legitimate one.
RATE_LIMIT_MAX_CLIENTS = int(os.getenv("RATE_LIMIT_MAX_CLIENTS", "4096"))
