"""Upload validation — the checks that run before any native tool is spawned."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.config import MAX_BATCH_MB, MAX_FILES_PER_REQUEST, MAX_UPLOAD_BYTES
from app.deps import sanitise_filename
from tests.conftest import upload


def test_rejects_a_file_over_the_cap(client: TestClient) -> None:
    oversize = b"%PDF-1.7\n" + b"\x00" * (MAX_UPLOAD_BYTES + 1)
    response = client.post(
        "/compress", files=[upload("huge.pdf", oversize)], data={"level": "less"}
    )
    assert response.status_code == 413
    assert "50 MB" in response.json()["detail"]


def test_rejects_a_file_that_is_not_a_pdf(client: TestClient) -> None:
    response = client.post("/compress", files=[upload("notes.txt", b"just some text")])
    assert response.status_code == 415
    # The name is echoed as the user typed it, not renamed to .pdf first.
    assert response.json()["detail"] == "notes.txt is not a PDF file."


def test_rejects_an_empty_file(client: TestClient) -> None:
    response = client.post("/compress", files=[upload("empty.pdf", b"")])
    assert response.status_code == 400


def test_rejects_a_request_with_no_files(client: TestClient) -> None:
    # FastAPI's own validation catches a missing field before ours does.
    assert client.post("/compress", data={"level": "less"}).status_code == 422


def test_rejects_too_many_files(client: TestClient, text_pdf: bytes) -> None:
    files = [
        upload(f"file-{index}.pdf", text_pdf)
        for index in range(MAX_FILES_PER_REQUEST + 1)
    ]
    response = client.post("/compress", files=files)
    assert response.status_code == 400
    assert response.json()["detail"] == "too_many_files"


def test_rejects_a_batch_over_the_combined_cap(client: TestClient) -> None:
    # Four files, each safely under the per-file cap, whose sum still clears
    # the combined batch cap.
    per_file = b"%PDF-1.7\n" + b"\x00" * (MAX_UPLOAD_BYTES - 1024)
    files = [upload(f"file-{index}.pdf", per_file) for index in range(4)]
    response = client.post("/compress", files=files, data={"level": "less"})
    assert response.status_code == 413
    assert f"{MAX_BATCH_MB} MB" in response.json()["detail"]


def test_magic_bytes_are_checked_not_the_extension(client: TestClient) -> None:
    # A .pdf name over non-PDF content must still be refused.
    response = client.post("/compress", files=[upload("lying.pdf", b"GIF89a" * 40)])
    assert response.status_code == 415


class TestSanitiseFilename:
    def test_strips_directory_components(self) -> None:
        assert sanitise_filename("../../etc/passwd.pdf") == "passwd.pdf"
        assert sanitise_filename(r"C:\Users\me\report.pdf") == "report.pdf"

    def test_keeps_a_single_pdf_extension(self) -> None:
        assert sanitise_filename("report.pdf") == "report.pdf"
        assert sanitise_filename("report") == "report.pdf"
        assert sanitise_filename("report.PDF") == "report.pdf"

    def test_falls_back_for_an_unusable_name(self) -> None:
        assert sanitise_filename(None) == "document.pdf"
        assert sanitise_filename("   ") == "document.pdf"
        assert sanitise_filename("...") == "document.pdf"

    def test_caps_the_length(self) -> None:
        assert len(sanitise_filename("x" * 500)) == 124  # 120 + ".pdf"
