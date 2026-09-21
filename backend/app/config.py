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

# --- Daytona offload ---------------------------------------------------------
#
# Moving the CPU-heavy operations into a per-request sandbox, so a 2 vCPU VPS
# shared with 18 other apps is not the thing grinding through a 50-page scan.
# Off by default: unset, every one of these values is inert and the service
# behaves exactly as it did before the feature existed.
#
# Like `auth` and `ratelimit`, everything here is read as `config.X` inside the
# function that uses it — `from app.config import X` binds a copy at import and
# makes `monkeypatch` silently useless in tests.
DAYTONA_ENABLED = os.getenv("DAYTONA_ENABLED", "false").lower() == "true"
DAYTONA_API_KEY = os.getenv("DAYTONA_API_KEY", "")
DAYTONA_API_URL = os.getenv("DAYTONA_API_URL", "https://app.daytona.io/api")
DAYTONA_TARGET = os.getenv("DAYTONA_TARGET", "eu")
DAYTONA_SNAPSHOT = os.getenv("DAYTONA_SNAPSHOT", "pdfkit-toolchain")

# Which operations may be offloaded. All four have an offload head; naming one
# that does not would be a silent no-op rather than an error, which is why this
# list only ever names what actually works. Written in compute-per-byte order —
# OCR's remote core measured 2.62x a VPS core, Word and Markdown inherit that
# whenever their OCR sub-step fires, and Compress's win is VPS-CPU protection
# on a big batch more than raw per-file speed. The order itself is cosmetic:
# `offload.eligible` only ever tests membership.
DAYTONA_OPERATIONS = _parse_origins(
    os.getenv("DAYTONA_OPERATIONS", "ocr,word,markdown,compress")
)

# The most sandboxes this process may have alive at once — one permit is one
# sandbox, not one request. It is therefore also the most shards a single
# batch is split into (`offload._split`), so a large batch can legitimately
# take the whole ceiling and leave the next request to run on the VPS.
DAYTONA_MAX_SANDBOXES = int(os.getenv("DAYTONA_MAX_SANDBOXES", "2"))

# Sizing for the *snapshot build* (backend/scripts/build_snapshot.py), not for
# any per-request create: Daytona rejects cpu/memory/disk on POST /sandbox when
# the sandbox comes from a snapshot ("Cannot specify Sandbox resources when
# using a snapshot"), because a snapshot's resources are fixed when it is built.
DAYTONA_SANDBOX_CPU = int(os.getenv("DAYTONA_SANDBOX_CPU", "4"))
DAYTONA_SANDBOX_MEMORY_GB = int(os.getenv("DAYTONA_SANDBOX_MEMORY_GB", "4"))
DAYTONA_SANDBOX_DISK_GB = int(os.getenv("DAYTONA_SANDBOX_DISK_GB", "10"))

# What makes a batch worth the round trip. The file count and the operation do
# the real gating: the measured VPS-to-Daytona link is ~60 MB/s, so a full
# 50 MB file costs about 1.5 s of transfer against ~1 s of lifecycle.
DAYTONA_MIN_FILES = int(os.getenv("DAYTONA_MIN_FILES", "2"))
# A cheap floor, not an economic gate — kept so a single tiny file never pays
# provisioning latency, not because transfer cost is the risk.
DAYTONA_MIN_BYTES = int(os.getenv("DAYTONA_MIN_BYTES", "5242880"))

DAYTONA_PROVISION_TIMEOUT_SECONDS = int(
    os.getenv("DAYTONA_PROVISION_TIMEOUT_SECONDS", "150")
)
DAYTONA_OVERHEAD_SECONDS = int(os.getenv("DAYTONA_OVERHEAD_SECONDS", "90"))

# Belt and braces against a leaked sandbox: it stops itself after this long
# idle, and disappears entirely at the TTL, even if the VPS died mid-request
# and never got to delete it.
DAYTONA_AUTO_STOP_MINUTES = int(os.getenv("DAYTONA_AUTO_STOP_MINUTES", "5"))
DAYTONA_TTL_MINUTES = int(os.getenv("DAYTONA_TTL_MINUTES", "30"))

# With this false, a Daytona failure is a hard error rather than a silent local
# retry — useful during rollout for telling "Daytona broke" apart from "the
# document was bad", which a successful fallback would hide.
DAYTONA_FALLBACK_LOCAL = os.getenv("DAYTONA_FALLBACK_LOCAL", "true").lower() == "true"


def remote_timeout_for(operation: str) -> int:
    """Wall-clock budget for one offloaded batch.

    The same budget the operation gets locally, plus room for the sandbox
    lifecycle and the transfer either side of it.
    """
    return timeout_for(operation) + DAYTONA_OVERHEAD_SECONDS


# --- sandbox telemetry --------------------------------------------------------
#
# One record per shard, posted to the Next app's stats Postgres so the admin
# dashboard can report Daytona's own cost without depending on its Spending
# dashboard, which lags real consumption by up to 48 hours. Off unless both are
# set — see app/services/sandbox_stats.py.
STATS_INGEST_URL = os.getenv("STATS_INGEST_URL", "")
STATS_INGEST_SECRET = os.getenv("STATS_INGEST_SECRET", "")
