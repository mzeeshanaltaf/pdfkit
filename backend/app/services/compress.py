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

*Fonts.* Word embeds font programs whole. One emoji in a two-page document
drags in all 7.7 MB of Segoe UI Emoji, and Ghostscript's subsetter cannot cut
it down because the bulk is a colour table it does not understand. That is
``app.services.fonts``, and it runs first, because a smaller set of fonts is a
better input for either of the others.

So we survey the document, run only the candidates its shape justifies, and keep
the smallest result. If nothing beats the upload we return the upload, and the
response headers report equal sizes so the UI can say so honestly.
"""

from __future__ import annotations

import asyncio
import logging
import re
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader

from app.config import timeout_for
from app.deps import SavedUpload, UploadBatch
from app.services import fonts, progress, streams
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services.responses import OutputFile, derive_name
from app.services.runner import job_slot, run

logger = logging.getLogger(__name__)

LEVELS = ("extreme", "recommended", "less")
DEFAULT_LEVEL = "recommended"

# Below these shares of the file, a strategy cannot win enough to be worth the
# seconds it costs. A scan is ~97% image bytes; a Print-To-PDF document is ~99%
# content-stream bytes; a Word document with an emoji in it is ~97% font bytes.
# The middle is rare, and there more than one candidate runs.
IMAGE_SHARE_FLOOR = 0.10
CONTENT_SHARE_FLOOR = 0.10
FONT_SHARE_FLOOR = 0.10

# How many pages are rasterised to prove font subsetting changed nothing. Enough
# to catch a systematic mistake without rendering a whole book; the first and
# last page are always among them.
VERIFY_PAGES = 8
VERIFY_DPI = 72
# Rasterising is not bit-exact across runs of a different font program even when
# it is correct, so allow a hair. A genuinely dropped glyph moves far more than
# this: the en-dash bug that prompted the check moved 0.08% of the page.
VERIFY_TOLERANCE = 0.0002


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


@dataclass(frozen=True, slots=True)
class FileStat:
    """Before/after size for one file in the batch, keyed by its original name."""

    name: str
    original_size: int
    result_size: int


@dataclass(slots=True)
class CompressionResult:
    outputs: list[OutputFile]
    original_size: int
    result_size: int
    files: list[FileStat]


# How much of one file's progress each step is worth, in order. A *fixed*
# cursor over the biggest plan a file could get, decided before we know which
# steps will actually run - because `wants_rewrite` and `wants_ghostscript` are
# only known after the font pass, and re-normalising then would make the bar
# jump backwards. A forward jump reads as "that step was quick"; a backward one
# reads as broken.
#
# Two of these are genuinely smooth and they are the two that dominate: rewrite
# on a vector document, ghostscript on a scan. Survey and verify are single
# lumps, and fonts is lumpy for the reason documented in `fonts.subset`.
STEP_WEIGHTS: tuple[tuple[str, str, int], ...] = (
    ("survey", "Looking at the document", 5),
    ("fonts", "Subsetting the fonts", 20),
    ("verify", "Checking nothing moved", 15),
    ("rewrite", "Rewriting the drawing", 25),
    ("ghostscript", "Recompressing the images", 35),
)

# Below this gap a publish is skipped. A twenty-file request can spawn four
# hundred subprocesses and tick a content-stream loop tens of thousands of
# times; the throttle is what keeps that from becoming the workload.
MIN_PUBLISH_INTERVAL = 0.25
MIN_PUBLISH_DELTA = 1.0


class _Cursor:
    """Where one file is, as a 0-100 number, across a plan of skippable steps."""

    def __init__(self, publisher: progress.Publisher) -> None:
        self._publisher = publisher
        self._base = 0.0
        self._span = 0.0
        self._offsets: dict[str, float] = {}
        running = 0.0
        for name, _label, weight in STEP_WEIGHTS:
            self._offsets[name] = running
            running += weight

    def start(self, name: str) -> None:
        """Enter a step, fast-forwarding over any that were skipped."""
        label, weight = next(
            (text, weight) for key, text, weight in STEP_WEIGHTS if key == name
        )
        self._base = self._offsets[name]
        self._span = float(weight)
        self._publisher.step(label, self._base)

    def at(self, fraction: float) -> None:
        """Position inside the current step, as 0-1 of it."""
        self._publisher.percent(self._base + self._span * max(0.0, min(1.0, fraction)))

    def done(self) -> None:
        self._base += self._span
        self._span = 0.0
        self._publisher.percent(self._base)


def _threaded_reporter(cursor: _Cursor) -> Callable[[int, int], None]:
    """An ``on_step`` for work running on an ``asyncio.to_thread`` worker.

    The callback fires on that worker, which must not touch the loop - hence
    ``call_soon_threadsafe`` onto the loop captured here, while we are still on
    it.
    """
    loop = asyncio.get_running_loop()
    last = [0.0, -1.0]  # when we last published, and at what percent

    def on_step(done: int, total: int) -> None:
        if total <= 0:
            return
        percent = done / total * 100
        now = time.monotonic()
        if (
            done < total
            and now - last[0] < MIN_PUBLISH_INTERVAL
            and percent - last[1] < MIN_PUBLISH_DELTA
        ):
            return
        last[0], last[1] = now, percent
        loop.call_soon_threadsafe(cursor.at, percent / 100)

    return on_step


# Ghostscript announces the page count once and then names each page as it
# finishes. Both go to stdout, which is free because the PDF goes to
# -sOutputFile=. This is the whole reason -dQUIET is gone from the command line.
_GS_TOTAL = re.compile(r"^Processing pages \d+ through (\d+)\.")
_GS_PAGE = re.compile(r"^Page (\d+)")


def _ghostscript_reporter(cursor: _Cursor) -> Callable[[str, str], None]:
    total = [0]

    def on_line(stream: str, line: str) -> None:
        if stream != "stdout":
            return
        text = line.strip()
        if match := _GS_TOTAL.match(text):
            total[0] = int(match.group(1))
        elif (match := _GS_PAGE.match(text)) and total[0] > 0:
            cursor.at(int(match.group(1)) / total[0])

    return on_line


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
        # No -dQUIET: its per-page "Page N" lines on stdout are the only honest
        # progress signal on a scan, which is the document class this route
        # exists for. tests/test_gs_progress.py is there so a future tidy-up
        # cannot put the flag back without a failing test.
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


async def _run_ghostscript(
    source: Path, destination: Path, preset: Preset, cursor: _Cursor | None = None
) -> bool:
    result = await run(
        _ghostscript(source, destination, preset),
        operation="compress",
        check=False,
        on_line=_ghostscript_reporter(cursor) if cursor is not None else None,
    )
    if result.ok and destination.exists() and destination.stat().st_size > 0:
        return True
    if mentions_password(result.output):
        raise encrypted_input()
    logger.error("ghostscript failed (%s): %s", result.returncode, result.output)
    return False


async def _parses_cleanly(source: Path) -> bool:
    """True when poppler reads every content stream without complaint.

    ``pdftotext`` walks the operators, not just the text, so it is the cheapest
    thing that will notice an operand we mangled into an operator. Milliseconds
    on an ordinary document; a few seconds on one with a hundred megabytes of
    vector drawing in it, which is why the caller only reaches for it once.
    """
    result = await run(
        ["pdftotext", str(source), "-"],
        operation="compress",
        check=False,
    )
    return result.ok and "Syntax Error" not in result.output


async def _run_rewrite(
    source: Path, destination: Path, preset: Preset, cursor: _Cursor | None = None
) -> bool:
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
            on_step=_threaded_reporter(cursor) if cursor is not None else None,
        )
    if not rebuilt:
        return False

    # The rewriter edits drawing operators as raw bytes. That is the most
    # dangerous thing this service does, so the result is read back before it is
    # allowed to compete: a number turned into an operator breaks every operand
    # after it, and the file still opens, so nothing else would notice. The
    # source is only parsed when the candidate looks bad, which keeps the cost
    # at one pass on the documents where a pass is expensive.
    if not await _parses_cleanly(destination):
        if await _parses_cleanly(source):
            logger.error("stream rewrite broke %s; discarding it", source.name)
            destination.unlink(missing_ok=True)
            return False
        logger.info("%s already had content-stream errors; keeping the rewrite", source.name)

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


async def _render(source: Path, folder: Path, pages: Sequence[int]) -> list[Path] | None:
    """Rasterise the named pages to PNG, or None if Ghostscript's poppler friend fails."""
    folder.mkdir(parents=True, exist_ok=True)
    produced: list[Path] = []
    for number in pages:
        prefix = folder / f"p{number}"
        result = await run(
            [
                "pdftoppm", "-png", "-r", str(VERIFY_DPI),
                "-f", str(number), "-l", str(number),
                str(source), str(prefix),
            ],
            operation="probe",
            check=False,
        )
        if not result.ok:
            return None
        matches = sorted(folder.glob(f"p{number}-*.png"))
        if len(matches) != 1:
            return None
        produced.append(matches[0])
    return produced


def _same_pixels(before: Sequence[Path], after: Sequence[Path]) -> bool:
    """True when every rendered page pair is the same to within the tolerance."""
    from PIL import Image, ImageChops

    for left, right in zip(before, after, strict=True):
        with Image.open(left) as one, Image.open(right) as two:
            first, second = one.convert("RGB"), two.convert("RGB")
            if first.size != second.size:
                return False
            difference = ImageChops.difference(first, second)
            if difference.getbbox() is None:
                continue
            # Count only pixels that moved enough to be a real mark rather than
            # a rasteriser rounding one edge differently.
            histogram = difference.convert("L").histogram()
            moved = sum(histogram[16:])
            if moved > first.size[0] * first.size[1] * VERIFY_TOLERANCE:
                return False
    return True


async def _renders_the_same(before: Path, after: Path, workspace: Path) -> bool:
    """Check that subsetting the fonts did not change how the document looks.

    The scan in ``app.services.fonts`` refuses anything it does not understand,
    but a content stream it never reached would look exactly like a font with no
    glyphs in use — and the symptom of that is text quietly going blank. This is
    the check that turns a mistake there into a lost compression opportunity.
    """
    try:
        count = len(PdfReader(str(before)).pages)
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.info("cannot count pages to verify %s: %s", before.name, error)
        return False
    if count == 0:
        return False

    if count <= VERIFY_PAGES:
        pages = list(range(1, count + 1))
    else:
        # An even spread, first and last included.
        step = (count - 1) / (VERIFY_PAGES - 1)
        pages = sorted({round(1 + step * index) for index in range(VERIFY_PAGES)})

    folder = workspace / "verify"
    original = await _render(before, folder / "before", pages)
    if original is None:
        return False
    candidate = await _render(after, folder / "after", pages)
    if candidate is None:
        return False

    same = await asyncio.to_thread(_same_pixels, original, candidate)
    shutil.rmtree(folder, ignore_errors=True)
    if not same:
        logger.warning("font subsetting changed how %s renders; discarding it", before.name)
    return same


async def _run_font_subset(
    source: Path, destination: Path, workspace: Path, cursor: _Cursor | None = None
) -> bool:
    async with job_slot("compress"):
        deadline = time.monotonic() + timeout_for("compress")
        subsetted = await asyncio.to_thread(
            fonts.subset,
            source,
            destination,
            deadline=deadline,
            on_step=_threaded_reporter(cursor) if cursor is not None else None,
        )
    if not subsetted:
        return False
    if cursor is not None:
        cursor.done()
        cursor.start("verify")
    if await _renders_the_same(source, destination, workspace):
        return True
    destination.unlink(missing_ok=True)
    return False


async def compress_one(
    upload: SavedUpload, workspace: Path, level: str, cursor: _Cursor | None = None
) -> OutputFile:
    """Compress one file, returning the original when nothing beat it."""
    ensure_readable(upload.path)
    preset = PRESETS[level]
    stem = upload.path.stem
    destination = workspace / f"{stem}-compressed.pdf"

    if cursor is not None:
        cursor.start("survey")
    measured = await asyncio.to_thread(streams.survey, upload.path)
    candidates: list[Path] = []

    # Fonts first: cutting them is orthogonal to both other routes, and leaves a
    # smaller document for whichever of them runs next.
    working = upload.path
    if measured is None or measured.font_share >= FONT_SHARE_FLOOR:
        trimmed = workspace / f"{stem}-fonts.pdf"
        if cursor is not None:
            cursor.start("fonts")
        if await _run_font_subset(upload.path, trimmed, workspace, cursor):
            working = trimmed
            candidates.append(trimmed)
            measured = await asyncio.to_thread(streams.survey, trimmed)

    wants_rewrite = measured is None or measured.content_share >= CONTENT_SHARE_FLOOR
    wants_ghostscript = measured is None or measured.image_share >= IMAGE_SHARE_FLOOR
    if not wants_rewrite and not wants_ghostscript and working is upload.path:
        # No pictures, no drawing, and the fonts gave nothing: the weight is
        # elsewhere — attachments, metadata, a bloated object tree. Ghostscript
        # is the only one of the three that rebuilds all of that.
        wants_ghostscript = True

    if wants_rewrite:
        rewritten = workspace / f"{stem}-rewritten.pdf"
        if cursor is not None:
            cursor.start("rewrite")
        if await _run_rewrite(working, rewritten, preset, cursor):
            candidates.append(rewritten)

    if wants_ghostscript:
        distilled = workspace / f"{stem}-gs.pdf"
        if cursor is not None:
            cursor.start("ghostscript")
        if await _run_ghostscript(working, distilled, preset, cursor):
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
    publisher = progress.current()

    outputs: list[OutputFile] = []
    for index, upload in enumerate(batch.files, start=1):
        await progress.stop_if_cancelled()
        publisher.file(index, len(batch.files), upload.original_name)
        outputs.append(
            await compress_one(upload, workspace, level, _Cursor(publisher))
        )
    return CompressionResult(
        outputs=outputs,
        original_size=sum(upload.size for upload in batch.files),
        result_size=sum(output.path.stat().st_size for output in outputs),
        files=[
            FileStat(
                name=upload.original_name,
                original_size=upload.size,
                result_size=output.path.stat().st_size,
            )
            for upload, output in zip(batch.files, outputs, strict=True)
        ],
    )
