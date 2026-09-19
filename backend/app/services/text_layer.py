"""Reading and revealing the text layer OCR puts behind a scanned page.

OCRmyPDF writes recognised text in rendering mode 3 — drawn but neither filled
nor stroked, so the page still looks exactly like the scan it came from. That is
the right default, and every text *extractor* reads it happily: pypdf and
pdftotext both return the words.

A layout *parser* is a different matter. pdf2docx, which rebuilds a PDF as real
Word content, discards invisible text: it is trying to reproduce what the page
looks like, and by that measure the text is not there. Handed an OCR'd scan it
therefore produces a document with a picture of the page and nothing to edit,
which is precisely what someone converting a scan to Word does not want.

:func:`reveal_text` fixes that for the pages that were scanned, by making the
recognised text visible and dropping the page image it was sitting behind. What
reaches pdf2docx is then an ordinary text page, laid out where Tesseract found
the words, and what comes back is an editable Word document. Only pages that had
no text of their own are touched, so a figure on a born-digital page is never
stripped out from under its caption.
"""

from __future__ import annotations

import logging
from collections.abc import Collection
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject

logger = logging.getLogger(__name__)

# The text rendering mode operator OCRmyPDF uses for its invisible layer, and
# the one that paints. Rewriting between them is a pure content-stream edit:
# every glyph, position and font stays exactly as it was.
_INVISIBLE = b"3 Tr"
_FILL = b"0 Tr"


def page_texts(source: Path) -> dict[int, str]:
    """The extractable text of each page, keyed by 1-based page number.

    Blocking and I/O-bound; call it in a thread. Never raises: a page pypdf
    cannot read comes back empty, because a document that is partly readable is
    still worth returning.
    """
    try:
        reader = PdfReader(str(source))
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.warning("could not read %s: %s", source.name, error)
        return {}

    texts: dict[int, str] = {}
    for index, page in enumerate(reader.pages, start=1):
        try:
            texts[index] = page.extract_text() or ""
        except Exception as error:  # noqa: BLE001 — as above
            logger.warning("could not read page %s of %s: %s", index, source.name, error)
            texts[index] = ""
    return texts


def pages_without_text(source: Path) -> list[int]:
    """1-based pages with nothing to extract — the ones OCR would be for."""
    return [number for number, text in page_texts(source).items() if not text.strip()]


def _image_names(page) -> list[str]:  # noqa: ANN001 — pypdf's PageObject
    resources = page.get("/Resources")
    xobjects = resources.get("/XObject") if resources else None
    if not xobjects:
        return []
    names = []
    for name, reference in xobjects.items():
        try:
            if reference.get_object().get("/Subtype") == "/Image":
                names.append(name)
        except Exception as error:  # noqa: BLE001 — a broken or missing xobject
            logger.debug("skipping xobject %s: %s", name, error)
    return names


def reveal_text(source: Path, destination: Path, pages: Collection[int]) -> bool:
    """Make the OCR text on ``pages`` visible and remove their page images.

    Blocking; call it in a thread. Returns False if the document could not be
    rewritten, in which case ``destination`` must not be used — the caller
    carries on with the untouched file rather than failing the request.
    """
    wanted = set(pages)
    if not wanted:
        return False

    try:
        writer = PdfWriter(clone_from=str(source))
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.info("could not open %s to reveal its text: %s", source.name, error)
        return False

    changed = 0
    for number, page in enumerate(writer.pages, start=1):
        if number not in wanted:
            continue
        try:
            contents = page.get_contents()
            if contents is None:
                continue
            data = contents.get_data().replace(_INVISIBLE, _FILL)
            for name in _image_names(page):
                # Drop the draw, not the object: the image stays in the
                # resources unreferenced and is simply never painted.
                data = data.replace(f"{name} Do".encode(), b"")

            stream = DecodedStreamObject()
            stream.set_data(data)
            page.replace_contents(stream)
            changed += 1
        except Exception as error:  # noqa: BLE001 — as above
            logger.info("could not rewrite page %s of %s: %s", number, source.name, error)

    if not changed:
        return False

    try:
        with destination.open("wb") as handle:
            writer.write(handle)
    except Exception as error:  # noqa: BLE001 — as above
        logger.info("could not write the revealed %s: %s", source.name, error)
        return False

    logger.info("revealed the OCR text on %s page(s) of %s", changed, source.name)
    return True
