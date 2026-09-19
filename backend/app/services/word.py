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
import logging
import sys
from pathlib import Path

from fastapi import HTTPException

from app.deps import SavedUpload, UploadBatch
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services.ocr import ocr_to_path
from app.services.responses import DOCX_MEDIA_TYPE, OutputFile, convert_name
from app.services.runner import run, sanitise
from app.services.text_layer import pages_without_text, reveal_text

logger = logging.getLogger(__name__)

# The directory the `app` package lives in, so `-m app.tools.pdf2docx_cli`
# resolves whatever the working directory happens to be — uvicorn in the
# container starts in /app, pytest on a developer machine does not.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]


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
    ocred = await ocr_to_path(upload.path, scratch / f"{stem}-ocr.pdf", scratch, languages)
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
    workspace = batch.workspace("out")
    scratch = batch.workspace("convert-tmp")
    return [
        await to_word_one(upload, workspace, scratch, ocr_mode, languages)
        for upload in batch.files
    ]
