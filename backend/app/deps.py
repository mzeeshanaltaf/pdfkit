"""Request-scoped plumbing: the upload batch, and the per-request dependencies.

Upload handling deliberately avoids a FastAPI dependency with ``yield``. Since
FastAPI 0.106 the exit half of such a dependency runs *before* the response body
is sent, which would delete the very files we are about to stream back. Temp
directories are therefore owned by an explicit :class:`UploadBatch` and torn
down by a ``BackgroundTask`` attached to the response (see
``app.services.responses``).

:func:`job_publisher` *is* a ``yield`` dependency, and that same timing is what
makes it right: the job is over by the time the endpoint returns, so publishing
the terminal frame before the download starts streaming is exactly when the
progress bar should reach the end.

The four dependencies at the bottom are attached per-router in ``app.main``
rather than per-endpoint, so an endpoint added later cannot forget one.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import HTTPException, Request, UploadFile

from app import config
from app.config import (
    MAX_BATCH_BYTES,
    MAX_BATCH_MB,
    MAX_FILES_PER_REQUEST,
    MAX_UPLOAD_BYTES,
    MAX_UPLOAD_MB,
    WORK_DIR,
)
from app.services import auth, progress, ratelimit

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1024 * 1024
PDF_MAGIC = b"%PDF-"

# A conforming PDF starts with %PDF- at byte 0, but plenty of real-world files
# carry a few junk bytes in front and every reader tolerates it, so we do too.
MAGIC_SEARCH_WINDOW = 1024

_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]+")
_COLLAPSE = re.compile(r"\s+")
MAX_NAME_LENGTH = 120


def display_name(raw: str | None) -> str:
    """A client-supplied name made safe to echo back, extension left alone.

    Used in error messages: telling someone their ``notes.txt`` is not a PDF
    only makes sense if we quote the name they actually chose.
    """
    candidate = (raw or "").strip()
    # Cut any directory component the client may have sent, in either slash style.
    candidate = candidate.replace("\\", "/").rsplit("/", 1)[-1]
    candidate = _UNSAFE_CHARS.sub("_", candidate)
    candidate = _COLLAPSE.sub(" ", candidate).strip(" ._")
    return candidate[:MAX_NAME_LENGTH] or "document"


def sanitise_filename(raw: str | None) -> str:
    """Reduce a client-supplied name to a plain, safe ``*.pdf`` basename."""
    candidate = display_name(raw)

    stem, dot, ext = candidate.rpartition(".")
    if dot and ext.lower() == "pdf":
        candidate = stem
    if not candidate:
        candidate = "document"
    return f"{candidate[:MAX_NAME_LENGTH]}.pdf"


@dataclass(slots=True)
class SavedUpload:
    """One validated upload, already on disk inside the batch's temp directory."""

    path: Path
    original_name: str
    size: int


@dataclass(slots=True)
class UploadBatch:
    """The temp directory for one request, plus the uploads saved into it."""

    directory: Path
    files: list[SavedUpload] = field(default_factory=list)

    @property
    def single(self) -> SavedUpload:
        return self.files[0]

    def workspace(self, name: str) -> Path:
        """A fresh sub-directory of the batch, for one tool's intermediate output."""
        path = self.directory / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def cleanup(self) -> None:
        shutil.rmtree(self.directory, ignore_errors=True)


def _scratch_root() -> Path:
    """The directory per-request temp dirs are created in.

    WORK_DIR is a tmpfs in the container. It can be unusable in two ways: it
    does not exist at all (a developer machine, where /tmp/pdfkit is not a
    thing), or it exists but is not writable by us — a tmpfs mounted by the
    orchestrator masks the ownership the image set at build time, so a
    misconfigured mount lands here as root-owned. Either way, falling back to
    the platform temp directory keeps the service working; requests are still
    cleaned up, they just aren't on a tmpfs, so it is worth a warning.
    """
    root = Path(WORK_DIR)
    try:
        root.mkdir(parents=True, exist_ok=True)
        if os.access(root, os.W_OK | os.X_OK):
            return root
        reason = "not writable"
    except OSError as error:
        reason = str(error)

    fallback = Path(tempfile.gettempdir()) / "pdfkit"
    fallback.mkdir(parents=True, exist_ok=True)
    logger.warning("WORK_DIR %s unusable (%s); using %s", root, reason, fallback)
    return fallback


async def save_uploads(uploads: Sequence[UploadFile]) -> UploadBatch:
    """Stream uploads to a private temp directory, rejecting anything unusable.

    Raises 400 for an empty request, 413 for a file over the per-file cap or
    the batch over its combined cap, and 415 for something that is not a PDF.
    The temp directory is removed before the exception leaves this function,
    so a rejected request leaves nothing behind.
    """
    if not uploads:
        raise HTTPException(status_code=400, detail="no_files")
    if len(uploads) > MAX_FILES_PER_REQUEST:
        raise HTTPException(status_code=400, detail="too_many_files")

    batch = UploadBatch(directory=Path(tempfile.mkdtemp(dir=_scratch_root())))
    inputs = batch.workspace("in")
    batch_total = 0
    try:
        for index, upload in enumerate(uploads):
            saved = await _save_one(upload, inputs, index, batch_total)
            batch_total += saved.size
            batch.files.append(saved)
    except BaseException:
        batch.cleanup()
        raise
    return batch


async def _save_one(
    upload: UploadFile, directory: Path, index: int, batch_total: int
) -> SavedUpload:
    original_name = sanitise_filename(upload.filename)
    shown = display_name(upload.filename)
    # Prefix with the position so two uploads named the same do not collide.
    destination = directory / f"{index:02d}-{original_name}"

    size = 0
    head = b""
    with destination.open("wb") as sink:
        while chunk := await upload.read(CHUNK_SIZE):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"{shown} is over the {MAX_UPLOAD_MB} MB limit.",
                )
            if batch_total + size > MAX_BATCH_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail=f"This batch is over the {MAX_BATCH_MB} MB combined limit.",
                )
            if len(head) < MAGIC_SEARCH_WINDOW:
                head += chunk[: MAGIC_SEARCH_WINDOW - len(head)]
            sink.write(chunk)
    await upload.close()

    if size == 0:
        raise HTTPException(status_code=400, detail=f"{shown} is empty.")
    if PDF_MAGIC not in head:
        raise HTTPException(
            status_code=415, detail=f"{shown} is not a PDF file."
        )

    return SavedUpload(path=destination, original_name=original_name, size=size)


@asynccontextmanager
async def upload_batch(uploads: Sequence[UploadFile]) -> AsyncIterator[UploadBatch]:
    """Save uploads and guarantee cleanup on any failure.

    On success the batch survives the block: ownership passes to the response,
    which deletes it once the bytes have been sent.
    """
    batch = await save_uploads(uploads)
    try:
        yield batch
    except BaseException:
        batch.cleanup()
        raise


# --- per-router dependencies -------------------------------------------------

JOB_ID = re.compile(r"^[0-9a-f]{32}$")


async def coarse_rate_limit(request: Request) -> None:
    """A wide per-IP ceiling, applied before anything more expensive.

    Runs ahead of the token check so an unauthenticated flood is bounded
    without ever reaching the work — and so it is the only limiter that has to
    hold state for a caller who never had a token.
    """
    ratelimit.enforce(request, "coarse", config.RATE_LIMIT_COARSE)


async def require_token(request: Request) -> None:
    if not auth.enabled():
        return
    try:
        auth.verify(auth.bearer(request.headers.get("Authorization")))
    except auth.TokenError as error:
        raise HTTPException(
            status_code=401,
            detail=error.code,
            headers={"WWW-Authenticate": "Bearer"},
        ) from None


async def job_rate_limit(request: Request) -> None:
    """The real limit on processing work: a burst window and an hourly one."""
    ratelimit.enforce(
        request, "job", config.RATE_LIMIT_JOB_BURST, config.RATE_LIMIT_JOB_HOURLY
    )


async def progress_rate_limit(request: Request) -> None:
    ratelimit.enforce(request, "progress", config.RATE_LIMIT_PROGRESS)


async def job_publisher(request: Request) -> AsyncIterator[None]:
    """Bind this request's progress publisher, and close its channel after.

    A missing, malformed or already-claimed ``X-Job-Id`` is not an error: the
    request runs with the no-op publisher and the client falls back to the
    indeterminate bar it had before any of this existed.
    """
    job_id = request.headers.get("X-Job-Id", "")
    channel = progress.registry.claim(job_id) if JOB_ID.match(job_id) else None
    if channel is None:
        # No progress, but still cancellable: giving up on work nobody is
        # waiting for is worth doing whether or not anyone is watching it.
        progress.bind(progress.NULL, request.is_disconnected)
        yield
        return

    publisher = progress.Publisher(channel)
    # is_disconnected is what lets a cancelled run stop the batch server-side;
    # the body is already on disk by the time any service asks, so it is
    # reliable here.
    progress.bind(publisher, request.is_disconnected)
    try:
        yield
    except HTTPException as error:
        publisher.finish(
            progress.TIMEOUT if error.status_code == 504 else progress.ERROR
        )
        raise
    except BaseException:
        publisher.finish(progress.ERROR)
        raise
    else:
        publisher.finish(progress.DONE)
    finally:
        progress.registry.release(job_id)
