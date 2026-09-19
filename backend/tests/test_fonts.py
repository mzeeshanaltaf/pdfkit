"""Font subsetting.

The dangerous failure here is silent: a font subset badly still opens, still
extracts its text, and simply draws the wrong characters — or none. So these
tests check glyph identity and rendering, not just that the file got smaller.
"""

from __future__ import annotations

import io

import pytest
from pypdf import PdfReader
from pypdf.generic import StreamObject

from app.services import fonts, streams
from tests.conftest import build_fat_font_pdf, build_vector_pdf, requires_font

pytestmark = requires_font


def _programs(path) -> list[StreamObject]:
    """Every embedded font program in a document, as stored."""
    found = []
    for page in PdfReader(str(path)).pages:
        for font in streams.values(streams.resolve(page["/Resources"]).get("/Font")):
            reference, _ = fonts._program_of(streams.resolve(font))
            if reference is not None:
                found.append(streams.resolve(reference))
    return found


@pytest.fixture
def fat(tmp_path):
    source = tmp_path / "fat.pdf"
    source.write_bytes(build_fat_font_pdf())
    return source


def test_cuts_a_whole_font_down_to_the_glyphs_used(fat, tmp_path):
    destination = tmp_path / "out.pdf"
    assert fonts.subset(fat, destination) is True

    before = len(_programs(fat)[0]._data)
    after = len(_programs(destination)[0]._data)
    # Five letters out of six thousand glyphs: this should be a rout, not a trim.
    assert after < before / 10
    assert destination.stat().st_size < fat.stat().st_size / 5


def test_the_text_survives(fat, tmp_path):
    destination = tmp_path / "out.pdf"
    fonts.subset(fat, destination)
    assert "Hello" in PdfReader(str(destination)).pages[0].extract_text()


def test_the_used_glyphs_keep_their_outlines_and_their_numbers(fat, tmp_path):
    """The bug this guards against renumbered every glyph.

    A PDF names glyphs by id, so a subsetter that compacts them leaves the
    content streams pointing at whatever moved into the old slots — the
    en-dashes in the sample document came out blank. Nothing about the file's
    size or its extracted text shows it.
    """
    from fontTools.ttLib import TTFont

    destination = tmp_path / "out.pdf"
    fonts.subset(fat, destination)

    original = TTFont(io.BytesIO(_programs(fat)[0].get_data()), lazy=False)
    rebuilt = TTFont(io.BytesIO(_programs(destination)[0].get_data()), lazy=False)

    order = original.getGlyphOrder()
    cmap = original.getBestCmap()
    for char in "Hello":
        gid = order.index(cmap[ord(char)])
        assert gid < len(rebuilt.getGlyphOrder()), f"glyph {gid} fell off the end"
        name_before = order[gid]
        name_after = rebuilt.getGlyphOrder()[gid]
        assert (
            original["glyf"][name_before].numberOfContours
            == rebuilt["glyf"][name_after].numberOfContours
        ), f"the glyph at id {gid} is not the one {char!r} was drawn with"


def test_leaves_a_document_with_no_embedded_fonts_alone(tmp_path):
    source = tmp_path / "vector.pdf"
    destination = tmp_path / "out.pdf"
    source.write_bytes(build_vector_pdf())
    assert fonts.subset(source, destination) is False
    assert not destination.exists()


def test_declines_a_file_it_cannot_read(tmp_path):
    source = tmp_path / "broken.pdf"
    destination = tmp_path / "out.pdf"
    source.write_bytes(b"%PDF-1.7\nnot a pdf\n")
    assert fonts.subset(source, destination) is False


def test_respects_a_deadline(fat, tmp_path):
    destination = tmp_path / "out.pdf"
    assert fonts.subset(fat, destination, deadline=0.0) is False


def test_the_survey_notices_the_font_weight(fat):
    measured = streams.survey(fat)
    assert measured is not None
    assert measured.font_share > 0.8
    assert measured.image_bytes == 0
