"""POST /compress — Ghostscript compression at three quality levels."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.responses import FileResponse

from app.deps import upload_batch
from app.services.compress import compress, validate_level
from app.services.responses import file_response

router = APIRouter(tags=["compress"])


@router.post("/compress")
async def compress_endpoint(
    files: Annotated[list[UploadFile], File()],
    level: Annotated[str | None, Form()] = None,
) -> FileResponse:
    chosen = validate_level(level)
    async with upload_batch(files) as batch:
        result = await compress(batch, chosen)
        return file_response(
            result.outputs,
            batch,
            archive_name="pdfkit-compressed.zip",
            # Lets the UI show "4.2 MB → 1.1 MB" without re-measuring the upload.
            headers={
                "X-Original-Size": str(result.original_size),
                "X-Result-Size": str(result.result_size),
            },
        )
