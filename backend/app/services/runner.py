"""The single place this app spawns a subprocess.

Every native tool (ghostscript, qpdf, ocrmypdf, pdfimages, tesseract) goes
through :func:`run`, which gives us one place to enforce a concurrency limit and
a timeout, and one place that decides how much of a tool's stderr a client is
allowed to see.

:func:`job_slot` exposes that same limit to work we do in-process rather than in
a child — compression's content-stream rewrite is pure Python but just as
CPU-hungry as Ghostscript, and must queue behind the same two slots.

Output is read as it arrives rather than buffered to exit, so a caller can pass
``on_line`` and watch a tool report its own progress. That is what turns
"something is happening on the server" into "page 12 of 29". See :func:`_spawn`
for the two things that rewrite had to get right.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.config import MAX_CONCURRENT_JOBS, QUEUE_TIMEOUT_SECONDS, timeout_for
from app.services import progress

logger = logging.getLogger(__name__)

# Native tools are CPU- and memory-hungry; this is what stops a burst of
# requests from thrashing a small VPS.
#
# This — like `app.services.ratelimit`'s store — is per-process state, and so
# only means what it says while uvicorn runs with `--workers 1`
# (backend/Dockerfile). Two workers would silently double both ceilings.
_slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"]+")
MAX_DETAIL_LENGTH = 300

# Read size per pipe. Matches the pipe buffer, so a chatty child is drained in
# whole-buffer bites rather than a syscall per line.
READ_CHUNK = 64 * 1024

# How much of each stream is kept for ``ToolResult``. Output is only ever used
# for an error excerpt or a status line, and one runaway tool should not be able
# to put a gigabyte in a tmpfs-backed container's memory. Before this file
# streamed its pipes, ``communicate()`` kept everything, unbounded.
MAX_CAPTURED_BYTES = 1024 * 1024

# A "line" longer than this is not a line — some tool is emitting a blob with no
# separator in it. Hand it over as-is and start again rather than growing the
# pending buffer without limit.
MAX_PENDING_LINE = 64 * 1024

_LINE_BREAK = re.compile(rb"\r\n|\r|\n")

# Called with (stream_name, line) for every line a tool writes, as it writes it.
# Never awaited: it runs inline on the read pump, so an implementation that
# blocks blocks the draining of that pipe.
OnLine = Callable[[str, str], None]


@dataclass(slots=True)
class ToolResult:
    """Outcome of one subprocess."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def output(self) -> str:
        """stderr and stdout together — tools are inconsistent about which they use."""
        return f"{self.stderr}\n{self.stdout}".strip()


def sanitise(message: str) -> str:
    """Strip absolute paths out of tool output so temp locations never leak."""
    cleaned = _ABSOLUTE_PATH.sub("<path>", message)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) > MAX_DETAIL_LENGTH:
        cleaned = f"{cleaned[:MAX_DETAIL_LENGTH]}…"
    return cleaned


@asynccontextmanager
async def job_slot(operation: str) -> AsyncIterator[None]:
    """Hold one of the global job slots, or give up with 503.

    Waiting is bounded: a caller that cannot get a slot inside
    ``QUEUE_TIMEOUT_SECONDS`` is told the server is busy rather than left to sit
    behind an OCR run that has minutes left on it.
    """
    publisher = progress.current()
    # Only announce the wait when there is one. Publishing "queued"
    # unconditionally would put a frame nobody waited for in front of every
    # uncontended request, which reads as a flicker.
    if _slots.locked():
        publisher.queued()
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("%s rejected: no free job slot after %ss", operation, QUEUE_TIMEOUT_SECONDS)
        raise HTTPException(status_code=503, detail="server_busy") from None
    publisher.running()
    try:
        yield
    finally:
        _slots.release()


async def run(
    command: Sequence[str],
    *,
    operation: str,
    check: bool = True,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    on_line: OnLine | None = None,
) -> ToolResult:
    """Run one native tool under the global concurrency limit and its timeout.

    With ``check`` the default, a non-zero exit becomes a 500 carrying a
    sanitised excerpt of the tool's own message. Callers that need to classify
    a failure themselves (unlock, which has to tell "wrong password" apart from
    "broken file") pass ``check=False`` and read :class:`ToolResult`.

    ``on_line`` is called with ``("stdout" | "stderr", line)`` as each line
    arrives, for the tools that report their own progress.
    """
    argv = [str(part) for part in command]
    timeout = timeout_for(operation)

    async with job_slot(operation):
        result = await _spawn(
            argv, operation=operation, timeout=timeout, cwd=cwd, env=env, on_line=on_line
        )

    if check and not result.ok:
        logger.error("%s failed (%s): %s", operation, result.returncode, result.output)
        raise HTTPException(
            status_code=500,
            detail=sanitise(result.output) or f"{operation}_failed",
        )
    return result


class _Pump:
    """Reads one pipe to EOF, splitting lines out as they arrive.

    Two things this has to get right, both of which ``StreamReader.readline``
    gets wrong for our purposes: it raises ``LimitOverrunError`` on a line past
    its 64 KiB limit, and it does not treat a bare carriage return as a
    separator — so a tool that reports progress by rewriting one line with
    ``\\r`` would buffer until it exited, which is the opposite of the point.
    """

    def __init__(self, name: str, on_line: OnLine | None) -> None:
        self.name = name
        self._on_line = on_line
        self._captured = bytearray()
        self._truncated = False
        self._pending = bytearray()

    async def drain(self, stream: asyncio.StreamReader | None) -> None:
        if stream is None:
            return
        while chunk := await stream.read(READ_CHUNK):
            self._capture(chunk)
            if self._on_line is not None:
                self._split(chunk)
        # Whatever the tool wrote without a trailing newline is still a line.
        if self._on_line is not None and self._pending:
            self._emit(bytes(self._pending))
            self._pending.clear()

    def _capture(self, chunk: bytes) -> None:
        room = MAX_CAPTURED_BYTES - len(self._captured)
        if room <= 0:
            self._truncated = True
            return
        if len(chunk) > room:
            self._truncated = True
        self._captured += chunk[:room]

    def _split(self, chunk: bytes) -> None:
        self._pending += chunk
        *lines, rest = _LINE_BREAK.split(bytes(self._pending))
        for line in lines:
            self._emit(line)
        self._pending = bytearray(rest)
        # No separator in sight: hand over what we have in fixed pieces rather
        # than grow a buffer for a tool that is never going to end its "line".
        while len(self._pending) > MAX_PENDING_LINE:
            self._emit(bytes(self._pending[:MAX_PENDING_LINE]))
            del self._pending[:MAX_PENDING_LINE]

    def _emit(self, line: bytes) -> None:
        assert self._on_line is not None
        try:
            self._on_line(self.name, line.decode("utf-8", "replace"))
        except Exception:  # noqa: BLE001 — a broken listener must not kill the job
            logger.exception("progress listener raised on a %s line", self.name)

    @property
    def text(self) -> str:
        decoded = self._captured.decode("utf-8", "replace")
        return f"{decoded}\n…output truncated…" if self._truncated else decoded


async def _spawn(
    argv: Sequence[str],
    *,
    operation: str,
    timeout: int,
    cwd: Path | None,
    env: Mapping[str, str] | None,
    on_line: OnLine | None,
) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, **env} if env else None,
    )

    out, err = _Pump("stdout", on_line), _Pump("stderr", on_line)
    # Both pipes, concurrently, always. Draining one at a time is the classic
    # subprocess deadlock: a tool that fills the other pipe's 64 KiB buffer
    # blocks on write and never reaches the exit we are waiting for. Avoiding
    # exactly this is what `communicate()` was doing for us before.
    pumps = asyncio.gather(out.drain(process.stdout), err.drain(process.stderr))
    try:
        async with asyncio.timeout(timeout):
            await pumps
            await process.wait()
    except TimeoutError:
        # The pumps are cancelled but the child is not: kill it explicitly or it
        # keeps a CPU busy for the rest of the container's life.
        pumps.cancel()
        with contextlib.suppress(BaseException):
            await pumps
        process.kill()
        await process.wait()
        logger.error("%s timed out after %ss", operation, timeout)
        raise HTTPException(status_code=504, detail="processing_timed_out") from None

    return ToolResult(
        returncode=process.returncode or 0,
        stdout=out.text,
        stderr=err.text,
    )
