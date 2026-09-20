"""Ghostscript's per-page lines, and the flag whose absence produces them.

``-dQUIET`` is exactly the kind of flag someone tidies back in. It would not
break compression, it would silently kill the only honest progress signal on a
scanned document — so this file ties the two together.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services import compress, progress

from .conftest import requires_ghostscript


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_the_quiet_flag_is_not_on_the_command_line() -> None:
    argv = compress._ghostscript(
        Path("in.pdf"), Path("out.pdf"), compress.PRESETS["recommended"]
    )
    assert "-dQUIET" not in argv


def test_the_reporter_reads_ghostscript_page_lines() -> None:
    channel = progress.registry.claim("f" * 32)
    assert channel is not None
    publisher = progress.Publisher(channel)
    publisher.file(1, 1, "one.pdf")

    cursor = compress._Cursor(publisher)
    cursor.start("ghostscript")
    base = channel.snapshot.percent

    on_line = compress._ghostscript_reporter(cursor)
    # Anything before the total is known moves nothing.
    on_line("stdout", "Page 1")
    assert channel.snapshot.percent == base

    on_line("stdout", "Processing pages 1 through 4.")
    on_line("stdout", "Page 2")
    halfway = channel.snapshot.percent
    assert halfway is not None and base is not None and halfway > base

    on_line("stdout", "Page 4")
    assert channel.snapshot.percent == 100.0

    progress.registry.clear()


def test_the_reporter_ignores_stderr() -> None:
    """Ghostscript's warnings are chatty and none of them are progress."""
    channel = progress.registry.claim("e" * 32)
    assert channel is not None
    publisher = progress.Publisher(channel)
    publisher.file(1, 1, "one.pdf")
    cursor = compress._Cursor(publisher)
    cursor.start("ghostscript")

    on_line = compress._ghostscript_reporter(cursor)
    on_line("stderr", "Processing pages 1 through 4.")
    on_line("stderr", "Page 2")
    assert channel.snapshot.percent == 65.0  # the step's own start, unmoved

    progress.registry.clear()


@requires_ghostscript
@pytest.mark.anyio
async def test_a_real_compression_reports_every_page(tmp_path: Path, photo_pdf: bytes) -> None:
    source = tmp_path / "one.pdf"
    source.write_bytes(photo_pdf)

    seen: list[str] = []
    from app.services.runner import run

    await run(
        compress._ghostscript(source, tmp_path / "out.pdf", compress.PRESETS["recommended"]),
        operation="compress",
        check=False,
        on_line=lambda stream, line: seen.append(line) if stream == "stdout" else None,
    )

    assert any(line.startswith("Processing pages") for line in seen)
    assert any(line.startswith("Page 1") for line in seen)
