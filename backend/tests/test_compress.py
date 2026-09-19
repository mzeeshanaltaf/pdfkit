"""POST /compress."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from tests.conftest import requires_ghostscript, upload, zip_names

pytestmark = requires_ghostscript


def test_compresses_a_photo_pdf(client: TestClient, photo_pdf: bytes) -> None:
    response = client.post(
        "/compress",
        files=[upload("holiday.pdf", photo_pdf)],
        data={"level": "recommended"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "holiday-compressed.pdf" in response.headers["content-disposition"]

    assert len(response.content) < len(photo_pdf)
    assert response.headers["X-Original-Size"] == str(len(photo_pdf))
    assert response.headers["X-Result-Size"] == str(len(response.content))
    assert len(PdfReader(io.BytesIO(response.content)).pages) == 1


@pytest.mark.parametrize("level", ["extreme", "recommended", "less"])
def test_every_level_produces_a_valid_pdf(
    client: TestClient, photo_pdf: bytes, level: str
) -> None:
    response = client.post(
        "/compress", files=[upload("holiday.pdf", photo_pdf)], data={"level": level}
    )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-")


def test_extreme_beats_less(client: TestClient, photo_pdf: bytes) -> None:
    sizes = {}
    for level in ("extreme", "less"):
        response = client.post(
            "/compress", files=[upload("holiday.pdf", photo_pdf)], data={"level": level}
        )
        sizes[level] = len(response.content)
    assert sizes["extreme"] < sizes["less"]


def test_never_hands_back_a_bigger_file(client: TestClient, text_pdf: bytes) -> None:
    # A hand-built, already-minimal PDF comes back *larger* from pdfwrite. The
    # service must drop that result rather than pass on a worse file for the
    # same wait, and the headers must describe what was actually sent.
    response = client.post(
        "/compress", files=[upload("tiny.pdf", text_pdf)], data={"level": "extreme"}
    )
    assert response.status_code == 200
    assert len(response.content) <= len(text_pdf)
    assert response.headers["X-Original-Size"] == str(len(text_pdf))
    assert response.headers["X-Result-Size"] == str(len(response.content))


def test_a_second_pass_does_not_undo_the_first(
    client: TestClient, photo_pdf: bytes
) -> None:
    """Compressing an already-compressed file must not inflate it again."""
    first = client.post(
        "/compress", files=[upload("holiday.pdf", photo_pdf)], data={"level": "recommended"}
    ).content
    second = client.post(
        "/compress", files=[upload("holiday.pdf", first)], data={"level": "recommended"}
    ).content
    assert len(second) <= len(first)


def test_shrinks_a_vector_pdf_that_ghostscript_makes_bigger(
    client: TestClient, vector_pdf: bytes
) -> None:
    """The regression this whole split exists for.

    A print-driver PDF is all bezier paths and no images: pdfwrite hands back
    something larger, so compression used to fall through to "return the
    original" and report a 0% saving at every level. The content-stream
    rewriter is what actually shrinks this document.
    """
    response = client.post(
        "/compress",
        files=[upload("villkor.pdf", vector_pdf)],
        data={"level": "recommended"},
    )
    assert response.status_code == 200
    assert len(response.content) < len(vector_pdf) * 0.9
    assert len(PdfReader(io.BytesIO(response.content)).pages) == 3


def test_the_lossless_level_still_shrinks_a_vector_pdf(
    client: TestClient, vector_pdf: bytes
) -> None:
    """"Less compression" rounds no coordinates, and still wins on padding alone."""
    response = client.post(
        "/compress", files=[upload("villkor.pdf", vector_pdf)], data={"level": "less"}
    )
    assert response.status_code == 200
    assert len(response.content) < len(vector_pdf)


def test_several_files_come_back_as_a_zip(
    client: TestClient, text_pdf: bytes, photo_pdf: bytes
) -> None:
    response = client.post(
        "/compress",
        files=[upload("first.pdf", text_pdf), upload("second.pdf", photo_pdf)],
        data={"level": "recommended"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "pdfkit-compressed.zip" in response.headers["content-disposition"]
    assert ".zip.zip" not in response.headers["content-disposition"]
    assert zip_names(response.content) == [
        "first-compressed.pdf",
        "second-compressed.pdf",
    ]
    assert response.headers["X-Original-Size"] == str(len(text_pdf) + len(photo_pdf))


def test_duplicate_names_do_not_collide_in_the_zip(
    client: TestClient, text_pdf: bytes
) -> None:
    response = client.post(
        "/compress",
        files=[upload("same.pdf", text_pdf), upload("same.pdf", text_pdf)],
        data={"level": "less"},
    )
    assert zip_names(response.content) == ["same-compressed.pdf", "same-compressed (2).pdf"]


def test_rejects_an_unknown_level(client: TestClient, text_pdf: bytes) -> None:
    response = client.post(
        "/compress", files=[upload("a.pdf", text_pdf)], data={"level": "maximum"}
    )
    assert response.status_code == 400
    assert "extreme" in response.json()["detail"]


def test_defaults_to_recommended(client: TestClient, photo_pdf: bytes) -> None:
    response = client.post("/compress", files=[upload("a.pdf", photo_pdf)])
    assert response.status_code == 200


def test_reports_an_encrypted_input(client: TestClient, encrypted_pdf: bytes) -> None:
    # Ghostscript 10 exits 0 on a file it cannot decrypt and writes a blank PDF,
    # so without the pypdf pre-check this would come back 200 with junk in it.
    response = client.post(
        "/compress", files=[upload("locked.pdf", encrypted_pdf)], data={"level": "less"}
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "password_required"


def test_an_owner_password_only_file_is_still_compressed(
    client: TestClient, owner_locked_pdf: bytes
) -> None:
    # Encrypted, but it opens with the empty password, so refusing it would be
    # rejecting a file Ghostscript handles perfectly well.
    response = client.post(
        "/compress",
        files=[upload("owner.pdf", owner_locked_pdf)],
        data={"level": "recommended"},
    )
    assert response.status_code == 200
    assert len(response.content) < len(owner_locked_pdf)
