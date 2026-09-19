"""Add a searchable text layer with OCRmyPDF (Tesseract under the hood)."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.config import MAX_OCR_LANGUAGES
from app.deps import SavedUpload, UploadBatch
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services.responses import OutputFile, derive_name
from app.services.runner import run, sanitise

logger = logging.getLogger(__name__)

# ocrmypdf's documented exit codes; only the ones we can act on are named.
EXIT_OK = 0
EXIT_ALREADY_OCR = 6
EXIT_ENCRYPTED = 8

# Tesseract ships these alongside the real languages: orientation/script
# detection and a maths-symbol model. Neither is something to offer a user.
_NOT_LANGUAGES = {"osd", "equ"}
_LANG_CODE = re.compile(r"^[a-z]{3}(?:_[A-Za-z]+)*$")

# Display names for the models Tesseract commonly ships. Anything not listed
# falls back to its own code, which is better than hiding a working language.
LANGUAGE_NAMES: dict[str, str] = {
    "afr": "Afrikaans",
    "ara": "Arabic",
    "ben": "Bengali",
    "bul": "Bulgarian",
    "cat": "Catalan",
    "ces": "Czech",
    "chi_sim": "Chinese (Simplified)",
    "chi_tra": "Chinese (Traditional)",
    "dan": "Danish",
    "deu": "German",
    "ell": "Greek",
    "eng": "English",
    "est": "Estonian",
    "fas": "Persian",
    "fin": "Finnish",
    "fra": "French",
    "heb": "Hebrew",
    "hin": "Hindi",
    "hrv": "Croatian",
    "hun": "Hungarian",
    "ind": "Indonesian",
    "isl": "Icelandic",
    "ita": "Italian",
    "jpn": "Japanese",
    "kor": "Korean",
    "lav": "Latvian",
    "lit": "Lithuanian",
    "msa": "Malay",
    "nld": "Dutch",
    "nor": "Norwegian",
    "pol": "Polish",
    "por": "Portuguese",
    "ron": "Romanian",
    "rus": "Russian",
    "slk": "Slovak",
    "slv": "Slovenian",
    "spa": "Spanish",
    "srp": "Serbian",
    "swe": "Swedish",
    "tha": "Thai",
    "tur": "Turkish",
    "ukr": "Ukrainian",
    "urd": "Urdu",
    "vie": "Vietnamese",
}

DEFAULT_LANGUAGE = "eng"


@dataclass(frozen=True, slots=True)
class Language:
    code: str
    name: str


_cache: list[Language] | None = None
_cache_lock = asyncio.Lock()


def _parse_langs(output: str) -> list[Language]:
    codes = {
        line.strip()
        for line in output.splitlines()
        if _LANG_CODE.match(line.strip()) and line.strip() not in _NOT_LANGUAGES
    }
    languages = [Language(code=code, name=LANGUAGE_NAMES.get(code, code)) for code in codes]
    # Ordered by display name, not by code, because the picker renders this list as it
    # arrives: sorting by code puts "German" above "English". The code breaks ties so the
    # order stays stable for any model that falls back to showing its own code as a name.
    return sorted(languages, key=lambda language: (language.name.casefold(), language.code))


async def available_languages(refresh: bool = False) -> list[Language]:
    """The installed Tesseract models. Cached — the list only changes on redeploy."""
    global _cache
    async with _cache_lock:
        if _cache is None or refresh:
            result = await run(
                ["tesseract", "--list-langs"], operation="probe", check=False
            )
            if not result.ok:
                logger.error("tesseract --list-langs failed: %s", result.output)
                raise HTTPException(status_code=503, detail="ocr_unavailable")
            _cache = _parse_langs(result.output)
        return _cache


async def validate_languages(raw: str | None) -> list[str]:
    """Parse the comma-separated ``languages`` field against what is installed."""
    requested = [part.strip() for part in (raw or "").split(",") if part.strip()]
    if not requested:
        requested = [DEFAULT_LANGUAGE]

    # De-duplicate but keep the caller's order: Tesseract weights the first.
    ordered = list(dict.fromkeys(requested))
    if len(ordered) > MAX_OCR_LANGUAGES:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_OCR_LANGUAGES} languages can be used at once.",
        )

    installed = {language.code for language in await available_languages()}
    unknown = [code for code in ordered if code not in installed]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported OCR language: {', '.join(unknown)}.",
        )
    return ordered


OCR_MODES = ("off", "auto")


def validate_ocr_mode(mode: str | None, *, default: str) -> str:
    """The ``ocr`` field shared by the two conversion tools.

    ``off`` never runs OCR. ``auto`` runs OCRmyPDF with ``--skip-text``, which
    leaves pages that already carry text alone — so it means "read the pages
    that need reading", not "re-OCR the document".
    """
    chosen = (mode or default).strip().lower()
    if chosen not in OCR_MODES:
        raise HTTPException(
            status_code=400, detail=f"ocr must be one of {', '.join(OCR_MODES)}."
        )
    return chosen


async def ocr_to_path(
    source: Path, destination: Path, scratch: Path, languages: list[str]
) -> Path:
    """Add a text layer to ``source``, writing the result to ``destination``.

    The OCR step on its own, so the tools that need a readable document before
    they can do their real job — PDF to Word and PDF to Markdown — get exactly
    the same behaviour as the OCR tool rather than a second implementation of it.
    """
    result = await run(
        [
            "ocrmypdf",
            "-l",
            "+".join(languages),
            # Pages that already carry text are passed through untouched rather
            # than double-layered, which is what makes this safe on mixed PDFs.
            "--skip-text",
            "--optimize",
            "1",
            "--quiet",
            str(source),
            str(destination),
        ],
        operation="ocr",
        check=False,
        # Keep OCRmyPDF's own scratch files on the request's tmpfs so they are
        # removed with the batch instead of accumulating in the container.
        env={"TMPDIR": str(scratch)},
    )

    if result.returncode == EXIT_ENCRYPTED or mentions_password(result.output):
        raise encrypted_input()
    if result.returncode not in (EXIT_OK, EXIT_ALREADY_OCR) or not destination.exists():
        logger.error("ocrmypdf failed (%s): %s", result.returncode, result.output)
        raise HTTPException(
            status_code=500, detail=sanitise(result.output) or "ocr_failed"
        )
    return destination


async def ocr_one(
    upload: SavedUpload, workspace: Path, scratch: Path, languages: list[str]
) -> OutputFile:
    ensure_readable(upload.path)
    destination = await ocr_to_path(
        upload.path, workspace / f"{upload.path.stem}-ocr.pdf", scratch, languages
    )
    return OutputFile(
        path=destination, download_name=derive_name(upload.original_name, "ocr")
    )


async def ocr(batch: UploadBatch, languages: list[str]) -> list[OutputFile]:
    workspace = batch.workspace("out")
    scratch = batch.workspace("ocr-tmp")
    return [await ocr_one(upload, workspace, scratch, languages) for upload in batch.files]
