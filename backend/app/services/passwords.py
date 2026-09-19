"""Getting a password to qpdf without it ever appearing in the process list.

``ps`` is world-readable inside a container, so a password passed as a bare
argv entry is readable by anything else on the box for the life of the process.
qpdf offers two ways around that and we use both:

* ``--password-file=FILE`` for the *input* password (unlock);
* ``@FILE`` argument files for everything else (protect), because qpdf 11.3 —
  the version Debian bookworm ships — only accepts the encryption passwords
  positionally.

Both files live inside the request's temp directory, are written 0600, and go
away with the rest of the batch when the response has been sent.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

MAX_PASSWORD_LENGTH = 512


def validate_password(password: str | None, *, required: bool = True) -> str | None:
    """Reject passwords we cannot pass safely, or that qpdf will not accept."""
    if password is None or password == "":
        if required:
            raise HTTPException(status_code=400, detail="password_missing")
        return None
    if len(password) > MAX_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail="password_too_long")
    # An argument file is line-delimited, so a newline in a password would let
    # the caller inject extra qpdf arguments. Control characters are worthless
    # in a password anyway — no viewer's password box can produce one.
    if any(character in password for character in "\r\n\x00"):
        raise HTTPException(status_code=400, detail="password_invalid")
    return password


def write_secret_file(directory: Path, name: str, contents: str) -> Path:
    """Write ``contents`` to a 0600 file and return its path."""
    path = directory / name
    # Open with the mode up front; writing then chmod'ing leaves a window where
    # the file is world-readable.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as sink:
        sink.write(contents)
    return path


def password_file(directory: Path, password: str, name: str = "pw") -> Path:
    """A file for ``qpdf --password-file=`` — the password, with no trailing newline.

    qpdf strips a single trailing newline itself, but a password that genuinely
    ends in whitespace would then be mangled, so we write the bytes exactly.
    """
    return write_secret_file(directory, name, password)


def argument_file(directory: Path, arguments: list[str], name: str = "args") -> Path:
    """A file for ``qpdf @FILE`` — one argument per line."""
    return write_secret_file(directory, name, "\n".join(arguments) + "\n")
