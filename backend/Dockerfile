# syntax=docker/dockerfile:1

# --- base: system tooling and the production dependency set ------------------
FROM python:3.12-slim-bookworm AS base

# Native tooling the PDF services shell out to.
# The tesseract-ocr-* packages are the OCR models. Each is ~1-6 MB and shows up in
# GET /ocr/languages on its own, so adding one here is the whole change - no code edit.
# Note the package name and the Tesseract code differ for some: chi-sim vs chi_sim.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ghostscript \
      qpdf \
      tesseract-ocr \
      tesseract-ocr-eng \
      tesseract-ocr-ara \
      tesseract-ocr-chi-sim \
      tesseract-ocr-deu \
      tesseract-ocr-fra \
      tesseract-ocr-hin \
      tesseract-ocr-ita \
      tesseract-ocr-jpn \
      tesseract-ocr-nld \
      tesseract-ocr-por \
      tesseract-ocr-rus \
      tesseract-ocr-spa \
      tesseract-ocr-swe \
      tesseract-ocr-urd \
      poppler-utils \
      fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    WORK_DIR=/tmp/pdfkit

WORKDIR /app

# Dependency layer first so source edits don't invalidate the install.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# --- toolchain: what the Daytona `pdfkit-toolchain` snapshot is built from ----
# `base` is already exactly the right layer - every apt package plus the locked
# dependency set, and no application code, which is what lets `app/` be uploaded
# per job instead of being baked in and going stale.
#
# The ENTRYPOINT is the only addition, and it has to live here rather than in
# the snapshot request: Daytona rejects a top-level `entrypoint` alongside a
# `buildInfo` ("Cannot specify an entrypoint when using a build info entry"),
# and a plain python:3.12-slim container with no long-running process drops
# into a REPL and exits before anything can be uploaded to it.
#
# Built into a snapshot by scripts/build_snapshot.py; Phase 5 turns that into CI.
FROM base AS toolchain
ENTRYPOINT ["sleep", "infinity"]

# --- test: dev dependencies and the suite, never shipped ---------------------
# Built with `--target test`; see the `backend-tests` service in docker-compose.
FROM base AS test

RUN uv sync --locked --no-install-project
COPY app ./app
COPY tests ./tests
COPY README.md ./
RUN uv sync --locked

RUN mkdir -p /tmp/pdfkit
CMD ["pytest", "-q"]

# --- runtime: the default target ---------------------------------------------
FROM base AS runtime

COPY app ./app
COPY README.md ./
RUN uv sync --locked --no-dev

# uid and gid are both pinned to 1001 because docker-compose.yml has to name
# them when it mounts the /tmp/pdfkit tmpfs; an auto-assigned gid would drift.
RUN groupadd --system --gid 1001 pdfkit \
 && useradd --system --create-home --uid 1001 --gid 1001 pdfkit \
 && mkdir -p /tmp/pdfkit \
 && chown -R pdfkit:pdfkit /tmp/pdfkit /app

USER pdfkit
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
