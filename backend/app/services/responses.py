"""Turning a service's output files into the HTTP response.

One output goes back as itself; several go back as a zip. Either way the
request's temp directory is deleted by a ``BackgroundTask``, which Starlette
runs *after* the body has been written to the wire.
"""

from __future__ import annotations

import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from app.deps import UploadBatch, display_name, sanitise_filename

ZIP_MEDIA_TYPE = "application/zip"
PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
MARKDOWN_MEDIA_TYPE = "text/markdown; charset=utf-8"


@dataclass(slots=True)
class OutputFile:
    """A finished file on disk plus the name the user should receive it under."""

    path: Path
    download_name: str
    media_type: str = PDF_MEDIA_TYPE


def derive_name(source_name: str, suffix: str, extension: str = "pdf") -> str:
    """``sample.pdf`` + ``compressed`` → ``sample-compressed.pdf``."""
    stem = Path(sanitise_filename(source_name)).stem
    return f"{stem}-{suffix}.{extension}"


def convert_name(source_name: str, extension: str) -> str:
    """``report.pdf`` + ``docx`` → ``report.docx``.

    Unlike :func:`derive_name` there is no suffix, because the extension has
    already changed: ``report-word.docx`` would be noise, and the name cannot
    collide with the input the way ``report-compressed.pdf`` could.
    """
    stem = Path(sanitise_filename(source_name)).stem
    return f"{stem}.{extension}"


def unique_names(outputs: Sequence[OutputFile]) -> list[str]:
    """Zip entry names, de-duplicated — a repeat would silently overwrite."""
    seen: dict[str, int] = {}
    names: list[str] = []
    for output in outputs:
        name = output.download_name
        if name in seen:
            seen[name] += 1
            stem, dot, ext = name.rpartition(".")
            base = stem if dot else name
            tail = f".{ext}" if dot else ""
            name = f"{base} ({seen[output.download_name]}){tail}"
        else:
            seen[name] = 1
        names.append(name)
    return names


def build_archive(outputs: Sequence[OutputFile], destination: Path) -> Path:
    """Zip the outputs. Deflate level 1: PDFs barely shrink, so speed wins."""
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1
    ) as archive:
        for output, name in zip(outputs, unique_names(outputs), strict=True):
            archive.write(output.path, arcname=name)
    return destination


def file_response(
    outputs: Sequence[OutputFile],
    batch: UploadBatch,
    *,
    archive_name: str,
    headers: Mapping[str, str] | None = None,
) -> FileResponse:
    """Respond with the single output, or with a zip of all of them.

    Takes ownership of ``batch``: its temp directory is removed once the
    response has been sent.
    """
    cleanup = BackgroundTask(batch.cleanup)
    extra = dict(headers or {})

    if len(outputs) == 1:
        only = outputs[0]
        return FileResponse(
            only.path,
            media_type=only.media_type,
            filename=only.download_name,
            headers=extra,
            background=cleanup,
        )

    archive = build_archive(outputs, batch.directory / "result.zip")
    return FileResponse(
        archive,
        media_type=ZIP_MEDIA_TYPE,
        filename=sanitise_archive_name(archive_name),
        headers=extra,
        background=cleanup,
    )


def sanitise_archive_name(name: str) -> str:
    """Make a safe ``*.zip`` name, whatever extension the caller passed.

    ``sanitise_filename`` forces ``.pdf``, so it cannot be reused here: feeding
    it "x.zip" gives "x.zip.pdf" and the .zip would end up doubled.
    """
    cleaned = display_name(name)
    stem, dot, extension = cleaned.rpartition(".")
    if dot and extension.lower() in ("zip", "pdf"):
        cleaned = stem
    return f"{cleaned or 'pdfkit'}.zip"
