"""Encrypt PDFs with qpdf (AES-256)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

from app.deps import SavedUpload, UploadBatch
from app.services.errors import encrypted_input, ensure_readable, mentions_password
from app.services.passwords import argument_file
from app.services.responses import OutputFile, derive_name
from app.services.runner import run, sanitise

logger = logging.getLogger(__name__)

# qpdf exits 0 on success and 3 when it succeeded but emitted warnings (a
# damaged-but-recoverable input, say). Both produce a usable output file.
_ACCEPTABLE = (0, 3)


async def protect_one(
    upload: SavedUpload, workspace: Path, secrets: Path, password: str, index: int
) -> OutputFile:
    ensure_readable(upload.path)
    destination = workspace / f"{upload.path.stem}-protected.pdf"

    # The passwords go in an argument file rather than argv: qpdf 11.3 only
    # takes them positionally, and argv is visible to anything that can run ps.
    arguments = argument_file(
        secrets,
        [
            "--encrypt",
            password,
            password,
            "256",
            "--",
            str(upload.path),
            str(destination),
        ],
        name=f"protect-{index:02d}.args",
    )

    result = await run(["qpdf", f"@{arguments}"], operation="protect", check=False)
    if result.returncode not in _ACCEPTABLE or not destination.exists():
        # An input that is already encrypted cannot be read, let alone re-encrypted.
        if mentions_password(result.output):
            raise encrypted_input()
        logger.error("qpdf encrypt failed (%s): %s", result.returncode, result.output)
        raise HTTPException(
            status_code=500, detail=sanitise(result.output) or "protect_failed"
        )

    return OutputFile(
        path=destination,
        download_name=derive_name(upload.original_name, "protected"),
    )


async def protect(batch: UploadBatch, password: str) -> list[OutputFile]:
    workspace = batch.workspace("out")
    secrets = batch.workspace("secrets")
    return [
        await protect_one(upload, workspace, secrets, password, index)
        for index, upload in enumerate(batch.files)
    ]
