"""Run a batch of heavy jobs from a JSON spec, as a standalone process.

    python -m app.tools.remote_job /work/spec.json

This is the sandbox-side half of the offload design: the code that eventually
runs *inside* a Daytona sandbox, invoked as
``/opt/venv/bin/python -m app.tools.remote_job /work/spec.json`` with
``cwd=/app``. It has no Daytona dependency of its own — it reads a spec, calls
the same per-file service functions the local path calls, and reports on
stdout/stderr — so a plain local subprocess is a complete stand-in for a
sandbox, which is how it is tested.

Third shim in the ``app/tools`` family, and deliberately the same shape as
``anydoc_cli`` and ``pdf2docx_cli``: results as one JSON line per input on
**stdout**, progress on **stderr**, and an exit status that is about whether the
shim *ran*, not about whether a document could be processed. Exit 0 means every
file was attempted and its outcome is on stdout; exit 1 means the batch itself
could not run.

A JSON spec rather than argv, because the options differ in shape across the
four operations — ``compress`` takes ``level``, ``word`` and ``markdown`` take
``ocr_mode`` plus ``languages`` — and per-operation argv parsing would drift as
those change.

**The seam is the per-file function, not the batch driver.** ``compress_one``
alone fires ~20 subprocesses interleaved with pure-Python CPU work that has no
argv at all, so there is no point further down where a job could be handed off
without either paying twenty round trips or leaving the expensive half on the
VPS. Calling the existing per-file functions unmodified is also what makes an
offloaded job byte-identical to a local one, errors included.

**Files are processed one at a time**, exactly as the batch drivers do it. Two
reasons, and both matter: a single :class:`~app.services.progress.Publisher`
carries one file index at a time, so concurrent files would interleave into
incoherent progress frames; and sequential is what the local path does, which is
the behaviour an offloaded job has to reproduce. The concurrency that does get
sized here is the one *inside* a file — ``runner._slots`` is a module-level
semaphore bound at import from ``config.MAX_CONCURRENT_JOBS``, so setting that
environment variable on this process to the sandbox's own vCPU count gives the
sandbox a correctly-sized limit for free, with no change to ``runner.py``. Note
that it has to be passed in: ``os.cpu_count()`` inside a Daytona sandbox reports
the *runner's* cores (measured 48 against a 4-CPU quota), not the sandbox's.

``progress.stop_if_cancelled()`` is a no-op here — nothing binds a disconnect
probe in this process. Cancellation stays a VPS-side concern for the
orchestrator that owns the client connection, not something the shim decides.
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.deps import SavedUpload
from app.services import compress as compress_service
from app.services import markdown as markdown_service
from app.services import ocr as ocr_service
from app.services import progress
from app.services import word as word_service
from app.services.responses import OutputFile

EXIT_OK = 0
EXIT_CANNOT_RUN = 1

#: Marks a progress line, shared with the other shims. ``tests/test_remote_job``
#: keeps them equal.
MARKER = "pdfkit_progress"

#: Distinguishes these frames from the other shims' once an orchestrator is
#: reading several streams at once.
SCOPE = "remote"


class _StderrPublisher(progress.Publisher):
    """A publisher with no channel, writing one JSON frame per update to stderr.

    Built the way :class:`~app.services.progress.NullPublisher` is — its own
    ``__init__`` setting up the base class's slots, and an override of the one
    method that touches a channel. Everything else (the fold from a per-file
    percentage into a batch-wide one, the monotonic clamp) is inherited, so the
    numbers on stderr are the numbers the local path would have published.

    The services need no changes for this: they already publish through
    whatever ``progress.current()`` returns.
    """

    __slots__ = ()

    def __init__(self) -> None:  # noqa: D107 — there is no channel to hold
        self._channel = None  # type: ignore[assignment]
        self._index = 0
        self._total = 0
        self._name = ""
        self._step = ""
        self._percent = None

    def _emit(self, phase: str) -> None:
        self._write(self._percent)

    def finish(self, reason: str = progress.DONE) -> None:
        # Publisher.finish() publishes straight to the channel rather than
        # through _emit, so it needs its own override here just as it does in
        # NullPublisher.
        self._write(100.0 if reason == progress.DONE else self._percent)

    def _write(self, percent: float | None) -> None:
        try:
            line = json.dumps(
                {
                    MARKER: 1,
                    "scope": SCOPE,
                    "file": self._index,
                    "total": self._total,
                    "name": self._name,
                    "step": self._step,
                    "percent": percent,
                },
                separators=(",", ":"),
            )
            print(line, file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001 — never fail a batch over a progress line
            pass


class _SpecError(ValueError):
    """The spec cannot be turned into work. Always exit 1, never a file result."""


@dataclass(slots=True)
class _Job:
    """One entry of the spec: the name to echo back, and the file to work on."""

    input: str
    upload: SavedUpload


#: An operation's per-file call. Takes everything from the spec it could need,
#: so the four of them share one signature and dispatch stays a dict lookup.
Runner = Callable[
    [SavedUpload, Path, Path, dict[str, Any], progress.Publisher], Awaitable[OutputFile]
]


@dataclass(frozen=True, slots=True)
class _Operation:
    run: Runner
    #: Merged under the spec's ``options``. Mirrors each router's own defaults.
    defaults: dict[str, Any] = field(default_factory=dict)
    #: The step label the batch driver shows when a file starts. Kept identical
    #: so an offloaded job's progress text matches a local one word for word.
    first_step: str = ""


async def _run_compress(
    upload: SavedUpload,
    out_dir: Path,
    scratch: Path,
    options: dict[str, Any],
    publisher: progress.Publisher,
) -> OutputFile:
    # _Cursor is private to compress, and reaching for it is intentional: it is
    # what `compress.compress` passes, and the point of this shim is to be the
    # same call. Dropping it would silently lose every intra-file step.
    return await compress_service.compress_one(
        upload, out_dir, str(options["level"]), compress_service._Cursor(publisher)
    )


async def _run_ocr(
    upload: SavedUpload,
    out_dir: Path,
    scratch: Path,
    options: dict[str, Any],
    publisher: progress.Publisher,
) -> OutputFile:
    return await ocr_service.ocr_one(upload, out_dir, scratch, _languages(options))


async def _run_word(
    upload: SavedUpload,
    out_dir: Path,
    scratch: Path,
    options: dict[str, Any],
    publisher: progress.Publisher,
) -> OutputFile:
    return await word_service.to_word_one(
        upload, out_dir, scratch, str(options["ocr_mode"]), _languages(options)
    )


async def _run_markdown(
    upload: SavedUpload,
    out_dir: Path,
    scratch: Path,
    options: dict[str, Any],
    publisher: progress.Publisher,
) -> OutputFile:
    return await markdown_service.to_markdown_one(
        upload, out_dir, scratch, str(options["ocr_mode"]), _languages(options)
    )


def _languages(options: dict[str, Any]) -> list[str]:
    raw = options.get("languages") or [ocr_service.DEFAULT_LANGUAGE]
    if isinstance(raw, str):  # a single code, sent unwrapped
        raw = [raw]
    return [str(code) for code in raw]


OPERATIONS: dict[str, _Operation] = {
    "compress": _Operation(
        run=_run_compress,
        defaults={"level": compress_service.DEFAULT_LEVEL},
    ),
    "ocr": _Operation(
        run=_run_ocr,
        defaults={"languages": [ocr_service.DEFAULT_LANGUAGE]},
        first_step="Reading the pages",
    ),
    # "off" and "auto" are the defaults app.routers.convert passes for /word
    # and /markdown respectively.
    "word": _Operation(
        run=_run_word,
        defaults={"ocr_mode": "off", "languages": [ocr_service.DEFAULT_LANGUAGE]},
        first_step="Rebuilding the document",
    ),
    "markdown": _Operation(
        run=_run_markdown,
        defaults={"ocr_mode": "auto", "languages": [ocr_service.DEFAULT_LANGUAGE]},
        first_step="Reading the document",
    ),
}


@dataclass(slots=True)
class _Spec:
    operation: str
    options: dict[str, Any]
    jobs: list[_Job]
    out_dir: Path
    scratch_dir: Path


def _load_spec(path: Path) -> _Spec:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise _SpecError(f"cannot read {path}: {error}") from error
    except ValueError as error:
        raise _SpecError(f"{path} is not valid JSON: {error}") from error
    if not isinstance(raw, dict):
        raise _SpecError("spec must be a JSON object")

    operation = raw.get("operation")
    if operation not in OPERATIONS:
        raise _SpecError(
            f"operation must be one of {', '.join(sorted(OPERATIONS))}, not {operation!r}"
        )

    entries = raw.get("files")
    if not isinstance(entries, list) or not entries:
        raise _SpecError("files must be a non-empty list")

    supplied = raw.get("options") or {}
    if not isinstance(supplied, dict):
        raise _SpecError("options must be a JSON object")
    options = dict(OPERATIONS[operation].defaults) | supplied

    # Relative inputs resolve against the spec, so a sandbox can be handed
    # {"input": "in/a.pdf"} next to /work/spec.json and nothing has to know the
    # absolute path the orchestrator happened to choose.
    base = path.parent
    jobs: list[_Job] = []
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("input"):
            raise _SpecError(f"each file needs an input path, got {entry!r}")
        name = str(entry["input"])
        source = Path(name)
        source = source if source.is_absolute() else base / source
        if not source.is_file():
            raise _SpecError(f"no such input file: {source}")
        jobs.append(
            _Job(
                input=name,
                upload=SavedUpload(
                    path=source,
                    original_name=str(entry.get("original_name") or source.name),
                    size=int(entry.get("size") or source.stat().st_size),
                ),
            )
        )

    return _Spec(
        operation=operation,
        options=options,
        jobs=jobs,
        out_dir=_directory(raw.get("out_dir"), base / "out"),
        scratch_dir=_directory(raw.get("scratch_dir"), base / "scratch"),
    )


def _directory(value: Any, fallback: Path) -> Path:
    return Path(str(value)) if value else fallback


def _emit(payload: dict[str, Any]) -> None:
    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


def _cannot_run(reason: str) -> int:
    """Report a failure of the shim itself.

    On **stderr**, unlike ``anydoc_cli``'s equivalent: stdout here is strictly
    the per-file result contract, and an orchestrator that sees exit 1 falls
    back to the local path rather than parsing anything. Leaving stdout empty
    makes "no result lines" unambiguous.
    """
    print(json.dumps({"status": "failed", "error": reason}), file=sys.stderr, flush=True)
    return EXIT_CANNOT_RUN


def _relative(path: Path, out_dir: Path) -> str:
    """The output's path as the orchestrator will ask for it: relative to out_dir."""
    try:
        return str(path.relative_to(out_dir))
    except ValueError:
        return str(path)


async def _run(spec: _Spec) -> int:
    publisher = _StderrPublisher()
    progress.bind(publisher)

    operation = OPERATIONS[spec.operation]
    spec.out_dir.mkdir(parents=True, exist_ok=True)
    spec.scratch_dir.mkdir(parents=True, exist_ok=True)

    total = len(spec.jobs)
    failed = False
    for index, job in enumerate(spec.jobs, start=1):
        publisher.file(index, total, job.upload.original_name, operation.first_step)
        try:
            output = await operation.run(
                job.upload, spec.out_dir, spec.scratch_dir, spec.options, publisher
            )
        except HTTPException as error:
            # Recorded verbatim so the orchestrator can re-raise the identical
            # HTTPException on the VPS. The services raise these deliberately
            # for client consumption (`ensure_readable` gives 422
            # password_required; the 500s have already been through
            # `sanitise`), so there is nothing here left to scrub.
            _emit(
                {
                    "input": job.input,
                    "status": "error",
                    "http_status": error.status_code,
                    "detail": error.detail,
                }
            )
            failed = True
            continue
        _emit(
            {
                "input": job.input,
                "status": "ok",
                "output": _relative(output.path, spec.out_dir),
                "download_name": output.download_name,
                "media_type": output.media_type,
                "result_size": output.path.stat().st_size,
            }
        )

    # Only on a clean batch. A per-file cursor stops well short of 100 —
    # locally it is the `job_publisher` dependency that publishes the terminal
    # frame once the endpoint returns, and on a failure it publishes one with
    # `reason=ERROR` and the percentage left where it stopped. Emitting an
    # unconditional 100 here would hand the orchestrator a "finished" frame for
    # a batch it is about to re-raise a 422 from.
    if not failed:
        publisher.finish()
    return EXIT_OK


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        return _cannot_run("usage: remote_job <spec.json>")
    try:
        spec = _load_spec(Path(argv[0]))
    except _SpecError as error:
        return _cannot_run(str(error))
    try:
        return asyncio.run(_run(spec))
    except Exception as error:  # noqa: BLE001 — anything but a per-file HTTPException
        # A batch driver would have let this reach the endpoint as a 500, so
        # the offloaded equivalent is "this job did not run": the orchestrator
        # falls back to the local path rather than inventing a per-file verdict.
        return _cannot_run(f"{type(error).__name__}: {error}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
