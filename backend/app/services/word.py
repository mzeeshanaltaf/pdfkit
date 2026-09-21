"""Convert a PDF into an editable Word document with pdf2docx.

pdf2docx reads the PDF's layout and rebuilds it as real Word content —
paragraphs, runs, tables and images — rather than dropping a picture of each
page into a document. That is what makes the result editable, and it is also
why it needs text to work with: a scan has none until OCR puts some there,
which is what ``ocr="auto"`` is for.

It runs in a subprocess rather than in-process. Two reasons:
``app.services.runner`` can only enforce a timeout on something it can kill,
and keeping its AGPL PyMuPDF engine in a separate process is the same posture
this image already has with Ghostscript. That subprocess is
``app.tools.pdf2docx_cli`` rather than pdf2docx's own ``pdf2docx convert``,
because the stock library drops the spaces between words on PDFs that position
each word individually — see that module for what it does about it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from fastapi import HTTPException

from app.deps import SavedUpload, UploadBatch
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services import offload, progress
from app.services.ocr import ocr_to_path
from app.services.responses import DOCX_MEDIA_TYPE, OutputFile, convert_name
from app.services.runner import run, sanitise
from app.services.text_layer import pages_without_text, reveal_text

logger = logging.getLogger(__name__)

# The directory the `app` package lives in, so `-m app.tools.pdf2docx_cli`
# resolves whatever the working directory happens to be — uvicorn in the
# container starts in /app, pytest on a developer machine does not.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

#: Duplicated from ``app.tools.pdf2docx_cli`` rather than imported: importing
#: the shim here would pull pdf2docx and its PyMuPDF engine into the API
#: process, which is the one thing running it in a subprocess is for.
#: ``tests/test_shims.py`` keeps the two equal.
MARKER = "pdfkit_progress"

# Parsing the layout is most of the work; writing the .docx from an already
# parsed page is quick. Measured on the fixtures, and stable enough that a
# fixed split beats anything adaptive.
_DOCX_PHASES: dict[str, tuple[float, float]] = {
    "parse": (0.0, 0.8),
    "write": (0.8, 0.2),
}

# With OCR on, recognition dominates a scan and the rebuild dominates a
# born-digital file; this split is the compromise. Without OCR the rebuild
# owns the whole bar.
_OCR_SLICE = (0.0, 55.0)
_DOCX_SLICE_AFTER_OCR = (55.0, 45.0)
_DOCX_SLICE_ALONE = (0.0, 100.0)


def _progress_reader(publisher: progress.Publisher, scale: tuple[float, float]):
    """Turn the shim's stderr lines into positions on this file's bar."""
    base, span = scale

    def on_line(stream: str, line: str) -> None:
        if stream != "stderr" or MARKER not in line:
            return
        try:
            payload = json.loads(line)
            offset, width = _DOCX_PHASES[str(payload["phase"])]
            total = float(payload["total"] or 0)
            done = float(payload["done"])
        except (ValueError, KeyError, TypeError):
            return
        if total <= 0:
            return
        publisher.percent(base + span * (offset + width * min(1.0, done / total)))

    return on_line


async def _prepare(upload: SavedUpload, scratch: Path, languages: list[str]) -> Path:
    """OCR the document and make the recognised text usable by pdf2docx.

    pdf2docx ignores the invisible layer OCRmyPDF writes, so on a scan the two
    steps together are what produce an editable document rather than a picture
    of one. See ``app.services.text_layer`` for why.
    """
    stem = upload.path.stem
    # Which pages are scans is a property of the *input*: after OCR every page
    # has text, so asking afterwards would tell us nothing.
    scanned = await asyncio.to_thread(pages_without_text, upload.path)

    # --skip-text means this is nearly free on a born-digital PDF: every page
    # already has text, so OCRmyPDF passes them all through untouched.
    ocred = await ocr_to_path(
        upload.path, scratch / f"{stem}-ocr.pdf", scratch, languages, _OCR_SLICE
    )
    if not scanned:
        return ocred

    revealed = scratch / f"{stem}-revealed.pdf"
    if await asyncio.to_thread(reveal_text, ocred, revealed, scanned):
        return revealed
    # The rewrite is an optimisation, not a requirement: a document it cannot
    # handle still converts, just without the recognised text showing through.
    logger.info("%s: could not reveal the OCR text, converting as-is", upload.original_name)
    return ocred


async def to_word_one(
    upload: SavedUpload,
    workspace: Path,
    scratch: Path,
    ocr_mode: str,
    languages: list[str],
) -> OutputFile:
    ensure_readable(upload.path)

    source = upload.path
    if ocr_mode == "auto":
        source = await _prepare(upload, scratch, languages)

    destination = workspace / f"{upload.path.stem}.docx"
    result = await run(
        # sys.executable, not "python": the venv interpreter is the one pdf2docx
        # is installed into.
        [sys.executable, "-m", "app.tools.pdf2docx_cli", str(source), str(destination)],
        operation="word",
        check=False,
        cwd=_PACKAGE_ROOT,
        on_line=_progress_reader(
            progress.current(),
            _DOCX_SLICE_AFTER_OCR if ocr_mode == "auto" else _DOCX_SLICE_ALONE,
        ),
    )

    if not result.ok or not destination.exists():
        if mentions_password(result.output):
            raise encrypted_input()
        logger.error("pdf2docx failed (%s): %s", result.returncode, result.output)
        raise HTTPException(
            status_code=500, detail=sanitise(result.output) or "convert_failed"
        )

    return OutputFile(
        path=destination,
        download_name=convert_name(upload.original_name, "docx"),
        media_type=DOCX_MEDIA_TYPE,
    )


async def to_word(
    batch: UploadBatch, ocr_mode: str, languages: list[str]
) -> list[OutputFile]:
    """Convert every file in the batch, in a sandbox if one is worth provisioning.

    The first three lines are this tool's whole opt-in to the offload path;
    ``None`` means "not this time" and everything below runs exactly as it did
    before the feature existed. See :mod:`app.services.offload`.
    """
    if (
        offloaded := await offload.maybe_offload(
            "word", batch, {"ocr_mode": ocr_mode, "languages": languages}
        )
    ) is not None:
        return offloaded

    workspace = batch.workspace("out")
    scratch = batch.workspace("convert-tmp")
    publisher = progress.current()

    outputs: list[OutputFile] = []
    for index, upload in enumerate(batch.files, start=1):
        await progress.stop_if_cancelled()
        publisher.file(
            index, len(batch.files), upload.original_name, "Rebuilding the document"
        )
        outputs.append(
            await to_word_one(upload, workspace, scratch, ocr_mode, languages)
        )
    return outputs
