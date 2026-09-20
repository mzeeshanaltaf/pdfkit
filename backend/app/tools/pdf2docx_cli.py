"""Convert a PDF to .docx with pdf2docx, as a standalone process.

    python -m app.tools.pdf2docx_cli <input> <output>

This replaces the ``pdf2docx convert`` CLI, for one reason: pdf2docx throws
away the spaces between words on PDFs that position each word individually.

How that happens. A PDF is under no obligation to write a space character —
it can place ``This``, then move the cursor and place ``is``, and a reader is
expected to infer the gap. MuPDF does infer it, and synthesises a space; but
because each word arrived with its own positioning, it puts that space in a
*span of its own*. pdf2docx then drops every span whose text is blank and
carries no styling (``pdf2docx/text/Spans.py``, ``Spans.restore``), on the
assumption that such a span is a stray blank — so every inter-word space in
the document disappears and the output reads ``Thisistocertifythat``.

The fix is to keep a blank span when it sits *between* two spans that have
content, and keep discarding the ones at either end (which is what pdf2docx's
own ``Line.strip()`` would do to them anyway). Restricting it to interior
spans is what makes this safe: such a span lies inside the line's existing
bounding box, so no line's geometry changes, and the layout analysis that
detects paragraphs and tables sees exactly what it saw before. Only the text
of the runs differs. That was verified against a set of PDFs — the line bboxes
come out bit-identical with and without this shim.

Why a subprocess, as with ``pdf2docx convert`` before it: ``app.services.runner``
can only enforce a timeout on something it can kill, and it keeps pdf2docx's
AGPL PyMuPDF engine in a process of its own.

It also reports progress, as JSON lines on **stderr**, because a page-by-page
rebuild of a long document is minutes of silence otherwise::

    {"pdfkit_progress": 1, "phase": "parse", "done": 3, "total": 12}

Both instrumented methods are patched the same defensive way as the whitespace
fix below: if pdf2docx has moved something, we warn and convert without
progress rather than not converting.
"""

from __future__ import annotations

import json
import sys

EXIT_OK = 0
EXIT_FAILED = 1

#: Marks our lines out from pdf2docx's own logging, which also goes to stderr.
#: Duplicated in ``app.services.word``; ``tests/test_shims.py`` keeps them equal.
MARKER = "pdfkit_progress"

PARSE = "parse"
WRITE = "write"


def _emit(phase: str, done: int, total: int) -> None:
    """One progress line. stderr only — stdout is not ours to write on."""
    try:
        line = json.dumps(
            {MARKER: 1, "phase": phase, "done": done, "total": total},
            separators=(",", ":"),
        )
        print(line, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 — never fail a conversion over a progress line
        pass


def _patch_progress(total: int) -> None:
    """Count pages through ``Page.parse`` and ``Page.make_docx``.

    Those are the two loops in ``Converter`` that are O(pages) and slow, and
    they are the per-page call the loops make rather than the loops
    themselves — so the count is right whichever of ``convert`` / ``parse`` /
    ``make_docx`` the caller drives.
    """
    from pdf2docx.page.Page import Page

    counters = {PARSE: 0, WRITE: 0}

    def counting(phase: str, original):
        def wrapper(self, *args, **kwargs):
            try:
                result = original(self, *args, **kwargs)
            finally:
                counters[phase] += 1
                _emit(phase, counters[phase], total)
            return result

        return wrapper

    Page.parse = counting(PARSE, Page.parse)
    Page.make_docx = counting(WRITE, Page.make_docx)


def _patch_spans() -> None:
    """Teach ``Spans.restore`` to keep the blank spans that are real spaces."""
    from pdf2docx.image.ImageSpan import ImageSpan
    from pdf2docx.text.Spans import Spans
    from pdf2docx.text.TextSpan import TextSpan

    def restore(self, raws: list):
        # An image always counts as content; a text span counts unless it is
        # blank and unstyled — the exact test pdf2docx uses to discard one.
        blank = []
        for raw in raws:
            if "image" in raw:
                blank.append(False)
            else:
                span = TextSpan(raw)
                blank.append(not (span.text.strip() or span.style))
        content = [i for i, is_blank in enumerate(blank) if not is_blank]
        first, last = (content[0], content[-1]) if content else (0, -1)

        for i, raw in enumerate(raws):
            if "image" in raw:
                span = ImageSpan(raw)
            else:
                span = TextSpan(raw)
                if blank[i] and not first < i < last:
                    span = None
            self.append(span)
        return self

    Spans.restore = restore


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: pdf2docx_cli <input.pdf> <output.docx>", file=sys.stderr)
        return EXIT_FAILED

    source, destination = argv

    try:
        _patch_spans()
    except Exception as error:  # noqa: BLE001 — pdf2docx moved something
        # Losing the spaces is bad; refusing to convert at all is worse.
        print(f"could not apply the whitespace fix: {error}", file=sys.stderr)

    from pdf2docx import Converter

    converter = Converter(source)
    try:
        try:
            _patch_progress(len(converter.fitz_doc))
        except Exception as error:  # noqa: BLE001 — same posture as above
            print(f"could not report progress: {error}", file=sys.stderr)
        converter.convert(destination)
    finally:
        converter.close()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
