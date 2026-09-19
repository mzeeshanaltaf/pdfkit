"""Compress PDFs, by whichever route the document actually rewards.

There are two completely different reasons a PDF is large, and one tool for
each:

*Images.* A scan is a stack of JPEGs, and Ghostscript's pdfwrite device
downsamples and re-encodes them. Left to its defaults it does neither — it
passes JPEG data through untouched and only downsamples an image already well
past the target resolution — so the flags below turn both of those off.

*Vector drawing.* "Microsoft: Print To PDF" and friends emit every glyph as
filled bezier paths with six decimal places on every coordinate. Ghostscript
re-interprets that geometry and hands back a file around 45% **bigger**, while
simply rewriting the numbers takes a quarter off it. That is
``app.services.streams``.

So we survey the document first, run only the candidates its shape justifies,
and keep the smallest result. If nothing beats the upload we return the upload,
and the response headers report equal sizes so the UI can say so honestly.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.config import timeout_for
from app.deps import SavedUpload, UploadBatch
from app.services import streams
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services.responses import OutputFile, derive_name
from app.services.runner import job_slot, run

logger = logging.getLogger(__name__)

LEVELS = ("extreme", "recommended", "less")
DEFAULT_LEVEL = "recommended"

# Below these shares of the file, a strategy cannot win enough to be worth the
# seconds it costs. A scan is ~97% image bytes; a Print-To-PDF document is ~99%
# content-stream bytes; the middle is rare, and there both candidates run.
IMAGE_SHARE_FLOOR = 0.10
CONTENT_SHARE_FLOOR = 0.10


@dataclass(frozen=True, slots=True)
class Preset:
    """One quality tier: what Ghostscript downsamples to, and how far we round."""

    pdf_settings: str
    colour_dpi: int
    mono_dpi: int
    jpeg_quality: int
    # Decimal places to round vector coordinates to, or None to only strip the
    # padding zeros, which cannot change the drawing at all.
    precision: int | None


PRESETS: dict[str, Preset] = {
    "extreme": Preset("/screen", colour_dpi=72, mono_dpi=300, jpeg_quality=40, precision=2),
    "recommended": Preset("/ebook", colour_dpi=150, mono_dpi=600, jpeg_quality=65, precision=3),
    "less": Preset("/printer", colour_dpi=300, mono_dpi=1200, jpeg_quality=85, precision=None),
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


def _ghostscript(source: Path, destination: Path, preset: Preset) -> list[str]:
    return [
        "gs",
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.7",
        f"-dPDFSETTINGS={preset.pdf_settings}",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        "-dSAFER",
        # THE flag on this command line. Ghostscript 9.x and later copy DCT
        # (JPEG) image data through verbatim by default, which on a scanned
        # document means the output is the input plus overhead — the single
        # reason compression used to do nothing at all to a scan.
        "-dPassThroughJPEGImages=false",
        # Likewise: the default threshold of 1.5 only downsamples an image
        # already 1.5x past the target, so a 200 dpi scan sailed past a 150 dpi
        # setting untouched. 1.0 means "if it is above the target, resample it".
        "-dColorImageDownsampleThreshold=1.0",
        "-dGrayImageDownsampleThreshold=1.0",
        "-dMonoImageDownsampleThreshold=1.0",
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
        # Pin the encoder rather than letting Ghostscript choose per image, so
        # that the QFactor below is the one actually used.
        "-dAutoFilterColorImages=false",
        "-dAutoFilterGrayImages=false",
        "-sColorImageFilter=DCTEncode",
        "-sGrayImageFilter=DCTEncode",
        f"-sOutputFile={destination}",
        # PDFSETTINGS carries a JPEG quality of its own but the three tiers
        # barely differ on it; setting QFactor explicitly is what makes
        # "extreme" much smaller than "less" rather than marginally so.
        # ``.setpdfwrite`` used to wrap this and was removed in Ghostscript 10 —
        # setdistillerparams works on its own. /ColorImageDict, not the ACS one:
        # the ACS dictionaries only apply while auto filtering is on.
        "-c",
        _distiller_params(_qfactor(preset.jpeg_quality)),
        # Everything after -f is a file to process, so the input goes last.
        "-f",
        str(source),
    ]


def _distiller_params(qfactor: float) -> str:
    sampling = f"/QFactor {qfactor} /Blend 1 /HSamples [2 1 1 2] /VSamples [2 1 1 2]"
    return (
        f"<< /ColorImageDict << {sampling} >> "
        f"/GrayImageDict << {sampling} >> >> setdistillerparams"
    )


def _qfactor(quality: int) -> float:
    """Ghostscript's QFactor from a familiar 0-100 JPEG quality.

    QFactor scales the quantisation tables: 0.1 is near-lossless, 1.0 is the
    distiller's "medium", and it climbs from there. Quality 85 → 0.3,
    65 → 0.75, 40 → 1.5.
    """
    return round(max(0.05, min(4.0, (100 - quality) / 40)), 2)


async def _run_ghostscript(source: Path, destination: Path, preset: Preset) -> bool:
    result = await run(
        _ghostscript(source, destination, preset),
        operation="compress",
        check=False,
    )
    if result.ok and destination.exists() and destination.stat().st_size > 0:
        return True
    if mentions_password(result.output):
        raise encrypted_input()
    logger.error("ghostscript failed (%s): %s", result.returncode, result.output)
    return False


async def _run_rewrite(source: Path, destination: Path, preset: Preset) -> bool:
    """Shorten every content stream, then let qpdf tighten the file structure."""
    async with job_slot("compress"):
        # Started after the slot is in hand, so time spent queueing does not come
        # out of the work's budget — the same deal a subprocess gets from `run`.
        deadline = time.monotonic() + timeout_for("compress")
        rebuilt = await asyncio.to_thread(
            streams.rebuild,
            source,
            destination,
            precision=preset.precision,
            deadline=deadline,
        )
    if not rebuilt:
        return False

    # pypdf writes a plain cross-reference table and one object per entry. This
    # packs the objects that are not streams into object streams; it is under a
    # second even on a 50 MB file, and never touches the stream data we just
    # spent the bulk of the request compressing.
    packed = destination.with_name(f"{destination.stem}-packed.pdf")
    result = await run(
        ["qpdf", "--object-streams=generate", str(destination), str(packed)],
        operation="compress",
        check=False,
    )
    if result.ok and packed.exists() and packed.stat().st_size < destination.stat().st_size:
        packed.replace(destination)
    else:
        packed.unlink(missing_ok=True)
    return True


async def compress_one(upload: SavedUpload, workspace: Path, level: str) -> OutputFile:
    """Compress one file, returning the original when nothing beat it."""
    ensure_readable(upload.path)
    preset = PRESETS[level]
    destination = workspace / f"{upload.path.stem}-compressed.pdf"

    measured = await asyncio.to_thread(streams.survey, upload.path)
    candidates: list[Path] = []

    wants_rewrite = measured is None or measured.content_share >= CONTENT_SHARE_FLOOR
    wants_ghostscript = measured is None or measured.image_share >= IMAGE_SHARE_FLOOR
    if not wants_rewrite and not wants_ghostscript:
        # Neither pictures nor drawing: the weight is fonts, attachments or
        # metadata. Ghostscript is the only one of the two that touches those.
        wants_ghostscript = True

    if wants_rewrite:
        rewritten = workspace / f"{upload.path.stem}-rewritten.pdf"
        if await _run_rewrite(upload.path, rewritten, preset):
            candidates.append(rewritten)

    if wants_ghostscript:
        distilled = workspace / f"{upload.path.stem}-gs.pdf"
        if await _run_ghostscript(upload.path, distilled, preset):
            candidates.append(distilled)

    if not candidates:
        raise HTTPException(status_code=500, detail="compress_failed")

    best = min(candidates, key=lambda path: path.stat().st_size)
    # A PDF that is already lean regularly comes back bigger from either route.
    # Handing that back would be a worse file for the same wait, so the upload
    # wins and the caller is told the size did not move.
    if best.stat().st_size >= upload.size:
        logger.info("compress: no gain on %s, returning original", upload.original_name)
        shutil.copyfile(upload.path, destination)
    else:
        best.replace(destination)

    # These live in a tmpfs, which is RAM. A batch of twenty files should not
    # keep every runner-up until the request ends.
    for candidate in candidates:
        if candidate != destination:
            candidate.unlink(missing_ok=True)

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
