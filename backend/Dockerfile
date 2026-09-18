# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Native tooling the PDF services shell out to.
RUN apt-get update && apt-get install -y --no-install-recommends \
      ghostscript \
      qpdf \
      tesseract-ocr \
      tesseract-ocr-eng \
      poppler-utils \
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

COPY app ./app
COPY README.md ./
RUN uv sync --locked --no-dev

RUN useradd --system --create-home --uid 1001 pdfkit \
 && mkdir -p /tmp/pdfkit \
 && chown -R pdfkit:pdfkit /tmp/pdfkit /app

USER pdfkit
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
