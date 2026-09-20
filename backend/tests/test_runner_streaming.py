"""The streaming rewrite of ``runner._spawn``.

Needs none of the Docker-only tools: every child here is ``sys.executable -c``,
so this file runs everywhere and is the guard on the riskiest edit in the
service — one that, got wrong, turns every chatty tool into a 504.
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from fastapi import HTTPException

from app.services import runner


def child(source: str) -> list[str]:
    return [sys.executable, "-c", source]


async def spawn(source: str, *, operation: str = "probe", on_line=None):
    return await runner.run(child(source), operation=operation, check=False, on_line=on_line)


def unix(text: str) -> str:
    """Python's text-mode stdout writes CRLF on Windows; the tools do not care."""
    return text.replace("\r\n", "\n")


@pytest.mark.anyio
async def test_captures_both_streams_intact() -> None:
    """The contract every existing caller depends on, unchanged."""
    result = await spawn(
        "import sys; sys.stdout.write('out1\\nout2\\n'); "
        "sys.stderr.write('err1\\n'); sys.exit(3)"
    )
    assert unix(result.stdout) == "out1\nout2\n"
    assert unix(result.stderr) == "err1\n"
    assert result.returncode == 3
    assert not result.ok


@pytest.mark.anyio
async def test_lines_arrive_in_order_per_stream() -> None:
    seen: list[tuple[str, str]] = []
    await spawn(
        "import sys\n"
        "for i in range(50):\n"
        "    print(f'out {i}')\n"
        "    print(f'err {i}', file=sys.stderr)\n",
        on_line=lambda stream, line: seen.append((stream, line)),
    )
    assert [line for stream, line in seen if stream == "stdout"] == [
        f"out {i}" for i in range(50)
    ]
    assert [line for stream, line in seen if stream == "stderr"] == [
        f"err {i}" for i in range(50)
    ]


@pytest.mark.anyio
async def test_a_megabyte_on_both_pipes_does_not_deadlock() -> None:
    """The exact regression ``communicate()`` was protecting us from.

    Reading one pipe to EOF before the other lets a child fill the 64 KiB
    buffer on the one nobody is draining, where it blocks on write until the
    operation times out — turning a working tool into a 504 for no reason.
    """
    result = await asyncio.wait_for(
        spawn(
            "import sys\n"
            "block = 'x' * 1024\n"
            "for _ in range(1024):\n"
            "    sys.stdout.write(block + '\\n')\n"
            "    sys.stderr.write(block + '\\n')\n"
        ),
        timeout=30,
    )
    assert result.ok
    assert len(result.stdout) > 1_000_000
    assert len(result.stderr) > 1_000_000


@pytest.mark.anyio
async def test_one_enormous_line_stays_under_the_cap() -> None:
    """A 10 MiB blob with no newline in it: capped, not buffered forever.

    ``StreamReader.readline`` would raise on this, which is why the pump
    splits chunks by hand.
    """
    lines: list[int] = []
    result = await spawn(
        "import sys; sys.stdout.write('y' * (10 * 1024 * 1024))",
        on_line=lambda stream, line: lines.append(len(line)),
    )
    assert result.ok
    assert len(result.stdout) <= runner.MAX_CAPTURED_BYTES + len("\n…output truncated…")
    assert "…output truncated…" in result.stdout
    # Handed over in pieces rather than grown without limit.
    assert lines and max(lines) <= runner.MAX_PENDING_LINE


@pytest.mark.anyio
async def test_carriage_returns_are_line_breaks() -> None:
    """A tool that redraws one line with \\r must not buffer until it exits."""
    seen: list[str] = []
    await spawn(
        "import sys; sys.stdout.write('10%\\r20%\\r30%\\n')",
        on_line=lambda stream, line: seen.append(line),
    )
    assert seen == ["10%", "20%", "30%"]


@pytest.mark.anyio
async def test_timeout_kills_the_child_and_raises_504(monkeypatch) -> None:
    monkeypatch.setattr(runner, "timeout_for", lambda _operation: 1)

    with pytest.raises(HTTPException) as raised:
        await spawn("import time; time.sleep(30)")
    assert raised.value.status_code == 504
    assert raised.value.detail == "processing_timed_out"


@pytest.mark.anyio
async def test_a_listener_that_raises_does_not_fail_the_job() -> None:
    def explode(stream: str, line: str) -> None:
        raise RuntimeError("progress listener is broken")

    result = await spawn("print('hello')", on_line=explode)
    assert result.ok
    assert unix(result.stdout) == "hello\n"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
