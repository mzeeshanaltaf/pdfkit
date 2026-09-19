"""POST /images/extract — the embedded bitmaps of a PDF, as a zip of JPEGs."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.responses import FileResponse

from app.deps import upload_batch
from app.services.images import extract_images, validate_quality
from app.services.responses import file_response

router = APIRouter(tags=["images"])


@router.post("/images/extract")
async def extract_endpoint(
    files: Annotated[list[UploadFile], File()],
    quality: Annotated[str | None, Form()] = None,
) -> FileResponse:
    chosen = validate_quality(quality)
    async with upload_batch(files) as batch:
        # Already a single zip, so file_response sends it as-is.
        archive = await extract_images(batch, chosen)
        return file_response([archive], batch, archive_name=archive.download_name)
