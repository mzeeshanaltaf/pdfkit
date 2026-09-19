"""Interpreting native tool failures that the user can actually act on."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# Ghostscript, qpdf and pikepdf each word it differently, but every one of them
# says "password" when the input is encrypted and we did not supply the key.
_PASSWORD_HINTS = (
    "invalid password",
    "requires a password",
    "password required",
    "incorrect password",
    "encrypted with a password",
    "is encrypted",
    "no password supplied",
)

PASSWORD_REQUIRED = "password_required"
WRONG_PASSWORD = "wrong_password"


def mentions_password(output: str) -> bool:
    """True when a tool refused the input because it is encrypted."""
    lowered = output.lower()
    return any(hint in lowered for hint in _PASSWORD_HINTS)


def encrypted_input() -> HTTPException:
    """The caller handed us an encrypted PDF for a tool that cannot read one."""
    return HTTPException(status_code=422, detail=PASSWORD_REQUIRED)


def ensure_readable(path: Path) -> None:
    """Reject an encrypted input before any native tool touches it.

    This is not belt-and-braces. Ghostscript 10 exits **0** on a PDF it cannot
    decrypt and writes a plausible-looking but empty output, so a caller who
    compressed a locked file would silently receive a blank document. pypdf
    gives us the answer in milliseconds, before that can happen.

    A file that is encrypted but opens with the empty user password (owner
    password only) is fine: every tool here can read one.
    """
    try:
        reader = PdfReader(str(path))
        if not reader.is_encrypted:
            return
        opens_empty = bool(reader.decrypt(""))
    except Exception as error:  # noqa: BLE001 — deliberately broad, see below
        # Anything but a clean "yes, encrypted" means we learned nothing. pypdf
        # raises a wide and undocumented spread of errors on damaged files
        # (PyPdfError, but also ValueError, KeyError, struct.error…), and qpdf
        # and Ghostscript are far more tolerant than it is. Failing the request
        # here would reject files the real tool handles fine, so we step aside
        # and let it have its go.
        logger.info("pypdf could not pre-read %s: %s", path.name, error)
        return

    if not opens_empty:
        raise encrypted_input()
