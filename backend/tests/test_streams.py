"""The content-stream rewriter.

Every test here is about the same worry: the rewriter edits PDF drawing
operators as raw bytes, so it has to leave alone every byte that only *looks*
like a number.
"""

from __future__ import annotations

import io
import zlib

import pytest
from pypdf import PdfReader

from app.services import streams
from tests.conftest import build_vector_pdf


# --- the lossless default ----------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (b"0.750000 0 0 -0.750000 0 841.920044 cm", b"0.75 0 0 -0.75 0 841.920044 cm"),
        (b"4.970000 -5.130000 l", b"4.97 -5.13 l"),
        (b"841.000000 0.000000 m", b"841 0 m"),
        (b".500000 .000000 re", b".5 0 re"),
        (b"12 34 56 rg", b"12 34 56 rg"),  # integers have nothing to give
    ],
)
def test_strips_padding_without_changing_any_value(source: bytes, expected: bytes) -> None:
    assert streams.shorten(source) == expected


def test_the_default_is_arithmetically_lossless() -> None:
    source = b"0.123456 78.901000 -0.000500 12.340000 m"
    before = [float(token) for token in source.split()[:-1]]
    after = [float(token) for token in streams.shorten(source).split()[:-1]]
    assert before == after


# --- bytes that must not be touched ------------------------------------------


def test_leaves_text_inside_a_string_alone() -> None:
    source = b"BT (price 1.500000 each) Tj ET 1.500000 0 Td"
    # The string keeps its text; only the operand outside it is shortened.
    assert streams.shorten(source) == b"BT (price 1.500000 each) Tj ET 1.5 0 Td"


def test_handles_escaped_and_nested_parens_in_a_string() -> None:
    source = rb"((a) \) 2.500000) Tj 2.500000 0 Td"
    assert streams.shorten(source) == rb"((a) \) 2.500000) Tj 2.5 0 Td"


def test_leaves_inline_image_data_alone() -> None:
    # Binary image bytes that happen to spell a padded number must survive.
    payload = b"\x01\x02 1.500000 \x03\xff"
    source = b"BI /W 4 /H 4 /BPC 8 ID " + payload + b" EI 1.500000 0 Td"
    result = streams.shorten(source)
    assert payload in result
    assert result.endswith(b"EI 1.5 0 Td")


def test_does_not_mangle_a_name_containing_digits() -> None:
    assert streams.shorten(b"/R7.0 Do /Im1.500000 Do") == b"/R7.0 Do /Im1.500000 Do"


def test_does_not_strand_the_mantissa_of_an_exponent() -> None:
    # Not legal in a content stream, but producers emit it; rewriting `1.500000`
    # to `1.5` here would leave `1.5e-5`, a different number.
    assert streams.shorten(b"1.500000e-5 0 Td") == b"1.500000e-5 0 Td"


# --- rounding ----------------------------------------------------------------


def test_rounding_shortens_further_than_the_lossless_pass() -> None:
    source = b"0.137255 0.121569 0.125490 rg"
    assert streams.shorten(source, precision=2) == b"0.14 0.12 0.13 rg"


def test_rounding_never_collapses_a_small_number_to_zero() -> None:
    """A scale factor rounded to 0 would make the drawing vanish."""
    result = streams.shorten(b"0.000123 0 0 0.000123 0 0 cm", precision=2)
    values = [float(token) for token in result.split()[:-1]]
    assert values[0] == pytest.approx(0.000123, rel=1e-3)
    assert 0 not in values[:1]


def test_rounding_never_lengthens_a_number() -> None:
    assert streams.shorten(b"1.5 0.25 m", precision=6) == b"1.5 0.25 m"


# --- end to end over a document ----------------------------------------------


def test_rebuild_shrinks_a_print_driver_pdf(tmp_path) -> None:
    source = tmp_path / "in.pdf"
    destination = tmp_path / "out.pdf"
    source.write_bytes(build_vector_pdf())

    assert streams.rebuild(source, destination) is True
    assert destination.stat().st_size < source.stat().st_size
    assert len(PdfReader(str(destination)).pages) == 3


def test_rebuild_keeps_the_drawing_operators(tmp_path) -> None:
    source = tmp_path / "in.pdf"
    destination = tmp_path / "out.pdf"
    source.write_bytes(build_vector_pdf(pages=1, glyphs=20))
    streams.rebuild(source, destination)

    before = PdfReader(str(source)).pages[0].get_contents().get_data()
    after = PdfReader(str(destination)).pages[0].get_contents().get_data()
    # Same drawing, fewer bytes: the operators are untouched and only the
    # numbers in front of them got shorter.
    assert after.count(b" c\n") == before.count(b" c\n")
    assert after.count(b"\nf\n") == before.count(b"\nf\n")
    assert len(after) < len(before)


def test_rebuild_declines_a_file_it_cannot_read(tmp_path) -> None:
    source = tmp_path / "broken.pdf"
    destination = tmp_path / "out.pdf"
    source.write_bytes(b"%PDF-1.7\nnot actually a pdf\n")
    assert streams.rebuild(source, destination) is False


def test_rebuild_respects_a_deadline(tmp_path) -> None:
    source = tmp_path / "in.pdf"
    destination = tmp_path / "out.pdf"
    source.write_bytes(build_vector_pdf())
    # A deadline already in the past: it must give up rather than run anyway.
    assert streams.rebuild(source, destination, deadline=0.0) is False


# --- the survey that picks the strategy --------------------------------------


def test_survey_sees_a_vector_pdf_as_content(tmp_path) -> None:
    source = tmp_path / "in.pdf"
    source.write_bytes(build_vector_pdf())
    measured = streams.survey(source)
    assert measured is not None
    assert measured.content_share > 0.5
    assert measured.image_bytes == 0


def test_survey_sees_a_scan_as_images(tmp_path, photo_pdf: bytes) -> None:
    source = tmp_path / "in.pdf"
    source.write_bytes(photo_pdf)
    measured = streams.survey(source)
    assert measured is not None
    assert measured.image_share > 0.5


def test_survey_gives_up_quietly_on_a_broken_file(tmp_path) -> None:
    source = tmp_path / "broken.pdf"
    source.write_bytes(b"not a pdf at all")
    assert streams.survey(source) is None
