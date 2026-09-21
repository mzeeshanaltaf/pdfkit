"""Convert a PDF into Markdown with anydoc, reading the pages that need OCR.

anydoc converts locally and does no OCR of its own, so a page that is an image
with no text layer makes it raise ``NeedsOcrError`` — naming exactly which
pages, 1-based. Adding a text layer with OCRmyPDF does **not** change its mind:
the recognised text is there and both pypdf and pdftotext read it, but anydoc
still classifies the page as a scan. That is measured behaviour, not a guess,
and it is what shapes the strategy:

1. Convert the whole document in one go. If that works — the born-digital case,
   and the common one — it is the best possible result, because a table or a
   paragraph running across a page break stays in one piece.
2. If it reports NeedsOcr and OCR is allowed, OCR the whole file once with
   ``--skip-text`` (which leaves pages that already have text alone), then
   assemble the document page by page: the pages anydoc could not read are
   filled in from the recognised text layer, and every other page is converted
   by anydoc on its own so that its structure survives.

The per-page conversions share a single subprocess, so a long document does not
pay for an interpreter start per page.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader, PdfWriter

from app.deps import SavedUpload, UploadBatch
from app.services.errors import encrypted_input, ensure_readable
from app.services import offload, progress
from app.services.ocr import ocr_to_path
from app.services.responses import MARKDOWN_MEDIA_TYPE, OutputFile, convert_name
from app.services.runner import ToolResult, run, sanitise
from app.services.text_layer import page_texts

logger = logging.getLogger(__name__)

NEEDS_OCR = "needs_ocr"
UNREADABLE = "document_unreadable"
TOO_COMPLEX = "document_too_complex"

# A page neither anydoc nor OCR could get anything out of. Saying so in place is
# better than dropping it, which would leave a document quietly missing a page.
UNREADABLE_PAGE = "_Page {number} could not be read._"

# The directory the `app` package lives in, so `-m app.tools.anydoc_cli` resolves
# whatever the working directory happens to be — uvicorn in the container starts
# in /app, pytest on a developer machine does not.
_PACKAGE_ROOT = Path(__file__).resolve().parents[2]

#: Duplicated from ``app.tools.anydoc_cli`` rather than imported, so the API
#: process never loads anydoc's native module. ``tests/test_shims.py`` keeps
#: the two equal.
MARKER = "pdfkit_progress"

# Three steps, and which slice of one file's bar each owns. The first anydoc
# pass converts the whole document and usually *is* the whole job; the other
# two only happen when it comes back needing OCR, which is the scanned case.
_FIRST_PASS = (0.0, 25.0)
_OCR_SLICE = (25.0, 45.0)
_ASSEMBLE_SLICE = (70.0, 30.0)


def _progress_reader(publisher: progress.Publisher, scale: tuple[float, float]):
    """Turn the shim's stderr lines into positions on this file's bar."""
    base, span = scale

    def on_line(stream: str, line: str) -> None:
        if stream != "stderr" or MARKER not in line:
            return
        try:
            payload = json.loads(line)
            total = float(payload["total"] or 0)
            done = float(payload["done"])
        except (ValueError, KeyError, TypeError):
            return
        if total <= 0:
            return
        publisher.percent(base + span * min(1.0, done / total))

    return on_line


def _parse(result: ToolResult) -> list[dict]:
    """The shim's per-file JSON status lines."""
    parsed: list[dict] = []
    for raw in result.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        # Only status lines. The shim puts progress on stderr precisely so it
        # cannot land here, but `to_markdown_one` indexes lines[0] positionally
        # and a stray object would silently become file zero's verdict — so
        # this is the second lock on the same door.
        if isinstance(payload, dict) and "status" in payload:
            parsed.append(payload)
    return parsed


async def _run_anydoc(
    out_dir: Path, sources: list[Path], scale: tuple[float, float] = _FIRST_PASS
) -> list[dict]:
    """Convert a batch of files in one subprocess, returning their status lines."""
    result = await run(
        # sys.executable, not "python": the venv interpreter is the one anydoc
        # is installed into.
        [sys.executable, "-m", "app.tools.anydoc_cli", str(out_dir), *map(str, sources)],
        operation="markdown",
        check=False,
        cwd=_PACKAGE_ROOT,
        on_line=_progress_reader(progress.current(), scale),
    )
    if not result.ok:
        logger.error("anydoc could not run (%s): %s", result.returncode, result.output)
        raise HTTPException(
            status_code=500, detail=sanitise(result.output) or "convert_failed"
        )
    return _parse(result)


def _raise_for(status: str, name: str) -> None:
    """Turn a per-file status into the error the UI knows how to show."""
    if status == "encrypted":
        raise encrypted_input()
    if status == "unreadable":
        raise HTTPException(status_code=422, detail=UNREADABLE)
    if status == "too_complex":
        raise HTTPException(status_code=422, detail=TOO_COMPLEX)
    logger.error("anydoc could not convert %s: %s", name, status)
    raise HTTPException(status_code=500, detail="convert_failed")


def _split_pages(source: Path, out_dir: Path, wanted: list[int]) -> dict[int, Path]:
    """Write each wanted page (1-based) out as its own PDF. Blocking; use a thread."""
    reader = PdfReader(str(source))
    written: dict[int, Path] = {}
    for number in wanted:
        writer = PdfWriter()
        writer.add_page(reader.pages[number - 1])
        path = out_dir / f"page-{number:04d}.pdf"
        with path.open("wb") as handle:
            writer.write(handle)
        written[number] = path
    return written


def as_markdown(text: str) -> str:
    """Recognised text, as Markdown paragraphs.

    OCR gives back lines, not structure: a paragraph arrives hard-wrapped at
    whatever width the page was set in. Blank lines are the only paragraph
    signal there is, so they are kept and the wrapping inside each block is
    undone — otherwise every line break would survive into the Markdown and the
    result would not reflow.
    """
    blocks = text.replace("\r\n", "\n").split("\n\n")
    paragraphs = [" ".join(block.split()) for block in blocks if block.strip()]
    return "\n\n".join(paragraphs)


def _page_count(source: Path) -> int:
    return len(PdfReader(str(source)).pages)


async def _assemble(
    source: Path, work: Path, ocred: Path, needs_ocr: list[int]
) -> str:
    """Build the document page by page, recognised text standing in where anydoc could not read."""
    page_count = await asyncio.to_thread(_page_count, source)
    recognised = await asyncio.to_thread(page_texts, ocred)

    # Pages anydoc has already refused are not offered to it a second time. If
    # it named none — it always has so far, but the field is its own — every
    # page is tried and the recognised text is the fallback.
    skip = set(needs_ocr)
    convertible = [number for number in range(1, page_count + 1) if number not in skip]

    pages_dir = work / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    out_dir = work / "pages-md"

    converted: dict[int, str] = {}
    if convertible:
        split = await asyncio.to_thread(_split_pages, source, pages_dir, convertible)
        by_name = {path.name: number for number, path in split.items()}
        for line in await _run_anydoc(out_dir, list(split.values()), _ASSEMBLE_SLICE):
            number = by_name.get(str(line.get("input")))
            if number is None or line.get("status") != "ok":
                continue
            markdown = (out_dir / f"{split[number].stem}.md").read_text(encoding="utf-8")
            if markdown.strip():
                converted[number] = markdown.strip()

    parts: list[str] = []
    unread: list[int] = []
    for number in range(1, page_count + 1):
        markdown = converted.get(number) or as_markdown(recognised.get(number, ""))
        if markdown.strip():
            parts.append(markdown.strip())
        else:
            unread.append(number)
            parts.append(UNREADABLE_PAGE.format(number=number))

    if unread and len(unread) == page_count:
        # Neither route found anything: OCR recognised no lettering at all, so
        # there is no document to hand back.
        raise HTTPException(status_code=422, detail=NEEDS_OCR)
    if unread:
        logger.info("%s: no text recovered for pages %s", source.name, unread)

    return "\n\n".join(parts) + "\n"


async def to_markdown_one(
    upload: SavedUpload,
    workspace: Path,
    scratch: Path,
    ocr_mode: str,
    languages: list[str],
) -> OutputFile:
    ensure_readable(upload.path)
    destination = workspace / f"{upload.path.stem}.md"
    output = OutputFile(
        path=destination,
        download_name=convert_name(upload.original_name, "md"),
        media_type=MARKDOWN_MEDIA_TYPE,
    )

    lines = await _run_anydoc(workspace, [upload.path])
    status = str(lines[0].get("status")) if lines else "failed"

    if status == "ok" and destination.exists():
        return output
    if status != "needs_ocr":
        _raise_for(status, upload.original_name)
    if ocr_mode != "auto":
        raise HTTPException(status_code=422, detail=NEEDS_OCR)

    pages = [page for page in (lines[0].get("pages") or []) if isinstance(page, int)]
    logger.info(
        "%s needs OCR for pages %s; reading them and assembling page by page",
        upload.original_name,
        pages or "(unreported)",
    )

    work = scratch / upload.path.stem
    work.mkdir(parents=True, exist_ok=True)
    ocred = await ocr_to_path(
        upload.path, work / "ocr.pdf", scratch, languages, _OCR_SLICE
    )

    destination.write_text(
        await _assemble(upload.path, work, ocred, pages), encoding="utf-8"
    )
    return output


async def to_markdown(
    batch: UploadBatch, ocr_mode: str, languages: list[str]
) -> list[OutputFile]:
    """Convert every file in the batch, in a sandbox if one is worth provisioning.

    The first three lines are this tool's whole opt-in to the offload path;
    ``None`` means "not this time" and everything below runs exactly as it did
    before the feature existed. See :mod:`app.services.offload`.
    """
    if (
        offloaded := await offload.maybe_offload(
            "markdown", batch, {"ocr_mode": ocr_mode, "languages": languages}
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
            index, len(batch.files), upload.original_name, "Reading the document"
        )
        outputs.append(
            await to_markdown_one(upload, workspace, scratch, ocr_mode, languages)
        )
    return outputs
