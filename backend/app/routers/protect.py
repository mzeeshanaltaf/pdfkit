"""POST /protect — AES-256 encryption with a user-supplied password."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.responses import FileResponse

from app.deps import upload_batch
from app.services.passwords import validate_password
from app.services.protect import protect
from app.services.responses import file_response

router = APIRouter(tags=["protect"])


@router.post("/protect")
async def protect_endpoint(
    files: Annotated[list[UploadFile], File()],
    password: Annotated[str | None, Form()] = None,
) -> FileResponse:
    # Declared optional so that an absent field and an empty one both come out
    # as our own 400 password_missing, rather than one of them arriving as
    # FastAPI's 422 validation envelope, which the UI would have to parse twice.
    secret = validate_password(password)
    assert secret is not None  # validate_password raises when required and empty
    async with upload_batch(files) as batch:
        outputs = await protect(batch, secret)
        return file_response(outputs, batch, archive_name="pdfkit-protected.zip")
