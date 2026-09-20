"""POST /ocr and GET /ocr/languages — searchable text layers via OCRmyPDF.

Two routers, not one. ``GET /ocr/languages`` is fetched by the language picker
on page load, before the user has done anything a token would be minted for,
and it answers from a process-lifetime cache of ``tesseract --list-langs`` —
effectively a static list. It is therefore mounted open, while ``POST /ocr``
goes through the full protected stack. See ``app.routers.__init__``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.responses import FileResponse

from app.deps import upload_batch
from app.services.ocr import available_languages, ocr, validate_languages
from app.services.responses import file_response

router = APIRouter(tags=["ocr"])
languages_router = APIRouter(tags=["ocr"])


@languages_router.get("/ocr/languages")
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
