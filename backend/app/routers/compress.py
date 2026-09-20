"""POST /compress — Ghostscript compression at three quality levels."""

from __future__ import annotations

import json
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
        headers = {
            # Lets the UI show "4.2 MB → 1.1 MB" without re-measuring the upload.
            "X-Original-Size": str(result.original_size),
            "X-Result-Size": str(result.result_size),
        }
        if len(result.files) > 1:
            # Per-file breakdown for a batch, so the UI can show each file's own
            # saving rather than just the total. json.dumps escapes to plain
            # ASCII by default, which is what a header value requires.
            headers["X-File-Stats"] = json.dumps(
                [
                    {
                        "name": stat.name,
                        "originalSize": stat.original_size,
                        "resultSize": stat.result_size,
                    }
                    for stat in result.files
                ]
            )
        return file_response(
            result.outputs,
            batch,
            archive_name="pdfkit-compressed.zip",
            headers=headers,
        )
