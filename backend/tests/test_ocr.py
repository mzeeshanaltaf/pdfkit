"""POST /ocr and GET /ocr/languages."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.services.ocr import _parse_langs
from tests.conftest import has_scalable_font, requires_tesseract, upload, zip_names

pytestmark = requires_tesseract


def text_of(payload: bytes) -> str:
    reader = PdfReader(io.BytesIO(payload))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def test_languages_lists_english(client: TestClient) -> None:
    response = client.get("/ocr/languages")
    assert response.status_code == 200
    languages = response.json()
    assert {"code": "eng", "name": "English"} in languages
    # osd is a script-detection model, not something to offer in a picker.
    assert all(entry["code"] != "osd" for entry in languages)


def test_parse_langs_skips_the_header_and_non_languages() -> None:
    raw = (
        'List of available languages in "/usr/share/tessdata/" (4):\n'
        "eng\nosd\nequ\ndeu\n"
    )
    # Ordered by display name, so English precedes German despite "deu" < "eng".
    assert [language.code for language in _parse_langs(raw)] == ["eng", "deu"]
    assert [language.name for language in _parse_langs(raw)] == ["English", "German"]


@pytest.mark.skipif(
    not has_scalable_font(), reason="no scalable font, OCR input would be unreadable"
)
def test_adds_a_text_layer_to_a_scanned_page(
    client: TestClient, scanned_pdf: bytes
) -> None:
    assert text_of(scanned_pdf).strip() == "", "fixture must start with no text layer"

    response = client.post(
        "/ocr", files=[upload("scan.pdf", scanned_pdf)], data={"languages": "eng"}
    )
    assert response.status_code == 200
    assert "scan-ocr.pdf" in response.headers["content-disposition"]
    assert "SCANNED" in text_of(response.content).upper()


def test_defaults_to_english(client: TestClient, scanned_pdf: bytes) -> None:
    response = client.post("/ocr", files=[upload("scan.pdf", scanned_pdf)])
    assert response.status_code == 200


def test_skips_pages_that_already_have_text(
    client: TestClient, text_pdf: bytes
) -> None:
    # --skip-text means a born-digital PDF passes through with its text intact
    # rather than gaining a second, worse layer on top.
    response = client.post(
        "/ocr", files=[upload("report.pdf", text_pdf)], data={"languages": "eng"}
    )
    assert response.status_code == 200
    assert "Page 1 of 3" in text_of(response.content)


def test_rejects_an_uninstalled_language(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/ocr", files=[upload("a.pdf", text_pdf)], data={"languages": "eng,klingon"}
    )
    assert response.status_code == 400
    assert "klingon" in response.json()["detail"]


def test_rejects_more_than_three_languages(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/ocr",
        files=[upload("a.pdf", text_pdf)],
        data={"languages": "eng,eng2,eng3,eng4"},
    )
    assert response.status_code == 400
    assert "At most 3" in response.json()["detail"]


def test_several_files_return_a_zip(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/ocr",
        files=[upload("one.pdf", text_pdf), upload("two.pdf", text_pdf)],
        data={"languages": "eng"},
    )
    assert response.headers["content-type"] == "application/zip"
    assert "pdfkit-ocr.zip" in response.headers["content-disposition"]
    assert zip_names(response.content) == ["one-ocr.pdf", "two-ocr.pdf"]


def test_reports_an_encrypted_input(client: TestClient, encrypted_pdf: bytes) -> None:
    response = client.post(
        "/ocr", files=[upload("locked.pdf", encrypted_pdf)], data={"languages": "eng"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "password_required"
