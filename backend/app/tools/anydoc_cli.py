"""Convert documents to Markdown with anydoc, as a standalone process.

    python -m app.tools.anydoc_cli <output-dir> <input>...

Each input is converted and written to ``<output-dir>/<input stem>.md``, and one
JSON line per input is printed to stdout::

    {"input": "00-report.pdf", "status": "ok", "characters": 812}
    {"input": "page-003.pdf", "status": "needs_ocr", "pages": [1]}

Why a subprocess at all: anydoc's Python binding is a native module doing
blocking, CPU-bound work. Every heavy job in this service goes through
``app.services.runner``, which owns the concurrency limit, the per-operation
timeout and — the part that only works on a process — killing the job when that
timeout expires. A thread cannot be killed and a native call cannot be
interrupted. It also means a panic in the Rust core costs one request rather
than the whole event loop.

Why a batch: converting a mixed document falls back to one conversion per page,
and paying a fresh interpreter start for each page adds up on a long document.
That is also why it reports progress: a hundred-page scan is a hundred
conversions inside one subprocess.

Progress goes to **stderr**, and that placement is load-bearing.
``app.services.markdown._parse`` reads every JSON object on *stdout* as a
per-file status and indexes the first one positionally, so a progress line
there would be read as file zero's result and break PDF-to-Markdown on scanned
documents only. ``_parse`` also skips objects with no ``status`` key, so it
takes two mistakes rather than one to reintroduce that.

Exit status is about whether the tool *ran*, not about whether a document could
be converted: 0 means every input was attempted and its outcome is on stdout,
1 means the batch itself could not run.

Nothing is ever sent anywhere. ``ocr="hosted"`` is deliberately never passed, so
anydoc stays entirely local; scanned pages come back as ``needs_ocr`` and are
handled by our own Tesseract in ``app.services.markdown``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

EXIT_OK = 0
EXIT_CANNOT_RUN = 1

#: Marks a progress line. Duplicated in ``app.services.markdown``;
#: ``tests/test_shims.py`` keeps them equal.
MARKER = "pdfkit_progress"

# anydoc's error classes, mapped by name to the status we report. Matching on
# the class name rather than importing seven symbols keeps this working if the
# package moves them; every one subclasses ConvertError, the only import we
# actually depend on.
_STATUS_BY_ERROR = {
    "NeedsOcrError": "needs_ocr",
    "EncryptedError": "encrypted",
    "UnsupportedError": "unreadable",
    "MalformedError": "unreadable",
    "MissingPartError": "unreadable",
    "ResourceLimitError": "too_complex",
}


def _emit(payload: dict[str, object]) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _progress(done: int, total: int) -> None:
    """One progress line, on stderr. See the module docstring on why not stdout."""
    try:
        line = json.dumps({MARKER: 1, "done": done, "total": total}, separators=(",", ":"))
        print(line, file=sys.stderr, flush=True)
    except Exception:  # noqa: BLE001 — never fail a batch over a progress line
        pass


def _convert_one(anydoc, source: Path, out_dir: Path) -> dict[str, object]:
    result: dict[str, object] = {"input": source.name}
    try:
        markdown = anydoc.to_markdown(str(source))
    except anydoc.ConvertError as error:
        name = type(error).__name__
        result["status"] = _STATUS_BY_ERROR.get(name, "failed")
        result["error"] = name
        if name == "NeedsOcrError":
            result["pages"] = [
                page for page in (getattr(error, "pages", None) or []) if isinstance(page, int)
            ]
        return result
    except Exception as error:  # noqa: BLE001 — an OSError, or a panic in the core
        result["status"] = "failed"
        result["error"] = f"{type(error).__name__}: {error}"
        return result

    (out_dir / f"{source.stem}.md").write_text(markdown, encoding="utf-8")
    result["status"] = "ok"
    result["characters"] = len(markdown)
    return result


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        _emit({"status": "failed", "error": "usage: anydoc_cli <output-dir> <input>..."})
        return EXIT_CANNOT_RUN

    out_dir = Path(argv[0])
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        import anydoc
    except ImportError as error:
        _emit({"status": "failed", "error": f"anydoc is not installed: {error}"})
        return EXIT_CANNOT_RUN

    inputs = argv[1:]
    for position, name in enumerate(inputs, start=1):
        _progress(position - 1, len(inputs))
        _emit(_convert_one(anydoc, Path(name), out_dir))
    _progress(len(inputs), len(inputs))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
