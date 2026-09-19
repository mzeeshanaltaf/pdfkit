"""The single place this app spawns a subprocess.

Every native tool (ghostscript, qpdf, ocrmypdf, pdfimages, tesseract) goes
through :func:`run`, which gives us one place to enforce a concurrency limit and
a timeout, and one place that decides how much of a tool's stderr a client is
allowed to see.

:func:`job_slot` exposes that same limit to work we do in-process rather than in
a child — compression's content-stream rewrite is pure Python but just as
CPU-hungry as Ghostscript, and must queue behind the same two slots.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.config import MAX_CONCURRENT_JOBS, QUEUE_TIMEOUT_SECONDS, timeout_for

logger = logging.getLogger(__name__)

# Native tools are CPU- and memory-hungry; this is what stops a burst of
# requests from thrashing a small VPS.
_slots = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

_ABSOLUTE_PATH = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"]+")
MAX_DETAIL_LENGTH = 300


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
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=QUEUE_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("%s rejected: no free job slot after %ss", operation, QUEUE_TIMEOUT_SECONDS)
        raise HTTPException(status_code=503, detail="server_busy") from None
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
) -> ToolResult:
    """Run one native tool under the global concurrency limit and its timeout.

    With ``check`` the default, a non-zero exit becomes a 500 carrying a
    sanitised excerpt of the tool's own message. Callers that need to classify
    a failure themselves (unlock, which has to tell "wrong password" apart from
    "broken file") pass ``check=False`` and read :class:`ToolResult`.
    """
    argv = [str(part) for part in command]
    timeout = timeout_for(operation)

    async with job_slot(operation):
        result = await _spawn(argv, operation=operation, timeout=timeout, cwd=cwd, env=env)

    if check and not result.ok:
        logger.error("%s failed (%s): %s", operation, result.returncode, result.output)
        raise HTTPException(
            status_code=500,
            detail=sanitise(result.output) or f"{operation}_failed",
        )
    return result


async def _spawn(
    argv: Sequence[str],
    *,
    operation: str,
    timeout: int,
    cwd: Path | None,
    env: Mapping[str, str] | None,
) -> ToolResult:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(cwd) if cwd else None,
        env={**os.environ, **env} if env else None,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
    except TimeoutError:
        # communicate() is cancelled but the child is not: kill it explicitly or
        # it keeps a CPU busy for the rest of the container's life.
        process.kill()
        await process.wait()
        logger.error("%s timed out after %ss", operation, timeout)
        raise HTTPException(status_code=504, detail="processing_timed_out") from None

    return ToolResult(
        returncode=process.returncode or 0,
        stdout=stdout.decode("utf-8", "replace"),
        stderr=stderr.decode("utf-8", "replace"),
    )
