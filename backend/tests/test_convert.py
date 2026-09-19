"""POST /convert/word and POST /convert/markdown."""

from __future__ import annotations

import io
import re
import zipfile
from html import unescape

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader, PdfWriter

from tests.conftest import (
    GAPPED_WORDS,
    has_scalable_font,
    requires_anydoc,
    requires_pdf2docx,
    requires_tesseract,
    upload,
    zip_names,
)

_PARAGRAPH = re.compile(r"<w:p[ >].*?</w:p>", re.S)
_RUN_TEXT = re.compile(r"<w:t(?: [^>]*)?>(.*?)</w:t>", re.S)


@pytest.fixture(scope="module")
def mixed_pdf(text_pdf: bytes, scanned_pdf: bytes) -> bytes:
    """Three born-digital pages followed by one scanned page.

    The document the whole two-stage strategy exists for: anydoc can read most
    of it and refuses exactly one page.
    """
    writer = PdfWriter()
    for source in (text_pdf, scanned_pdf):
        for page in PdfReader(io.BytesIO(source)).pages:
            writer.add_page(page)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def docx_text(payload: bytes) -> str:
    """The visible text of a .docx, one line per paragraph.

    Word splits a sentence across as many runs as it likes, so the runs have
    to be concatenated — and concatenated with *nothing* between them, exactly
    as Word renders them. Stripping the markup by replacing each tag with a
    space would be simpler and would quietly invent a space at every run
    boundary, which is precisely the thing some of these tests check for.
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        document = archive.read("word/document.xml").decode("utf-8", "replace")
    paragraphs = (
        unescape("".join(_RUN_TEXT.findall(paragraph)))
        for paragraph in _PARAGRAPH.findall(document)
    )
    return "\n".join(line for line in paragraphs if line.strip())


# --- markdown ----------------------------------------------------------------


@requires_anydoc
def test_markdown_carries_the_text(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/convert/markdown", files=[upload("report.pdf", text_pdf)]
    )
    assert response.status_code == 200
    assert "report.md" in response.headers["content-disposition"]
    assert response.headers["content-type"].startswith("text/markdown")
    assert "Page 1 of 3" in response.text


@requires_anydoc
def test_markdown_refuses_a_scan_when_ocr_is_off(
    client: TestClient, scanned_pdf: bytes
) -> None:
    response = client.post(
        "/convert/markdown",
        files=[upload("scan.pdf", scanned_pdf)],
        data={"ocr": "off"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "needs_ocr"


@requires_anydoc
@requires_tesseract
@pytest.mark.skipif(
    not has_scalable_font(), reason="no scalable font, OCR input would be unreadable"
)
def test_markdown_ocrs_a_scan_and_retries(
    client: TestClient, scanned_pdf: bytes
) -> None:
    # The two-pass path: anydoc reports NeedsOcr, OCRmyPDF adds a text layer,
    # anydoc converts the result.
    response = client.post(
        "/convert/markdown",
        files=[upload("scan.pdf", scanned_pdf)],
        data={"ocr": "auto", "languages": "eng"},
    )
    assert response.status_code == 200
    assert "SCANNED" in response.text.upper()


@requires_anydoc
@requires_tesseract
@pytest.mark.skipif(
    not has_scalable_font(), reason="no scalable font, OCR input would be unreadable"
)
def test_markdown_assembles_a_mixed_document(
    client: TestClient, mixed_pdf: bytes
) -> None:
    # The page-by-page path: anydoc converts the three born-digital pages and
    # the recognised text stands in for the one it refused, so the result has
    # to carry both.
    response = client.post(
        "/convert/markdown",
        files=[upload("mixed.pdf", mixed_pdf)],
        data={"ocr": "auto", "languages": "eng"},
    )
    assert response.status_code == 200

    body = response.text
    assert "Page 1 of 3" in body, "the born-digital pages should be converted by anydoc"
    assert "Page 3 of 3" in body
    assert "SCANNED" in body.upper(), "the scanned page should come from OCR"
    assert "could not be read" not in body


@requires_anydoc
def test_markdown_reports_an_encrypted_input(
    client: TestClient, encrypted_pdf: bytes
) -> None:
    response = client.post(
        "/convert/markdown", files=[upload("locked.pdf", encrypted_pdf)]
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "password_required"


@requires_anydoc
def test_markdown_several_files_return_a_zip(
    client: TestClient, text_pdf: bytes
) -> None:
    response = client.post(
        "/convert/markdown",
        files=[upload("one.pdf", text_pdf), upload("two.pdf", text_pdf)],
    )
    assert response.headers["content-type"] == "application/zip"
    assert "pdfkit-markdown.zip" in response.headers["content-disposition"]
    assert zip_names(response.content) == ["one.md", "two.md"]


# --- word --------------------------------------------------------------------


@requires_pdf2docx
def test_word_carries_the_text(client: TestClient, text_pdf: bytes) -> None:
    response = client.post("/convert/word", files=[upload("report.pdf", text_pdf)])
    assert response.status_code == 200
    assert "report.docx" in response.headers["content-disposition"]
    assert "wordprocessingml" in response.headers["content-type"]
    assert "Page 1 of 3" in docx_text(response.content)


@requires_pdf2docx
def test_word_keeps_the_spaces_a_pdf_only_implies(
    client: TestClient, gapped_pdf: bytes
) -> None:
    # The document writes no space character at all — the gaps between words
    # are pure geometry. Left to itself pdf2docx discards them and produces
    # "Spacesareimpliedhere"; app.tools.pdf2docx_cli is what stops it.
    response = client.post("/convert/word", files=[upload("bank.pdf", gapped_pdf)])
    assert response.status_code == 200

    text = docx_text(response.content)
    assert " ".join(GAPPED_WORDS) in text
    assert "".join(GAPPED_WORDS) not in text


@requires_pdf2docx
@requires_tesseract
def test_word_ocr_mode_leaves_a_text_pdf_alone(
    client: TestClient, text_pdf: bytes
) -> None:
    # --skip-text means asking for OCR on a born-digital PDF is a no-op rather
    # than a second, worse text layer.
    response = client.post(
        "/convert/word",
        files=[upload("report.pdf", text_pdf)],
        data={"ocr": "auto", "languages": "eng"},
    )
    assert response.status_code == 200
    assert "Page 1 of 3" in docx_text(response.content)


@requires_pdf2docx
@requires_tesseract
@pytest.mark.skipif(
    not has_scalable_font(), reason="no scalable font, OCR input would be unreadable"
)
def test_word_ocr_mode_reads_a_scan(client: TestClient, scanned_pdf: bytes) -> None:
    # Unlike anydoc, pdf2docx does read the text layer OCRmyPDF adds, so this
    # is the whole difference between the two modes on a scanned document.
    plain = client.post("/convert/word", files=[upload("scan.pdf", scanned_pdf)])
    assert plain.status_code == 200
    assert "SCANNED" not in docx_text(plain.content).upper()

    ocred = client.post(
        "/convert/word",
        files=[upload("scan.pdf", scanned_pdf)],
        data={"ocr": "auto", "languages": "eng"},
    )
    assert ocred.status_code == 200
    assert "SCANNED" in docx_text(ocred.content).upper()


@requires_pdf2docx
def test_word_reports_an_encrypted_input(
    client: TestClient, encrypted_pdf: bytes
) -> None:
    response = client.post(
        "/convert/word", files=[upload("locked.pdf", encrypted_pdf)]
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "password_required"


@requires_pdf2docx
def test_word_several_files_return_a_zip(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/convert/word",
        files=[upload("one.pdf", text_pdf), upload("two.pdf", text_pdf)],
    )
    assert response.headers["content-type"] == "application/zip"
    assert "pdfkit-word.zip" in response.headers["content-disposition"]
    assert zip_names(response.content) == ["one.docx", "two.docx"]


# --- shared options ----------------------------------------------------------


@pytest.mark.parametrize("endpoint", ["/convert/word", "/convert/markdown"])
def test_rejects_an_unknown_ocr_mode(
    client: TestClient, text_pdf: bytes, endpoint: str
) -> None:
    response = client.post(
        endpoint, files=[upload("a.pdf", text_pdf)], data={"ocr": "maybe"}
    )
    assert response.status_code == 400
    assert "ocr must be one of" in response.json()["detail"]


@requires_tesseract
@pytest.mark.parametrize("endpoint", ["/convert/word", "/convert/markdown"])
def test_rejects_an_uninstalled_language(
    client: TestClient, text_pdf: bytes, endpoint: str
) -> None:
    response = client.post(
        endpoint,
        files=[upload("a.pdf", text_pdf)],
        data={"ocr": "auto", "languages": "eng,klingon"},
    )
    assert response.status_code == 400
    assert "klingon" in response.json()["detail"]
