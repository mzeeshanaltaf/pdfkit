"""POST /convert/word and /convert/markdown — PDF into an editable document."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from starlette.responses import FileResponse

from app.deps import upload_batch
from app.services.markdown import to_markdown
from app.services.ocr import validate_languages, validate_ocr_mode
from app.services.responses import file_response
from app.services.word import to_word

router = APIRouter(tags=["convert"])


@router.post("/convert/word")
async def word_endpoint(
    files: Annotated[list[UploadFile], File()],
    ocr: Annotated[str | None, Form()] = None,
    languages: Annotated[str | None, Form()] = None,
) -> FileResponse:
    # Defaults to off: pdf2docx produces a document either way, so paying for an
    # OCR pass on a born-digital PDF should be something the caller asks for.
    mode = validate_ocr_mode(ocr, default="off")
    codes = await validate_languages(languages)
    async with upload_batch(files) as batch:
        outputs = await to_word(batch, mode, codes)
        return file_response(outputs, batch, archive_name="pdfkit-word.zip")


@router.post("/convert/markdown")
async def markdown_endpoint(
    files: Annotated[list[UploadFile], File()],
    ocr: Annotated[str | None, Form()] = None,
    languages: Annotated[str | None, Form()] = None,
) -> FileResponse:
    # Defaults to auto, unlike Word: anydoc refuses a scanned page outright, so
    # defaulting this off would turn the commonest scan into a pointless error.
    mode = validate_ocr_mode(ocr, default="auto")
    codes = await validate_languages(languages)
    async with upload_batch(files) as batch:
        outputs = await to_markdown(batch, mode, codes)
        return file_response(outputs, batch, archive_name="pdfkit-markdown.zip")
