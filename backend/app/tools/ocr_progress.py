"""An OCRmyPDF plugin that reports progress as JSON lines on stderr.

    ocrmypdf --plugin <path to this file> ...

Why a plugin and not just dropping ``--quiet``: OCRmyPDF's ``__main__`` sets
``options.progress_bar = False`` whenever ``sys.stderr`` is not a TTY — which,
under ``asyncio.subprocess.PIPE``, is always — and ``--quiet`` sets it too. So
there is no flag combination that makes it print per-page progress to a pipe.
The supported route is this hook, and it works precisely because the class it
returns is still *constructed and updated* even when the progress bar is
switched off; only the drawing is meant to stop. We keep ``--quiet`` (its
logging suppression is still wanted) and ignore ``disable``.

Everything here is best-effort. A progress bar that raises would take an OCR
run down with it, and OCR is also on the PDF-to-Word and PDF-to-Markdown paths,
so a bug here would break three tools at once. Every method swallows.

One event this deliberately cannot see: ``_pipeline.py`` passes
``progressbar_class=None`` for the PDF/A conversion tail, so nothing is
reported for it. That is why ``app.services.ocr`` caps this at 90% rather than
letting it reach the end.

The reported ``desc`` strings come from OCRmyPDF and its docstring warns they
may change between minor releases — hence the pin in ``pyproject.toml`` and
``tests/test_ocr_plugin.py``, which loads this against the installed version.
"""

from __future__ import annotations

import json
import sys
import time

from ocrmypdf import hookimpl

#: Marks our lines out from anything else on stderr. The reader in
#: ``app.services.ocr`` ignores every line without it.
MARKER = "pdfkit_progress"

#: Pages are seconds each, so this only collapses the bursts.
MIN_INTERVAL = 0.2


class JsonProgressBar:
    """Reports to stderr instead of drawing, and ignores ``disable``."""

    def __init__(
        self,
        *,
        total: float | int | None = None,
        desc: str | None = None,
        unit: str | None = None,
        disable: bool = False,  # noqa: ARG002 — ignored on purpose, see the module docstring
        **kwargs: object,  # noqa: ARG002 — the protocol says to tolerate new ones
    ) -> None:
        self.total = total
        self.desc = desc or ""
        self.unit = unit or ""
        self.done = 0.0
        self._last = 0.0

    def __enter__(self) -> JsonProgressBar:
        self._emit(force=True)
        return self

    def __exit__(self, *_exc: object) -> bool:
        # False: never swallow an exception OCRmyPDF is raising through us.
        return False

    def update(self, n: float | None = 1, *, completed: float | None = None) -> None:
        try:
            if completed is not None:
                self.done = float(completed)
            else:
                self.done += float(n if n is not None else 1)
            self._emit()
        except Exception:  # noqa: BLE001 — never fail the job over a progress line
            pass

    def _emit(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < MIN_INTERVAL:
            return
        self._last = now
        try:
            line = json.dumps(
                {
                    MARKER: 1,
                    "desc": self.desc,
                    "unit": self.unit,
                    "done": round(self.done, 3),
                    "total": self.total,
                },
                separators=(",", ":"),
            )
            # stderr, never stdout: OCRmyPDF can be asked to write the PDF
            # itself to stdout, and a stray line there would corrupt it.
            sys.stderr.write(f"{line}\n")
            sys.stderr.flush()
        except Exception:  # noqa: BLE001 — a closed pipe is not our problem
            pass


@hookimpl
def get_progressbar_class() -> type[JsonProgressBar]:
    return JsonProgressBar
