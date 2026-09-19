"""Shared fixtures. Every PDF here is generated at run time — no binary assets
are committed, so the suite cannot drift from a stale file on disk."""

from __future__ import annotations

import io
import shutil
import subprocess
import zipfile
import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.main import app

ENCRYPTED_PASSWORD = "hunter2"

# Docker-only tools. Locally the suite still runs; the tests that need them skip.
requires_qpdf = pytest.mark.skipif(
    shutil.which("qpdf") is None, reason="qpdf is only installed in the backend image"
)
requires_ghostscript = pytest.mark.skipif(
    shutil.which("gs") is None, reason="ghostscript is only installed in the backend image"
)
requires_tesseract = pytest.mark.skipif(
    shutil.which("tesseract") is None,
    reason="tesseract is only installed in the backend image",
)
requires_poppler = pytest.mark.skipif(
    shutil.which("pdfimages") is None,
    reason="poppler-utils is only installed in the backend image",
)


@pytest.fixture(scope="session")
def client() -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


# --- fixture documents -------------------------------------------------------


def build_text_pdf(pages: int = 3) -> bytes:
    """A minimal, hand-assembled PDF with real, extractable Helvetica text.

    Written by hand rather than with a layout library so the bytes are fully
    deterministic and the suite carries no extra dependency for one fixture.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )
    pages_id = len(objects) + 1 + pages * 2  # page objects, then their contents
    page_ids: list[int] = []
    for number in range(1, pages + 1):
        text = f"Page {number} of {pages}".encode("ascii")
        stream = b"BT /F1 24 Tf 72 700 Td (" + text + b") Tj ET"
        content = add(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )
        page_ids.append(
            add(
                b"<< /Type /Page /Parent "
                + str(pages_id).encode()
                + b" 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 "
                + str(font).encode()
                + b" 0 R >> >> /Contents "
                + str(content).encode()
                + b" 0 R >>"
            )
        )

    kids = b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids)
    tree = add(
        b"<< /Type /Pages /Count "
        + str(pages).encode()
        + b" /Kids [" + kids + b"] >>"
    )
    assert tree == pages_id, "page objects must be laid out before the page tree"
    catalog = add(b"<< /Type /Catalog /Pages " + str(tree).encode() + b" 0 R >>")
    return assemble_pdf(objects, catalog)


def assemble_pdf(objects: list[bytes], catalog: int) -> bytes:
    """Wrap already-built object bodies in a header, xref table and trailer."""
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{index} 0 obj\n".encode() + body + b"\nendobj\n"

    start_xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode()
        + b" /Root " + str(catalog).encode() + b" 0 R >>\nstartxref\n"
        + str(start_xref).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def build_vector_pdf(pages: int = 3, glyphs: int = 500) -> bytes:
    """A PDF that is pure vector drawing, written the way a print driver writes it.

    "Microsoft: Print To PDF" — the producer of the files this fixture stands in
    for — has no font to embed, so it traces every glyph as filled bezier paths
    and pads every single coordinate to six decimal places. The result carries
    no images and no fonts, so it is exactly the document Ghostscript cannot
    help with and the content-stream rewriter can.
    """
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    pages_id = pages * 2 + 1  # a content stream and a page object each
    page_ids: list[int] = []
    for number in range(pages):
        drawing = bytearray(b"0.750000 0.000000 0.000000 -0.750000 0.000000 841.920044 cm\n")
        # Deterministic, and shaped like the real thing: a fill colour, a move,
        # a run of curves, a close and a fill, over and over.
        for index in range(glyphs):
            x = (index * 7 + number * 13) % 500
            y = (index * 11 + number * 29) % 700
            drawing += b"q\n1.000000 0.000000 0.000000 1.000000 "
            drawing += f"{x}.190002 {y}.579956 cm\n".encode()
            drawing += b"0.137255 0.121569 0.125490 rg\n0.000000 0.000000 m\n"
            for step in range(6):
                a, b, c = step * 1.5, step * 2.25, step * 0.75
                drawing += f"{a:.6f} {b:.6f} {c:.6f} {a:.6f} {b:.6f} {c:.6f} c\n".encode()
            drawing += b"h\nf\nQ\n"

        packed = zlib.compress(bytes(drawing), 6)
        content = add(
            b"<< /Filter /FlateDecode /Length "
            + str(len(packed)).encode()
            + b" >>\nstream\n"
            + packed
            + b"\nendstream"
        )
        page_ids.append(
            add(
                b"<< /Type /Page /Parent "
                + str(pages_id).encode()
                + b" 0 R /MediaBox [0 0 595 842] /Resources << >> /Contents "
                + str(content).encode()
                + b" 0 R >>"
            )
        )

    kids = b" ".join(f"{page_id} 0 R".encode() for page_id in page_ids)
    tree = add(b"<< /Type /Pages /Count " + str(pages).encode() + b" /Kids [" + kids + b"] >>")
    assert tree == pages_id, "page objects must be laid out before the page tree"
    catalog = add(b"<< /Type /Catalog /Pages " + str(tree).encode() + b" 0 R >>")
    return assemble_pdf(objects, catalog)


DEJAVU = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")


def _ocr_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    if DEJAVU.exists():
        return ImageFont.truetype(str(DEJAVU), size)
    # No scalable font on this machine: Tesseract will do badly on the scaled-up
    # bitmap font, so the OCR assertions skip rather than fail spuriously.
    return ImageFont.load_default()


def build_scanned_pdf(pages: int = 1, text: str = "SCANNED") -> bytes:
    """An image-only PDF: large black lettering on white, no text layer at all.

    This is the OCR fixture — 150 dpi, high contrast, one short word per page,
    which is about as easy as Tesseract input gets.
    """
    font = _ocr_font(110)
    frames = []
    for number in range(pages):
        canvas = Image.new("RGB", (1240, 1754), "white")
        ImageDraw.Draw(canvas).text(
            (120, 300), f"{text} {number + 1}", fill="black", font=font
        )
        frames.append(canvas)

    buffer = io.BytesIO()
    frames[0].save(
        buffer, "PDF", resolution=150.0, save_all=True, append_images=frames[1:]
    )
    return buffer.getvalue()


def has_scalable_font() -> bool:
    return DEJAVU.exists()


def build_photo_pdf() -> bytes:
    """A PDF whose single page is one large 300 dpi photo-like image.

    Ghostscript genuinely shrinks this by downsampling (the tiny text fixture it
    cannot), which is what makes it the compression fixture.
    """
    base = Image.linear_gradient("L").resize((1600, 2200), Image.BICUBIC)
    canvas = Image.merge(
        "RGB",
        (
            base,
            base.transpose(Image.Transpose.ROTATE_180),
            base.transpose(Image.Transpose.FLIP_LEFT_RIGHT),
        ),
    )
    draw = ImageDraw.Draw(canvas)
    for step in range(24):
        draw.ellipse(
            [step * 30, step * 40, 1600 - step * 25, 2200 - step * 45],
            outline=(step * 10 % 256, 255 - step * 9, step * 17 % 256),
            width=9,
        )

    buffer = io.BytesIO()
    canvas.save(buffer, "PDF", resolution=300.0)
    return buffer.getvalue()


def encrypt_pdf(
    source: bytes, password: str, directory: Path, *, user_password: str | None = None
) -> bytes:
    """Encrypt with the real qpdf — the same tool the service under test uses.

    ``user_password=""`` gives an owner-password-only file: encrypted, but it
    opens with the empty password, so every tool here can still read it.
    """
    plain = directory / "plain.pdf"
    locked = directory / "locked.pdf"
    plain.write_bytes(source)
    user = password if user_password is None else user_password
    subprocess.run(
        ["qpdf", "--encrypt", user, password, "256", "--", str(plain), str(locked)],
        check=True,
        capture_output=True,
    )
    return locked.read_bytes()


@pytest.fixture(scope="session")
def text_pdf() -> bytes:
    return build_text_pdf()


@pytest.fixture(scope="session")
def scanned_pdf() -> bytes:
    return build_scanned_pdf()


@pytest.fixture(scope="session")
def photo_pdf() -> bytes:
    return build_photo_pdf()


@pytest.fixture(scope="session")
def vector_pdf() -> bytes:
    return build_vector_pdf()


@pytest.fixture(scope="session")
def encrypted_pdf(text_pdf: bytes, tmp_path_factory: pytest.TempPathFactory) -> bytes:
    if shutil.which("qpdf") is None:
        pytest.skip("qpdf is only installed in the backend image")
    return encrypt_pdf(text_pdf, ENCRYPTED_PASSWORD, tmp_path_factory.mktemp("encrypt"))


@pytest.fixture(scope="session")
def owner_locked_pdf(
    photo_pdf: bytes, tmp_path_factory: pytest.TempPathFactory
) -> bytes:
    """Encrypted, but with an empty user password — readable without a prompt."""
    if shutil.which("qpdf") is None:
        pytest.skip("qpdf is only installed in the backend image")
    return encrypt_pdf(
        photo_pdf,
        ENCRYPTED_PASSWORD,
        tmp_path_factory.mktemp("owner"),
        user_password="",
    )


# --- helpers -----------------------------------------------------------------


def upload(name: str, data: bytes) -> tuple[str, tuple[str, bytes, str]]:
    return ("files", (name, data, "application/pdf"))


def zip_names(payload: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return archive.namelist()
