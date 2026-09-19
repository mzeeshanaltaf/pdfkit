"""POST /images/extract."""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient
from PIL import Image

from tests.conftest import requires_poppler, upload, zip_names

pytestmark = requires_poppler


def first_image(payload: bytes) -> Image.Image:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        name = archive.namelist()[0]
        return Image.open(io.BytesIO(archive.read(name)))


def test_extracts_the_embedded_image(client: TestClient, photo_pdf: bytes) -> None:
    response = client.post(
        "/images/extract",
        files=[upload("holiday.pdf", photo_pdf)],
        data={"quality": "normal"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "holiday-images.zip" in response.headers["content-disposition"]

    assert zip_names(response.content) == ["holiday-image-001.jpg"]
    image = first_image(response.content)
    assert image.format == "JPEG"
    assert image.size == (1600, 2200)


def test_a_single_image_still_comes_back_as_a_zip(
    client: TestClient, photo_pdf: bytes
) -> None:
    response = client.post("/images/extract", files=[upload("one.pdf", photo_pdf)])
    assert response.headers["content-type"] == "application/zip"
    assert len(zip_names(response.content)) == 1


def test_high_quality_is_larger_than_normal(
    client: TestClient, photo_pdf: bytes
) -> None:
    sizes = {}
    for quality in ("normal", "high"):
        response = client.post(
            "/images/extract",
            files=[upload("holiday.pdf", photo_pdf)],
            data={"quality": quality},
        )
        sizes[quality] = len(response.content)
    assert sizes["high"] > sizes["normal"]


def test_several_files_share_one_archive(
    client: TestClient, photo_pdf: bytes, scanned_pdf: bytes
) -> None:
    response = client.post(
        "/images/extract",
        files=[upload("photo.pdf", photo_pdf), upload("scan.pdf", scanned_pdf)],
        data={"quality": "normal"},
    )
    assert response.status_code == 200
    assert "pdfkit-images.zip" in response.headers["content-disposition"]
    assert zip_names(response.content) == ["photo-image-001.jpg", "scan-image-001.jpg"]


def test_a_pdf_with_no_images_is_reported(client: TestClient, text_pdf: bytes) -> None:
    response = client.post("/images/extract", files=[upload("text.pdf", text_pdf)])
    assert response.status_code == 422
    assert response.json()["detail"] == "no_images_found"


def test_rejects_an_unknown_quality(client: TestClient, photo_pdf: bytes) -> None:
    response = client.post(
        "/images/extract",
        files=[upload("a.pdf", photo_pdf)],
        data={"quality": "lossless"},
    )
    assert response.status_code == 400
    assert "normal" in response.json()["detail"]


def test_reports_an_encrypted_input(client: TestClient, encrypted_pdf: bytes) -> None:
    response = client.post(
        "/images/extract", files=[upload("locked.pdf", encrypted_pdf)]
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "password_required"
