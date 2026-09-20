"""Rewriting a PDF's content streams so they compress harder.

Ghostscript is the right tool for a PDF whose weight is scanned images: it
downsamples and re-encodes them. It is the *wrong* tool for a PDF whose weight
is vector drawing, which it re-interprets and routinely emits larger than it
found — "Microsoft: Print To PDF" output, where every glyph arrives as filled
bezier paths, comes back about 45% bigger through pdfwrite.

Those files are still very compressible, just not by touching the pictures.
Their producers write every coordinate at a fixed six decimal places, so a
number that means 0.75 costs ten bytes as ``0.750000``, and a page carries tens
of thousands of them. Stripping that padding is a pure text edit — every number
keeps its exact value — and it takes roughly a quarter off a file of this kind.

The default is therefore lossless. ``precision`` additionally rounds the
coordinates, which is not, and is reserved for the levels whose whole premise is
that the user has accepted some quality loss.
"""

from __future__ import annotations

import logging
import re
import time
import zlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    StreamObject,
)

logger = logging.getLogger(__name__)

# Level 9 costs about 2.5s per 100 MB of content over level 6 and pays back
# roughly 5% of the output. On a tool whose entire job is the output size, and
# where the request is already seconds deep, that is the right side of the trade.
DEFLATE_LEVEL = 9


# --- the text edit -----------------------------------------------------------
#
# A PDF real number is preceded by whitespace or a delimiter, so the lookbehind
# keeps us out of the middle of a name (`/R7.0`), and the lookahead keeps us off
# anything that is not really the end of the number — including the `e` of an
# exponent, which is not legal in a content stream but does turn up, and whose
# mantissa we must not rewrite and strand.
_LEAD = rb"(?<![A-Za-z0-9_./#])"
_TAIL = rb"(?![0-9eE.])"

# `4.9700` → `4.97`, and `0.750000` → `0.75`.
_TRAILING_ZEROS = re.compile(_LEAD + rb"([+-]?\d*\.\d*?[1-9])0+" + _TAIL)
# `841.000000` → `841`.
_ZERO_FRACTION = re.compile(_LEAD + rb"([+-]?\d+)\.0+" + _TAIL)
# `.000000` → `0`, which is shorter and means the same thing.
_ZERO = re.compile(_LEAD + rb"[+-]?\.0+" + _TAIL)
# Any real number, for the rounding path.
_NUMBER = re.compile(_LEAD + rb"[+-]?\d*\.\d+" + _TAIL)

# Two things inside a content stream hold bytes that merely *look* like numbers
# and have to be copied through untouched: a literal string, and the binary
# payload of an inline image. This finds the start of either.
_OPAQUE = re.compile(rb"\(|BI[\s/\[<]")

_BACKSLASH, _OPEN_PAREN, _CLOSE_PAREN = 0x5C, 0x28, 0x29


def _end_of_string(buf: bytes, start: int) -> int:
    """Index just past the ``)`` closing the string that opened at ``start``.

    Literal strings nest parentheses and escape them with a backslash, so this
    cannot be a plain ``find``.
    """
    depth, index, length = 1, start, len(buf)
    while index < length:
        char = buf[index]
        if char == _BACKSLASH:
            index += 2
            continue
        if char == _OPEN_PAREN:
            depth += 1
        elif char == _CLOSE_PAREN:
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    return length


# What a rewritten number is allowed to look like. A content stream has no
# exponent notation, so a token like `1.2e-06` is not a small number there — it
# is the operator `e-06` with a stray `1.2` in front of it, and it breaks the
# operator that was supposed to consume the operand. Nothing leaves the rounder
# unless it matches this.
_PLAIN_NUMBER = re.compile(rb"\A[+-]?(?:\d+\.?\d*|\.\d+)\Z")


def _rounder(precision: int):
    """A substitution callback that shortens a number to ``precision`` decimals."""

    def shorten_one(match: re.Match[bytes]) -> bytes:
        original = match.group(0)
        try:
            value = float(original)
        except ValueError:  # pragma: no cover — the pattern cannot produce this
            return original
        text = f"{value:.{precision}f}".rstrip("0").rstrip(".")
        if value != 0 and float(text or 0) == 0:
            # Rounding a small non-zero number away would collapse a scale
            # factor or a hairline offset to zero and move the drawing, so this
            # one keeps the length it came with.
            return original
        candidate = (text or "0").encode()
        if len(candidate) >= len(original) or not _PLAIN_NUMBER.match(candidate):
            return original
        return candidate

    return shorten_one


def _shorten_numbers(buf: bytes, precision: int | None) -> bytes:
    """Rewrite the numbers in one run of operators, strings already excluded."""
    if precision is None:
        # Three plain substitutions with literal replacements, so there is no
        # Python-level callback per match. On a file carrying ten million
        # numbers that is worth about 40% of the wall clock.
        buf = _TRAILING_ZEROS.sub(rb"\1", buf)
        buf = _ZERO_FRACTION.sub(rb"\1", buf)
        return _ZERO.sub(b"0", buf)
    return _NUMBER.sub(_rounder(precision), buf)


def shorten(buf: bytes, precision: int | None = None) -> bytes:
    """Shrink one decoded content stream, leaving strings and inline images alone."""
    pieces: list[bytes] = []
    position, length = 0, len(buf)
    while position < length:
        match = _OPAQUE.search(buf, position)
        stop = match.start() if match else length
        pieces.append(_shorten_numbers(buf[position:stop], precision))
        if match is None:
            break
        if match.group(0)[:1] == b"(":
            end = _end_of_string(buf, match.end())
        else:
            marker = buf.find(b"EI", match.end())
            end = length if marker < 0 else marker + 2
        pieces.append(buf[match.start() : end])
        position = end
    return b"".join(pieces)


# --- finding the content streams ---------------------------------------------


def resolve(obj: object) -> object:
    """Follow an indirect reference, or hand back what was given."""
    return obj.get_object() if isinstance(obj, IndirectObject) else obj


def values(obj: object) -> list:
    """The values of a (possibly indirect) dictionary, or nothing."""
    resolved = resolve(obj)
    return list(resolved.values()) if isinstance(resolved, DictionaryObject) else []


def _stored_size(stream: StreamObject) -> int:
    """How many bytes this stream occupies in the file, still encoded."""
    data = getattr(stream, "_data", None)
    if isinstance(data, (bytes, bytearray)):
        return len(data)
    try:
        return int(resolve(stream.get("/Length")))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


class _Walk:
    """Collects every stream a page can *draw with*, and sizes the images.

    Deliberately a safelist rather than "every stream that is not an image": an
    ICC profile and an embedded font are both bare Flate streams too, and
    running the number rewriter over either would corrupt the document.
    """

    def __init__(self) -> None:
        self.content: list[StreamObject] = []
        self.image_bytes = 0
        self.font_bytes = 0
        self._seen: set[tuple[int, int] | int] = set()
        self._visited_resources: set[int] = set()

    def _first_visit(self, obj: object) -> StreamObject | None:
        """The stream behind ``obj``, or None if it is not one or is a repeat."""
        reference = getattr(obj, "indirect_reference", None)
        key = (reference.idnum, reference.generation) if reference else id(obj)
        if key in self._seen:
            return None
        self._seen.add(key)
        resolved = resolve(obj)
        return resolved if isinstance(resolved, StreamObject) else None

    def _take_content(self, obj: object) -> StreamObject | None:
        stream = self._first_visit(obj)
        if stream is not None:
            self.content.append(stream)
        return stream

    def _take_image(self, obj: object, stream: StreamObject) -> None:
        if self._first_visit(obj) is None:
            return
        self.image_bytes += _stored_size(stream)
        for key in ("/SMask", "/Mask"):
            mask = stream.get(key)
            target = resolve(mask)
            if isinstance(target, StreamObject) and self._first_visit(mask) is not None:
                self.image_bytes += _stored_size(target)

    def _resources(self, resources: object) -> None:
        resolved = resolve(resources)
        if not isinstance(resolved, DictionaryObject):
            return
        if id(resolved) in self._visited_resources:
            return
        self._visited_resources.add(id(resolved))

        for xobject in values(resolved.get("/XObject")):
            target = resolve(xobject)
            if not isinstance(target, StreamObject):
                continue
            subtype = target.get("/Subtype")
            if subtype == "/Image":
                self._take_image(xobject, target)
            elif subtype == "/Form" and self._take_content(xobject) is not None:
                self._resources(target.get("/Resources"))

        for pattern in values(resolved.get("/Pattern")):
            target = resolve(pattern)
            # PatternType 1 is a tiling pattern, whose stream is drawing
            # operators. PatternType 2 is a shading dict with no stream at all.
            if (
                isinstance(target, StreamObject)
                and target.get("/PatternType") == 1
                and self._take_content(pattern) is not None
            ):
                self._resources(target.get("/Resources"))

        for font in values(resolved.get("/Font")):
            target = resolve(font)
            if not isinstance(target, DictionaryObject):
                continue
            self._take_font(target)
            if target.get("/Subtype") == "/Type3":
                for glyph in values(target.get("/CharProcs")):
                    self._take_content(glyph)
                self._resources(target.get("/Resources"))

    def _take_font(self, font: DictionaryObject) -> None:
        """Size the embedded font programs, whatever flavour they are."""
        holders: list[object] = [font]
        if font.get("/Subtype") == "/Type0":
            holders = values(font.get("/DescendantFonts")) or [
                item for item in (resolve(font.get("/DescendantFonts")) or []) if item is not None
            ]
        for holder in holders:
            descriptor = resolve(resolve(holder).get("/FontDescriptor")) if isinstance(
                resolve(holder), DictionaryObject
            ) else None
            if not isinstance(descriptor, DictionaryObject):
                continue
            for key in ("/FontFile", "/FontFile2", "/FontFile3"):
                program = descriptor.get(key)
                target = resolve(program)
                if isinstance(target, StreamObject) and self._first_visit(program) is not None:
                    self.font_bytes += _stored_size(target)

    def _annotations(self, page: object) -> None:
        annots = resolve(resolve(page).get("/Annots"))
        if not isinstance(annots, (ArrayObject, list)):
            return
        for annot in annots:
            resolved = resolve(annot)
            if not isinstance(resolved, DictionaryObject):
                continue
            for appearance in values(resolved.get("/AP")):
                target = resolve(appearance)
                if isinstance(target, StreamObject):
                    if self._take_content(appearance) is not None:
                        self._resources(target.get("/Resources"))
                    continue
                # /AP /N may instead be a dictionary of named appearance states.
                for state in values(appearance):
                    inner = resolve(state)
                    if isinstance(inner, StreamObject) and self._take_content(state):
                        self._resources(inner.get("/Resources"))

    def document(self, document: PdfReader | PdfWriter) -> _Walk:
        for page in document.pages:
            contents = resolve(page.get("/Contents"))
            if isinstance(contents, (ArrayObject, list)):
                for part in contents:
                    self._take_content(part)
            elif contents is not None:
                self._take_content(page.get("/Contents"))
            self._resources(page.get("/Resources"))
            self._annotations(page)
        return self


# --- the two entry points ----------------------------------------------------


@dataclass(frozen=True, slots=True)
class Survey:
    """Where one document's bytes actually are, so we can pick a strategy."""

    file_size: int
    image_bytes: int
    content_bytes: int
    font_bytes: int = 0

    @property
    def image_share(self) -> float:
        return self.image_bytes / self.file_size if self.file_size else 0.0

    @property
    def content_share(self) -> float:
        return self.content_bytes / self.file_size if self.file_size else 0.0

    @property
    def font_share(self) -> float:
        return self.font_bytes / self.file_size if self.file_size else 0.0


def survey(source: Path) -> Survey | None:
    """Measure how ``source`` spends its bytes, or None if pypdf cannot read it.

    Cheap: it reads stream dictionaries, never stream data.
    """
    try:
        reader = PdfReader(str(source))
        walk = _Walk().document(reader)
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.info("could not survey %s: %s", source.name, error)
        return None
    return Survey(
        file_size=source.stat().st_size,
        image_bytes=walk.image_bytes,
        content_bytes=sum(_stored_size(stream) for stream in walk.content),
        font_bytes=walk.font_bytes,
    )


def rebuild(
    source: Path,
    destination: Path,
    *,
    precision: int | None = None,
    deadline: float | None = None,
    on_step: Callable[[int, int], None] | None = None,
) -> bool:
    """Write ``source`` to ``destination`` with its content streams shortened.

    Blocking and CPU-bound — call it in a thread, holding a job slot. Returns
    False if the document could not be rebuilt, in which case ``destination``
    must not be used.

    ``on_step(done, total)`` is called as each content stream is finished, for
    the progress bar. It runs on this thread, so it must not touch the event
    loop directly — see ``app.services.compress._threaded_reporter``.
    """
    try:
        writer = PdfWriter(clone_from=str(source))
        streams = _Walk().document(writer).content
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.info("could not rebuild %s: %s", source.name, error)
        return False

    for position, stream in enumerate(streams, start=1):
        if on_step is not None:
            on_step(position, len(streams))
        if deadline is not None and time.monotonic() > deadline:
            logger.warning("stream rewrite of %s ran out of time", source.name)
            return False
        try:
            decoded = stream.get_data()
        except Exception as error:  # noqa: BLE001 — a damaged or exotic filter
            logger.debug("skipping an undecodable stream in %s: %s", source.name, error)
            continue
        shortened = shorten(decoded, precision)
        # A stream that came in as raw JPX-ish bytes or that simply has nothing
        # to give would still be re-deflated below; only keep the shorter text.
        packed = zlib.compress(shortened if len(shortened) < len(decoded) else decoded, DEFLATE_LEVEL)
        if len(packed) >= _stored_size(stream) and stream.get("/Filter") == "/FlateDecode":
            continue
        stream._data = packed  # noqa: SLF001 — pypdf has no public "set encoded data"
        stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        stream[NameObject("/Length")] = NumberObject(len(packed))
        if "/DecodeParms" in stream:
            del stream["/DecodeParms"]

    try:
        with destination.open("wb") as handle:
            writer.write(handle)
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.info("could not write the rebuilt %s: %s", source.name, error)
        return False
    return True
