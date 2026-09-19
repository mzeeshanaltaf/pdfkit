"""Subsetting embedded fonts down to the glyphs a document actually draws.

Word embeds whole font programs. A two-page company profile with a single emoji
in it carries the complete 7.7 MB Segoe UI Emoji — 91% of which is the ``COLR``
colour-layer table for thousands of emoji the document never mentions — and the
file is 4 MB for two pages of text. Ghostscript reports that it subset the font
and shrinks it barely at all, because its subsetter does not understand ``COLR``
and copies it through whole.

fontTools does understand it, so this module finds every glyph the document
draws and rebuilds each embedded font around exactly those. On the file above
that is 4,073,060 bytes down to 54,395, rendering pixel for pixel the same.

Two things make that safe rather than reckless:

*The ids are kept where they are.* A PDF names glyphs by number, so a subsetter
that renumbers them — which is the normal thing for a subsetter to do — silently
swaps or drops characters. ``retain_gids`` is what stops that; without it, the
en-dashes in the test document turned into blanks.

*Anything unfamiliar is refused.* If a content stream will not parse, or a
character code cannot be placed in the font with certainty, that font is left
exactly as it was. The caller then renders the result and compares it against
the input, so a scanning mistake costs a compression opportunity rather than
somebody's text.
"""

from __future__ import annotations

import io
import logging
import time
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from fontTools.agl import toUnicode
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    ContentStream,
    DictionaryObject,
    IndirectObject,
    NameObject,
    NumberObject,
    StreamObject,
)

from app.services.streams import DEFLATE_LEVEL, resolve, values

logger = logging.getLogger(__name__)

# The operators that put glyphs on the page.
_SHOW = (b"Tj", b"'", b'"', b"TJ")

# Only these carry a font program fontTools can open. A bare CFF (/FontFile3
# with /Subtype /Type1C) and a Type 1 (/FontFile) are not sfnt containers, and
# both are small enough in practice that they are not worth the risk.
_PROGRAM_KEYS = ("/FontFile2", "/FontFile3")

# Cmap subtables, in the order a viewer consults them for a simple font.
_SYMBOL = (3, 0)
_UNICODE = ((3, 1), (3, 10), (0, 3), (0, 4), (0, 6))
_MAC_ROMAN = (1, 0)


class Unmappable(Exception):
    """This font cannot be subset with certainty, so it will not be touched."""


def _raw(item: object) -> bytes:
    """The bytes of a PDF string as they appear in the file.

    pypdf hands back text strings already decoded, which is the wrong end of the
    problem: we need the original codes, because those are what index the font.
    """
    original = getattr(item, "original_bytes", None)
    if original is not None:
        return bytes(original)
    return item if isinstance(item, bytes) else b""


@dataclass(slots=True)
class _Program:
    """One embedded font program and the glyphs found pointing at it."""

    stream: StreamObject
    gids: set[int] = field(default_factory=set)
    usable: bool = True
    _font: TTFont | None = None

    def font(self) -> TTFont:
        if self._font is None:
            self._font = TTFont(io.BytesIO(self.stream.get_data()), lazy=False, fontNumber=0)
        return self._font

    def stored_size(self) -> int:
        data = getattr(self.stream, "_data", b"")
        return len(data) if isinstance(data, (bytes, bytearray)) else 0


def _program_of(font: DictionaryObject) -> tuple[IndirectObject | None, DictionaryObject | None]:
    """The embedded program for a font dict, plus the dict that describes it.

    For a Type0 font the descriptor hangs off the descendant CIDFont, which is
    also where /CIDToGIDMap lives, so both are returned.
    """
    holder: object = font
    if font.get("/Subtype") == "/Type0":
        descendants = resolve(font.get("/DescendantFonts"))
        if not isinstance(descendants, (ArrayObject, list)) or not descendants:
            return None, None
        holder = resolve(descendants[0])
    if not isinstance(holder, DictionaryObject):
        return None, None

    descriptor = resolve(holder.get("/FontDescriptor"))
    if not isinstance(descriptor, DictionaryObject):
        return None, None
    for key in _PROGRAM_KEYS:
        reference = descriptor.get(key)
        program = resolve(reference)
        if not isinstance(program, StreamObject) or not isinstance(reference, IndirectObject):
            continue
        if key == "/FontFile3" and program.get("/Subtype") != "/OpenType":
            continue
        return reference, holder
    return None, None


def _differences(font: DictionaryObject) -> dict[int, str]:
    """code → glyph name, from a simple font's /Encoding /Differences array."""
    names: dict[int, str] = {}
    encoding = resolve(font.get("/Encoding"))
    if not isinstance(encoding, DictionaryObject):
        return names
    table = resolve(encoding.get("/Differences"))
    if not isinstance(table, (ArrayObject, list)):
        return names
    code = 0
    for item in table:
        item = resolve(item)
        if isinstance(item, (int, float)):
            code = int(item)
        else:
            names[code] = str(item).lstrip("/")
            code += 1
    return names


def _cmaps(font: TTFont) -> tuple[dict | None, dict | None, dict | None]:
    if "cmap" not in font:
        return None, None, None
    symbol = unicode_table = mac = None
    for table in font["cmap"].tables:
        pair = (table.platformID, table.platEncID)
        if pair == _SYMBOL:
            symbol = table.cmap
        elif pair in _UNICODE and unicode_table is None:
            unicode_table = table.cmap
        elif pair == _MAC_ROMAN:
            mac = table.cmap
    return symbol, unicode_table, mac


class _Scan:
    """Walks everything that can draw text and records the glyphs it draws."""

    def __init__(self, document: PdfWriter) -> None:
        self.document = document
        self.programs: dict[tuple[int, int], _Program] = {}
        self._seen_streams: set[int] = set()
        self._seen_resources: set[int] = set()

    # -- collecting -----------------------------------------------------------

    def _record(self, font: DictionaryObject, data: bytes) -> None:
        reference, holder = _program_of(font)
        if reference is None or holder is None:
            return
        key = (reference.idnum, reference.generation)
        entry = self.programs.get(key)
        if entry is None:
            entry = self.programs[key] = _Program(stream=resolve(reference))
        if not entry.usable:
            return
        try:
            if font.get("/Subtype") == "/Type0":
                self._record_cid(entry, holder, font, data)
            else:
                self._record_simple(entry, font, data)
        except Exception as error:  # noqa: BLE001 — any doubt means hands off
            logger.info("not subsetting a font: %s", error)
            entry.usable = False

    def _record_cid(
        self, entry: _Program, holder: DictionaryObject, font: DictionaryObject, data: bytes
    ) -> None:
        # Identity-H/V is the encoding Word, LibreOffice and every other modern
        # producer uses, and is the only one where a code maps to a glyph without
        # consulting a CMap file we would also have to parse.
        if font.get("/Encoding") not in ("/Identity-H", "/Identity-V"):
            raise Unmappable("CID font with a non-identity encoding")
        mapping = resolve(holder.get("/CIDToGIDMap"))
        table = mapping.get_data() if isinstance(mapping, StreamObject) else None
        if table is None and mapping not in (None, "/Identity"):
            raise Unmappable("CID font with an unreadable CIDToGIDMap")
        for index in range(0, len(data) - 1, 2):
            cid = data[index] << 8 | data[index + 1]
            if table is not None:
                offset = cid * 2
                cid = table[offset] << 8 | table[offset + 1] if offset + 1 < len(table) else 0
            entry.gids.add(cid)

    def _record_simple(self, entry: _Program, font: DictionaryObject, data: bytes) -> None:
        program = entry.font()
        symbol, unicode_table, mac = _cmaps(program)
        names = _differences(font)
        by_name = {name: gid for gid, name in enumerate(program.getGlyphOrder())}

        for code in set(data):
            gid = None
            name = names.get(code)
            if name is not None:
                gid = by_name.get(name)
            if gid is None and symbol:
                # A symbolic TrueType is addressed through the (3,0) subtable,
                # where codes usually live in the 0xF000 private-use block.
                for candidate in (0xF000 | code, code):
                    if candidate in symbol:
                        gid = by_name.get(symbol[candidate])
                        break
            if gid is None and unicode_table:
                text = toUnicode(name) if name else chr(code)
                for char in text or "":
                    if ord(char) in unicode_table:
                        gid = by_name.get(unicode_table[ord(char)])
                        break
            if gid is None and mac is not None and code in mac:
                gid = by_name.get(mac[code])
            if gid is None:
                raise Unmappable(f"no glyph for code {code} in a simple font")
            entry.gids.add(gid)

    # -- traversal ------------------------------------------------------------

    def _content(self, stream: object, resources: object) -> None:
        """Read one content stream against the resources it draws with."""
        fonts = resolve(resolve(resources).get("/Font")) if isinstance(
            resolve(resources), DictionaryObject
        ) else None
        parsed = ContentStream(stream, self.document)
        current: object = None
        for operands, operator in parsed.operations:
            if operator == b"Tf" and operands:
                current = resolve(fonts.get(operands[0])) if isinstance(
                    fonts, DictionaryObject
                ) else None
                continue
            if operator not in _SHOW or not isinstance(current, DictionaryObject):
                continue
            operand = operands[-1] if operands else None
            parts = operand if isinstance(operand, (ArrayObject, list)) else [operand]
            data = b"".join(_raw(part) for part in parts)
            if data:
                self._record(current, data)

    def _once(self, obj: object) -> bool:
        reference = getattr(obj, "indirect_reference", None)
        key = reference.idnum if reference else id(obj)
        if key in self._seen_streams:
            return False
        self._seen_streams.add(key)
        return True

    def _resources(self, resources: object, inherited: object) -> None:
        """Recurse into the drawable streams a resource dictionary names."""
        resolved = resolve(resources)
        if not isinstance(resolved, DictionaryObject) or id(resolved) in self._seen_resources:
            return
        self._seen_resources.add(id(resolved))

        for form in values(resolved.get("/XObject")):
            target = resolve(form)
            if not isinstance(target, StreamObject) or target.get("/Subtype") != "/Form":
                continue
            if not self._once(form):
                continue
            own = target.get("/Resources") or inherited
            self._content(target, own)
            self._resources(own, inherited)

        for pattern in values(resolved.get("/Pattern")):
            target = resolve(pattern)
            if isinstance(target, StreamObject) and target.get("/PatternType") == 1:
                if not self._once(pattern):
                    continue
                own = target.get("/Resources") or inherited
                self._content(target, own)
                self._resources(own, inherited)

        for font in values(resolved.get("/Font")):
            target = resolve(font)
            if isinstance(target, DictionaryObject) and target.get("/Subtype") == "/Type3":
                own = target.get("/Resources") or inherited
                for glyph in values(target.get("/CharProcs")):
                    stream = resolve(glyph)
                    if isinstance(stream, StreamObject) and self._once(glyph):
                        self._content(stream, own)
                self._resources(own, inherited)

    def run(self) -> None:
        for page in self.document.pages:
            resources = page.get("/Resources")
            contents = page.get_contents()
            if contents is not None:
                self._content(contents, resources)
            self._resources(resources, resources)
            self._annotations(page, resources)

    def _annotations(self, page: object, inherited: object) -> None:
        annots = resolve(resolve(page).get("/Annots"))
        if not isinstance(annots, (ArrayObject, list)):
            return
        for annot in annots:
            resolved = resolve(annot)
            if not isinstance(resolved, DictionaryObject):
                continue
            for appearance in values(resolved.get("/AP")):
                for candidate in (appearance, *values(appearance)):
                    stream = resolve(candidate)
                    if not isinstance(stream, StreamObject) or not self._once(candidate):
                        continue
                    own = stream.get("/Resources") or inherited
                    self._content(stream, own)
                    self._resources(own, inherited)


def _rebuild(entry: _Program) -> bytes:
    font = entry.font()
    order = font.getGlyphOrder()
    glyphs = sorted({order[gid] for gid in entry.gids if 0 <= gid < len(order)})

    options = Options()
    options.drop_tables = []
    options.passthrough_tables = True
    options.notdef_outline = True
    options.recalc_bounds = False
    options.name_IDs = ["*"]
    # A PDF addresses glyphs by number, so they must stay at the numbers the
    # content streams already name. Without this, subsetting silently reassigns
    # every glyph and the document renders the wrong characters.
    options.retain_gids = True

    subsetter = Subsetter(options=options)
    subsetter.populate(glyphs=glyphs)
    subsetter.subset(font)
    out = io.BytesIO()
    font.save(out)
    return out.getvalue()


def subset(source: Path, destination: Path, *, deadline: float | None = None) -> bool:
    """Rewrite ``source`` into ``destination`` with its fonts cut to size.

    Blocking and CPU-bound — call it in a thread, holding a job slot. Returns
    False when nothing was gained or the document could not be handled, in which
    case ``destination`` must not be used.

    A True result still has to be checked by the caller: see this module's
    docstring on why the rendered pages are compared before it is trusted.
    """
    try:
        writer = PdfWriter(clone_from=str(source))
        scan = _Scan(writer)
        scan.run()
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.info("could not scan the fonts in %s: %s", source.name, error)
        return False

    gained = 0
    for entry in scan.programs.values():
        if deadline is not None and time.monotonic() > deadline:
            logger.warning("font subsetting of %s ran out of time", source.name)
            return False
        if not entry.usable or not entry.gids:
            continue
        before = entry.stored_size()
        try:
            rebuilt = _rebuild(entry)
        except Exception as error:  # noqa: BLE001 — fontTools raises broadly too
            logger.info("could not subset a font in %s: %s", source.name, error)
            continue
        packed = zlib.compress(rebuilt, DEFLATE_LEVEL)
        if len(packed) >= before:
            continue
        entry.stream._data = packed  # noqa: SLF001 — no public "set encoded data"
        entry.stream[NameObject("/Filter")] = NameObject("/FlateDecode")
        entry.stream[NameObject("/Length")] = NumberObject(len(packed))
        # /Length1 is the decoded length of a TrueType program; a stale one makes
        # some readers reject the font.
        if "/Length1" in entry.stream:
            entry.stream[NameObject("/Length1")] = NumberObject(len(rebuilt))
        if "/DecodeParms" in entry.stream:
            del entry.stream["/DecodeParms"]
        gained += before - len(packed)

    if gained <= 0:
        return False

    try:
        with destination.open("wb") as handle:
            writer.write(handle)
    except Exception as error:  # noqa: BLE001 — pypdf raises very broadly
        logger.info("could not write the subset %s: %s", source.name, error)
        return False
    logger.info("font subsetting saved %d bytes on %s", gained, source.name)
    return True
