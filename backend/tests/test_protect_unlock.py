"""POST /protect and POST /unlock, including the whole password flow."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.conftest import ENCRYPTED_PASSWORD, requires_qpdf, upload, zip_names

pytestmark = requires_qpdf


def reader(payload: bytes) -> PdfReader:
    return PdfReader(io.BytesIO(payload))


# --- protect -----------------------------------------------------------------


def test_protect_encrypts_the_file(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/protect",
        files=[upload("report.pdf", text_pdf)],
        data={"password": "correct horse"},
    )
    assert response.status_code == 200
    assert "report-protected.pdf" in response.headers["content-disposition"]

    locked = reader(response.content)
    assert locked.is_encrypted
    assert locked.decrypt("correct horse")
    assert len(locked.pages) == 3


def test_protect_requires_a_password(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/protect", files=[upload("report.pdf", text_pdf)], data={"password": ""}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "password_missing"


def test_protect_without_the_password_field_gives_the_same_error(
    client: TestClient, text_pdf: bytes
) -> None:
    # Absent and empty must not produce two different error shapes; the UI
    # should only ever have to read `detail`.
    response = client.post("/protect", files=[upload("report.pdf", text_pdf)])
    assert response.status_code == 400
    assert response.json()["detail"] == "password_missing"


def test_protect_rejects_a_password_containing_a_newline(
    client: TestClient, text_pdf: bytes
) -> None:
    # A newline would be a second line in qpdf's argument file, i.e. argument
    # injection, so it has to be refused rather than escaped.
    response = client.post(
        "/protect",
        files=[upload("report.pdf", text_pdf)],
        data={"password": "abc\n--replace-input"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "password_invalid"


def test_protect_several_files_returns_a_zip(
    client: TestClient, text_pdf: bytes
) -> None:
    response = client.post(
        "/protect",
        files=[upload("one.pdf", text_pdf), upload("two.pdf", text_pdf)],
        data={"password": "hunter2"},
    )
    assert response.headers["content-type"] == "application/zip"
    assert "pdfkit-protected.zip" in response.headers["content-disposition"]
    assert zip_names(response.content) == ["one-protected.pdf", "two-protected.pdf"]


def test_protect_refuses_an_already_encrypted_file(
    client: TestClient, encrypted_pdf: bytes
) -> None:
    response = client.post(
        "/protect",
        files=[upload("locked.pdf", encrypted_pdf)],
        data={"password": "another"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "password_required"


# --- unlock ------------------------------------------------------------------


def test_unlock_with_the_right_password(
    client: TestClient, encrypted_pdf: bytes
) -> None:
    response = client.post(
        "/unlock",
        files=[upload("locked.pdf", encrypted_pdf)],
        data={"password": ENCRYPTED_PASSWORD},
    )
    assert response.status_code == 200
    assert "locked-unlocked.pdf" in response.headers["content-disposition"]

    opened = reader(response.content)
    assert not opened.is_encrypted
    assert "Page 1 of 3" in (opened.pages[0].extract_text() or "")


def test_unlock_without_a_password_asks_for_one(
    client: TestClient, encrypted_pdf: bytes
) -> None:
    response = client.post("/unlock", files=[upload("locked.pdf", encrypted_pdf)])
    assert response.status_code == 422
    assert response.json()["detail"] == "password_required"


def test_unlock_with_the_wrong_password(
    client: TestClient, encrypted_pdf: bytes
) -> None:
    response = client.post(
        "/unlock",
        files=[upload("locked.pdf", encrypted_pdf)],
        data={"password": "not-it"},
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "wrong_password"


def test_unlock_passes_an_unencrypted_file_straight_through(
    client: TestClient, text_pdf: bytes
) -> None:
    response = client.post("/unlock", files=[upload("plain.pdf", text_pdf)])
    assert response.status_code == 200
    assert not reader(response.content).is_encrypted


def test_protect_then_unlock_round_trips(client: TestClient, text_pdf: bytes) -> None:
    protected = client.post(
        "/protect",
        files=[upload("round.pdf", text_pdf)],
        data={"password": "s3cret pass"},
    )
    assert protected.status_code == 200

    unlocked = client.post(
        "/unlock",
        files=[upload("round.pdf", protected.content)],
        data={"password": "s3cret pass"},
    )
    assert unlocked.status_code == 200

    opened = reader(unlocked.content)
    assert not opened.is_encrypted
    assert "Page 2 of 3" in (opened.pages[1].extract_text() or "")
