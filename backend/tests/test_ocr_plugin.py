"""The OCRmyPDF progress plugin.

The risk this guards is specific and large: a plugin that fails to import
makes ``ocrmypdf`` exit non-zero, and OCR is also on the PDF-to-Word and
PDF-to-Markdown paths — so one bad import here breaks three tools at once. The
version check below is cheap and proves the hook loads against whatever
version the image actually installed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.services import ocr, progress
from app.services.runner import run

from .conftest import requires_ocrmypdf


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_the_plugin_file_is_where_the_service_points() -> None:
    assert ocr.OCR_PLUGIN.is_file()


def test_the_bar_ignores_disable() -> None:
    """OCRmyPDF forces disable=True because our stderr is a pipe.

    A pipe is exactly where we want machine-readable lines, so the class
    deliberately does not honour it.
    """
    from app.tools.ocr_progress import JsonProgressBar

    bar = JsonProgressBar(total=3, desc="OCR", unit="page", disable=True)
    with bar as active:
        active.update(1)
    assert active.done == 1


def test_an_update_never_raises() -> None:
    from app.tools.ocr_progress import JsonProgressBar

    bar = JsonProgressBar(total=None, desc=None, unit=None)
    bar.update("not a number")  # type: ignore[arg-type]
    bar.update(completed=2)
    assert bar.done == 2


def test_the_reader_maps_phases_onto_the_bar() -> None:
    channel = progress.registry.claim("a" * 32)
    assert channel is not None
    publisher = progress.Publisher(channel)
    publisher.file(1, 1, "scan.pdf")

    on_line = ocr._progress_reader(publisher, ocr.WHOLE_JOB)

    def line(desc: str, done: int, total: int) -> str:
        return json.dumps({ocr.MARKER: 1, "desc": desc, "done": done, "total": total})

    on_line("stderr", line("Scanning contents", 10, 10))
    assert channel.snapshot.percent == 15.0

    on_line("stderr", line("OCR", 10, 10))
    # 90, not 100: the PDF/A tail reports nothing, so the bar stops short
    # rather than sitting at the end.
    assert channel.snapshot.percent == 90.0

    # An unrecognised phase moves nothing at all.
    on_line("stderr", line("Recompressing JPEGs", 1, 2))
    assert channel.snapshot.percent == 90.0

    progress.registry.clear()


def test_the_reader_ignores_stdout_and_other_noise() -> None:
    channel = progress.registry.claim("b" * 32)
    assert channel is not None
    publisher = progress.Publisher(channel)
    publisher.file(1, 1, "scan.pdf")
    on_line = ocr._progress_reader(publisher, ocr.WHOLE_JOB)

    payload = json.dumps({ocr.MARKER: 1, "desc": "OCR", "done": 5, "total": 5})
    on_line("stdout", payload)
    on_line("stderr", "WARNING: something ordinary happened")
    on_line("stderr", "{not json at all")
    assert channel.snapshot.percent == 0.0

    progress.registry.clear()


@requires_ocrmypdf
@pytest.mark.anyio
async def test_ocrmypdf_loads_the_plugin() -> None:
    """Cheap, and the one that catches a hook renamed in a minor release."""
    result = await run(
        ["ocrmypdf", "--plugin", str(ocr.OCR_PLUGIN), "--version"],
        operation="probe",
        check=False,
    )
    assert result.ok, result.output


@requires_ocrmypdf
@pytest.mark.anyio
async def test_a_real_ocr_run_reports_pages(tmp_path: Path, scanned_pdf: bytes) -> None:
    source = tmp_path / "scan.pdf"
    source.write_bytes(scanned_pdf)

    channel = progress.registry.claim("c" * 32)
    assert channel is not None
    publisher = progress.Publisher(channel)
    publisher.file(1, 1, "scan.pdf")
    progress.bind(publisher)
    try:
        await ocr.ocr_to_path(source, tmp_path / "out.pdf", tmp_path, ["eng"])
    finally:
        progress.bind(progress.NULL)

    percent = channel.snapshot.percent
    assert percent is not None and percent > 0
    progress.registry.clear()
