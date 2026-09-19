"""POST /ocr and GET /ocr/languages — searchable text layers via OCRmyPDF."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.responses import FileResponse

from app.deps import upload_batch
from app.services.ocr import available_languages, ocr, validate_languages
from app.services.responses import file_response

router = APIRouter(tags=["ocr"])


@router.get("/ocr/languages")
async def languages_endpoint() -> list[dict[str, str]]:
    """The Tesseract models installed in this image, for the language picker."""
    return [
        {"code": language.code, "name": language.name}
        for language in await available_languages()
    ]


@router.post("/ocr")
async def ocr_endpoint(
    files: Annotated[list[UploadFile], File()],
    languages: Annotated[str | None, Form()] = None,
) -> FileResponse:
    codes = await validate_languages(languages)
    async with upload_batch(files) as batch:
        outputs = await ocr(batch, codes)
        return file_response(outputs, batch, archive_name="pdfkit-ocr.zip")
