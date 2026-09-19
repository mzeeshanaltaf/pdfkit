"""Remove PDF encryption with qpdf."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import HTTPException

from app.deps import SavedUpload, UploadBatch
from app.services.errors import PASSWORD_REQUIRED, WRONG_PASSWORD, mentions_password
from app.services.passwords import password_file
from app.services.responses import OutputFile, derive_name
from app.services.runner import run, sanitise

logger = logging.getLogger(__name__)

_ACCEPTABLE = (0, 3)


async def unlock_one(
    upload: SavedUpload, workspace: Path, secrets: Path, password: str | None, index: int
) -> OutputFile:
    destination = workspace / f"{upload.path.stem}-unlocked.pdf"

    command = ["qpdf", "--decrypt"]
    if password is not None:
        # --password-file keeps the password out of argv; qpdf reads the file itself.
        secret = password_file(secrets, password, name=f"unlock-{index:02d}.pw")
        command.append(f"--password-file={secret}")
    command += [str(upload.path), str(destination)]

    result = await run(command, operation="unlock", check=False)
    if result.returncode in _ACCEPTABLE and destination.exists():
        return OutputFile(
            path=destination,
            download_name=derive_name(upload.original_name, "unlocked"),
        )

    if mentions_password(result.output):
        # With no password we have only tried the empty one, which is how an
        # owner-password-only file opens; a failure there means a real user
        # password exists and the UI should ask for it.
        detail = WRONG_PASSWORD if password is not None else PASSWORD_REQUIRED
        raise HTTPException(status_code=422, detail=detail)

    logger.error("qpdf decrypt failed (%s): %s", result.returncode, result.output)
    raise HTTPException(
        status_code=500, detail=sanitise(result.output) or "unlock_failed"
    )


async def unlock(batch: UploadBatch, password: str | None) -> list[OutputFile]:
    workspace = batch.workspace("out")
    secrets = batch.workspace("secrets")
    return [
        await unlock_one(upload, workspace, secrets, password, index)
        for index, upload in enumerate(batch.files)
    ]
