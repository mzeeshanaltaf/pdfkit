"""Extract the images embedded in a PDF: poppler's pdfimages, then Pillow → JPEG."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from fastapi import HTTPException
from PIL import Image

from app.deps import SavedUpload, UploadBatch
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services import progress
from app.services.responses import OutputFile, build_archive, sanitise_archive_name
from app.services.runner import run, sanitise

logger = logging.getLogger(__name__)

QUALITIES = {"normal": 80, "high": 92}
DEFAULT_QUALITY = "normal"

# Spacers, rules and one-pixel tracking images are embedded images too. Nobody
# wants 300 of them in the zip, so anything smaller than this is dropped.
MIN_EDGE_PX = 16

# A hostile PDF can embed a very large number of images; stop before we spend
# the whole job timeout writing JPEGs nobody asked for.
MAX_IMAGES_PER_FILE = 500

NO_IMAGES = "no_images_found"


def validate_quality(quality: str | None) -> str:
    chosen = (quality or DEFAULT_QUALITY).strip().lower()
    if chosen not in QUALITIES:
        raise HTTPException(
            status_code=400,
            detail=f"quality must be one of {', '.join(QUALITIES)}.",
        )
    return chosen


def _to_jpeg(source: Path, destination: Path, quality: int) -> bool:
    """Convert one extracted bitmap to JPEG. False if it is too small to keep."""
    with Image.open(source) as image:
        if min(image.size) < MIN_EDGE_PX:
            return False
        # JPEG has no alpha and no palette or CMYK-with-transparency, so
        # everything is flattened onto white first.
        if image.mode in ("RGBA", "LA") or (
            image.mode == "P" and "transparency" in image.info
        ):
            flattened = Image.new("RGB", image.size, (255, 255, 255))
            rgba = image.convert("RGBA")
            flattened.paste(rgba, mask=rgba.split()[-1])
            prepared = flattened
        elif image.mode != "RGB":
            prepared = image.convert("RGB")
        else:
            prepared = image
        prepared.save(destination, "JPEG", quality=quality, optimize=True)
    return True


def _convert_all(raw: list[Path], workspace: Path, stem: str, quality: int) -> list[Path]:
    """Blocking Pillow work — called via ``asyncio.to_thread``."""
    kept: list[Path] = []
    for source in raw:
        destination = workspace / f"{stem}-image-{len(kept) + 1:03d}.jpg"
        try:
            if _to_jpeg(source, destination, quality):
                kept.append(destination)
        except OSError as error:
            # One unreadable bitmap should not sink an otherwise good extraction.
            logger.warning("skipping unreadable image %s: %s", source.name, error)
        finally:
            source.unlink(missing_ok=True)
    return kept


async def extract_one(
    upload: SavedUpload, raw_dir: Path, workspace: Path, quality: int
) -> list[Path]:
    ensure_readable(upload.path)
    prefix = raw_dir / upload.path.stem
    result = await run(
        ["pdfimages", "-png", str(upload.path), str(prefix)],
        operation="images",
        check=False,
    )
    if not result.ok:
        if mentions_password(result.output):
            raise encrypted_input()
        logger.error("pdfimages failed (%s): %s", result.returncode, result.output)
        raise HTTPException(
            status_code=500, detail=sanitise(result.output) or "extract_failed"
        )

    raw = sorted(raw_dir.glob(f"{upload.path.stem}-*.png"))[:MAX_IMAGES_PER_FILE]
    return await asyncio.to_thread(
        _convert_all, raw, workspace, Path(upload.original_name).stem, quality
    )


async def extract_images(batch: UploadBatch, quality: str) -> OutputFile:
    """Always a zip: extraction usually yields many images, never a predictable one."""
    workspace = batch.workspace("out")
    raw_dir = batch.workspace("raw")
    level = QUALITIES[quality]

    publisher = progress.current()
    jpegs: list[Path] = []
    for index, upload in enumerate(batch.files, start=1):
        await progress.stop_if_cancelled()
        publisher.file(
            index, len(batch.files), upload.original_name, "Looking for images"
        )
        jpegs += await extract_one(upload, raw_dir, workspace, level)

    if not jpegs:
        raise HTTPException(status_code=422, detail=NO_IMAGES)

    entries = [OutputFile(path=path, download_name=path.name, media_type="image/jpeg") for path in jpegs]
    archive = build_archive(entries, batch.directory / "images.zip")
    name = (
        f"{Path(batch.single.original_name).stem}-images.zip"
        if len(batch.files) == 1
        else "pdfkit-images.zip"
    )
    return OutputFile(
        path=archive,
        download_name=sanitise_archive_name(name),
        media_type="application/zip",
    )
