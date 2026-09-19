"""Compress PDFs with Ghostscript's pdfwrite device."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.deps import SavedUpload, UploadBatch
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services.responses import OutputFile, derive_name
from app.services.runner import run, sanitise

logger = logging.getLogger(__name__)

LEVELS = ("extreme", "recommended", "less")
DEFAULT_LEVEL = "recommended"


@dataclass(frozen=True, slots=True)
class Preset:
    """A Ghostscript quality tier plus the resolutions it downsamples to."""

    pdf_settings: str
    colour_dpi: int
    mono_dpi: int


PRESETS: dict[str, Preset] = {
    "extreme": Preset(pdf_settings="/screen", colour_dpi=72, mono_dpi=300),
    "recommended": Preset(pdf_settings="/ebook", colour_dpi=150, mono_dpi=600),
    "less": Preset(pdf_settings="/printer", colour_dpi=300, mono_dpi=1200),
}


@dataclass(slots=True)
class CompressionResult:
    outputs: list[OutputFile]
    original_size: int
    result_size: int


def validate_level(level: str | None) -> str:
    chosen = (level or DEFAULT_LEVEL).strip().lower()
    if chosen not in PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"level must be one of {', '.join(LEVELS)}.",
        )
    return chosen


def _command(source: Path, destination: Path, preset: Preset) -> list[str]:
    return [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        f"-dPDFSETTINGS={preset.pdf_settings}",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        "-dSAFER",
        # Shared images are stored once instead of per placement — usually the
        # single biggest win on a document built from a template.
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
        "-dDownsampleColorImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={preset.colour_dpi}",
        "-dDownsampleGrayImages=true",
        "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={preset.colour_dpi}",
        "-dDownsampleMonoImages=true",
        "-dMonoImageDownsampleType=/Subsample",
        f"-dMonoImageResolution={preset.mono_dpi}",
        f"-sOutputFile={destination}",
        str(source),
    ]


async def compress_one(upload: SavedUpload, workspace: Path, level: str) -> OutputFile:
    """Compress one file, falling back to the original when it does not shrink."""
    ensure_readable(upload.path)
    preset = PRESETS[level]
    destination = workspace / f"{upload.path.stem}-compressed.pdf"

    result = await run(
        _command(upload.path, destination, preset),
        operation="compress",
        check=False,
    )
    if not result.ok or not destination.exists():
        if mentions_password(result.output):
            raise encrypted_input()
        logger.error("ghostscript failed (%s): %s", result.returncode, result.output)
        raise HTTPException(
            status_code=500, detail=sanitise(result.output) or "compress_failed"
        )

    # A PDF that is already lean — or is mostly vector art — regularly comes back
    # bigger after a pdfwrite round trip. Handing that back would be a worse file
    # for the same wait, so the original wins.
    if destination.stat().st_size >= upload.size:
        logger.info("compress: no gain on %s, returning original", upload.original_name)
        shutil.copyfile(upload.path, destination)

    return OutputFile(
        path=destination,
        download_name=derive_name(upload.original_name, "compressed"),
    )


async def compress(batch: UploadBatch, level: str) -> CompressionResult:
    workspace = batch.workspace("out")
    outputs = [await compress_one(upload, workspace, level) for upload in batch.files]
    return CompressionResult(
        outputs=outputs,
        original_size=sum(upload.size for upload in batch.files),
        result_size=sum(output.path.stat().st_size for output in outputs),
    )
