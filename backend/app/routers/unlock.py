"""POST /unlock — strip encryption, with or without a password."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.responses import FileResponse

from app.deps import upload_batch
from app.services.passwords import validate_password
from app.services.responses import file_response
from app.services.unlock import unlock

router = APIRouter(tags=["unlock"])


@router.post("/unlock")
async def unlock_endpoint(
    files: Annotated[list[UploadFile], File()],
    password: Annotated[str | None, Form()] = None,
) -> FileResponse:
    # Optional here: a file locked with an owner password only opens with the
    # empty user password, so the first attempt is worth making without one.
    secret = validate_password(password, required=False)
    async with upload_batch(files) as batch:
        outputs = await unlock(batch, secret)
        return file_response(outputs, batch, archive_name="pdfkit-unlocked.zip")
