"""``X-Processed-On``, on the real routers.

A separate module from ``test_offload.py`` on purpose: that file already
defines its own ``client`` fixture — a fake Daytona client, unrelated to
FastAPI — and a same-named fixture anywhere in a module shadows one of the
same name from ``conftest.py`` for the *whole* module, so these tests would
silently get the wrong ``client`` if they lived there.

Offloading is off in every test here (the suite's default), so the answer is
always ``"server"`` — the point is that :func:`app.services.responses.file_response`
stamps the header on *every* shape a router can hand back, single file and zip
alike, for every operation with an offload head. The sandbox half of the
contract — that the header would say ``"sandbox"`` instead — is covered by
the placement tests in ``test_offload.py``, which this header reads from.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.services import placement

from .conftest import (
    requires_anydoc,
    requires_ghostscript,
    requires_ocrmypdf,
    requires_pdf2docx,
    requires_tesseract,
    upload,
)


@requires_ghostscript
def test_compress_response_carries_the_placement_header(
    client: TestClient, text_pdf: bytes
) -> None:
    single = client.post(
        "/compress", files=[upload("a.pdf", text_pdf)], data={"level": "recommended"}
    )
    assert single.headers["x-processed-on"] == placement.SERVER

    batch = client.post(
        "/compress",
        files=[upload("a.pdf", text_pdf), upload("b.pdf", text_pdf)],
        data={"level": "recommended"},
    )
    assert batch.headers["x-processed-on"] == placement.SERVER


@requires_ocrmypdf
@requires_tesseract
def test_ocr_response_carries_the_placement_header(
    client: TestClient, scanned_pdf: bytes
) -> None:
    single = client.post("/ocr", files=[upload("a.pdf", scanned_pdf)])
    assert single.headers["x-processed-on"] == placement.SERVER

    batch = client.post(
        "/ocr", files=[upload("a.pdf", scanned_pdf), upload("b.pdf", scanned_pdf)]
    )
    assert batch.headers["x-processed-on"] == placement.SERVER


@requires_pdf2docx
def test_word_response_carries_the_placement_header(
    client: TestClient, text_pdf: bytes
) -> None:
    single = client.post("/convert/word", files=[upload("a.pdf", text_pdf)])
    assert single.headers["x-processed-on"] == placement.SERVER

    batch = client.post(
        "/convert/word", files=[upload("a.pdf", text_pdf), upload("b.pdf", text_pdf)]
    )
    assert batch.headers["x-processed-on"] == placement.SERVER


@requires_anydoc
def test_markdown_response_carries_the_placement_header(
    client: TestClient, text_pdf: bytes
) -> None:
    single = client.post("/convert/markdown", files=[upload("a.pdf", text_pdf)])
    assert single.headers["x-processed-on"] == placement.SERVER

    batch = client.post(
        "/convert/markdown", files=[upload("a.pdf", text_pdf), upload("b.pdf", text_pdf)]
    )
    assert batch.headers["x-processed-on"] == placement.SERVER
