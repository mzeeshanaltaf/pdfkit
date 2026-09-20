"""The two ``app/tools`` shims: where their progress goes, and what does not move.

The load-bearing assertion here is the anydoc one. ``markdown._parse`` reads
every JSON object on *stdout* as a per-file status and ``to_markdown_one``
indexes the first positionally — so a progress line on stdout would become file
zero's verdict and break PDF to Markdown on scanned documents, and only on
scanned documents.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.services import markdown as markdown_service
from app.services import ocr as ocr_service
from app.services import word as word_service
from app.services.runner import ToolResult
from app.tools import anydoc_cli, pdf2docx_cli

from .conftest import requires_anydoc, requires_pdf2docx

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_the_markers_agree() -> None:
    """Each service duplicates its shim's marker rather than importing it.

    Importing would pull anydoc's native module and pdf2docx's PyMuPDF engine
    into the API process, which running them in a subprocess is precisely for.
    """
    assert markdown_service.MARKER == anydoc_cli.MARKER
    assert word_service.MARKER == pdf2docx_cli.MARKER


def test_the_ocr_plugin_marker_agrees() -> None:
    from app.tools import ocr_progress

    assert ocr_service.MARKER == ocr_progress.MARKER


def run_shim(module: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", module, *args],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@requires_anydoc
def test_anydoc_progress_goes_to_stderr(tmp_path: Path, text_pdf: bytes) -> None:
    source = tmp_path / "one.pdf"
    source.write_bytes(text_pdf)
    out_dir = tmp_path / "out"

    result = run_shim("app.tools.anydoc_cli", str(out_dir), str(source))

    assert anydoc_cli.MARKER in result.stderr
    assert anydoc_cli.MARKER not in result.stdout


@requires_anydoc
def test_anydoc_stdout_still_parses_as_the_status_contract(
    tmp_path: Path, text_pdf: bytes
) -> None:
    source = tmp_path / "one.pdf"
    source.write_bytes(text_pdf)
    out_dir = tmp_path / "out"

    result = run_shim("app.tools.anydoc_cli", str(out_dir), str(source))
    parsed = markdown_service._parse(
        ToolResult(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr)
    )

    assert len(parsed) == 1
    assert parsed[0]["input"] == "one.pdf"
    assert "status" in parsed[0]


def test_parse_ignores_an_object_that_is_not_a_status() -> None:
    """The second lock on the same door: even on stdout, progress is skipped."""
    stdout = (
        json.dumps({anydoc_cli.MARKER: 1, "done": 0, "total": 1})
        + "\n"
        + json.dumps({"input": "one.pdf", "status": "ok", "characters": 12})
        + "\n"
    )
    parsed = markdown_service._parse(ToolResult(returncode=0, stdout=stdout, stderr=""))

    assert len(parsed) == 1
    assert parsed[0]["status"] == "ok"


@requires_pdf2docx
def test_pdf2docx_progress_goes_to_stderr(tmp_path: Path, text_pdf: bytes) -> None:
    source = tmp_path / "one.pdf"
    source.write_bytes(text_pdf)
    destination = tmp_path / "one.docx"

    result = run_shim("app.tools.pdf2docx_cli", str(source), str(destination))
    assert result.returncode == 0
    assert destination.exists()

    lines = [
        json.loads(line)
        for line in result.stderr.splitlines()
        if pdf2docx_cli.MARKER in line
    ]
    assert lines, "the shim reported no progress at all"
    assert {line["phase"] for line in lines} == {pdf2docx_cli.PARSE, pdf2docx_cli.WRITE}
    # The fixture is three pages, and every page is counted in both phases.
    assert max(line["done"] for line in lines) == lines[0]["total"] == 3
    assert pdf2docx_cli.MARKER not in result.stdout
