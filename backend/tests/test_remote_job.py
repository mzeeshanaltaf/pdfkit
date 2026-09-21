"""The ``remote_job`` shim: its result contract, its progress, and what exit 1 means.

There is no Daytona sandbox here and no network. The shim's whole point is that
it does not need one — it reads a spec, calls the same per-file service
functions the local path calls, and reports on stdout/stderr — so running it as
a plain local subprocess against a tmpdir standing in for ``/work`` exercises
exactly what a sandbox will.

That subprocess invocation *is* the ``FakeSandboxPool`` the offload design calls
for, minus a class wrapper: when Phase 2 introduces ``offload.py`` and its
``SandboxPool`` protocol, the fake it injects should reuse :func:`run_remote_job`
rather than re-deriving it.

The two assertions to keep honest as the shim grows:

* per-file failure is a *status value*, not a nonzero exit — conflating them
  would make the orchestrator fall back to the local path for a file that is
  going to fail there in exactly the same way, doubling the wait on a document
  nobody can process;
* progress goes to stderr, because stdout is the result contract and one stray
  line there would be read as a file's verdict.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.services import errors
from app.tools import anydoc_cli, ocr_progress, remote_job

from .conftest import (
    build_scanned_pdf,
    build_text_pdf,
    requires_anydoc,
    requires_ghostscript,
    requires_ocrmypdf,
    requires_pdf2docx,
    requires_tesseract,
)

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def write_spec(
    work: Path,
    operation: str,
    sources: dict[str, bytes],
    options: dict[str, object] | None = None,
) -> Path:
    """Lay out a ``/work``-shaped directory and return the path to its spec."""
    inputs = work / "in"
    inputs.mkdir(parents=True, exist_ok=True)
    files = []
    for name, data in sources.items():
        (inputs / name).write_bytes(data)
        files.append({"input": f"in/{name}", "original_name": name, "size": len(data)})

    spec = work / "spec.json"
    spec.write_text(
        json.dumps(
            {
                "operation": operation,
                "options": options or {},
                "files": files,
                "out_dir": str(work / "out"),
                "scratch_dir": str(work / "scratch"),
            }
        ),
        encoding="utf-8",
    )
    return spec


def run_remote_job(
    spec: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Invoke the shim the way a sandbox will: ``python -m``, from the package root."""
    return subprocess.run(
        [sys.executable, "-m", "app.tools.remote_job", str(spec)],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=os.environ | (env or {}),
    )


def results(completed: subprocess.CompletedProcess[str]) -> list[dict]:
    return [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]


def frames(completed: subprocess.CompletedProcess[str]) -> list[dict]:
    return [json.loads(line) for line in completed.stderr.splitlines() if line.strip()]


def test_the_markers_agree() -> None:
    """One marker across all three shims, so one reader can recognise any of them."""
    assert remote_job.MARKER == anydoc_cli.MARKER == ocr_progress.MARKER


# --- the result contract -----------------------------------------------------


@requires_ghostscript
def test_a_compressed_file_comes_back_named_and_on_disk(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path, "compress", {"a.pdf": build_text_pdf()}, {"level": "recommended"}
    )

    completed = run_remote_job(spec)

    assert completed.returncode == remote_job.EXIT_OK
    [result] = results(completed)
    assert result["input"] == "in/a.pdf"
    assert result["status"] == "ok"
    assert result["download_name"] == "a-compressed.pdf"
    assert result["media_type"] == "application/pdf"

    # The output path is relative to out_dir: that is what the orchestrator will
    # hand back to the sandbox to download.
    produced = tmp_path / "out" / result["output"]
    assert produced.is_file()
    assert produced.read_bytes().startswith(b"%PDF-")
    assert produced.stat().st_size == result["result_size"] > 0


def test_a_file_that_cannot_be_processed_is_a_status_not_an_exit_code(
    tmp_path: Path, encrypted_pdf: bytes
) -> None:
    """An encrypted input is file-level bad news; the shim itself ran fine."""
    spec = write_spec(tmp_path, "compress", {"locked.pdf": encrypted_pdf})

    completed = run_remote_job(spec)

    assert completed.returncode == remote_job.EXIT_OK
    [result] = results(completed)
    assert result == {
        "input": "in/locked.pdf",
        "status": "error",
        # Verbatim from the HTTPException `ensure_readable` raises, so the
        # orchestrator can re-raise the identical one on the VPS.
        "http_status": 422,
        "detail": errors.PASSWORD_REQUIRED,
    }


@requires_ghostscript
def test_one_bad_file_does_not_take_the_batch_with_it(
    tmp_path: Path, encrypted_pdf: bytes
) -> None:
    spec = write_spec(
        tmp_path,
        "compress",
        {"good.pdf": build_text_pdf(), "locked.pdf": encrypted_pdf},
    )

    completed = run_remote_job(spec)

    assert completed.returncode == remote_job.EXIT_OK
    assert [result["status"] for result in results(completed)] == ["ok", "error"]


# --- "the shim could not run" ------------------------------------------------


@pytest.mark.parametrize(
    ("spec_body", "reason"),
    [
        ({"files": [{"input": "in/a.pdf"}]}, "no operation"),
        ({"operation": "transmogrify", "files": [{"input": "in/a.pdf"}]}, "unknown"),
        ({"operation": "compress", "files": []}, "no files"),
        ({"operation": "compress", "files": [{"input": "in/absent.pdf"}]}, "missing"),
    ],
)
def test_a_spec_that_is_not_work_exits_one_with_an_empty_stdout(
    tmp_path: Path, spec_body: dict, reason: str
) -> None:
    (tmp_path / "in").mkdir()
    (tmp_path / "in" / "a.pdf").write_bytes(build_text_pdf(pages=1))
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps(spec_body), encoding="utf-8")

    completed = run_remote_job(spec)

    assert completed.returncode == remote_job.EXIT_CANNOT_RUN, reason
    # Strictly empty, not merely "no ok lines": stdout is the result contract,
    # and the diagnostic belongs on stderr with the progress.
    assert completed.stdout.strip() == ""
    assert json.loads(completed.stderr.strip())["status"] == "failed"


def test_malformed_json_cannot_run(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text("{not json", encoding="utf-8")

    completed = run_remote_job(spec)

    assert completed.returncode == remote_job.EXIT_CANNOT_RUN
    assert completed.stdout.strip() == ""


# --- progress ----------------------------------------------------------------


@requires_ghostscript
def test_progress_is_json_on_stderr_and_never_goes_backwards(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path,
        "compress",
        {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf(pages=1)},
    )

    completed = run_remote_job(spec)

    assert completed.returncode == remote_job.EXIT_OK
    assert remote_job.MARKER not in completed.stdout

    published = frames(completed)
    assert published, "the shim published no progress at all"

    seen: dict[int, float] = {}
    for frame in published:
        assert frame[remote_job.MARKER] == 1
        assert frame["scope"] == remote_job.SCOPE
        assert frame["total"] == 2
        percent = frame["percent"]
        if percent is None:
            continue
        index = frame["file"]
        assert percent >= seen.get(index, 0.0), f"file {index} went backwards"
        seen[index] = percent

    assert set(seen) >= {1, 2}
    assert published[-1]["percent"] == 100.0


@requires_ghostscript
def test_a_batch_with_a_failure_never_reports_finished(
    tmp_path: Path, encrypted_pdf: bytes
) -> None:
    """The shim does not own terminality when something went wrong.

    Locally it is the ``job_publisher`` dependency that publishes the terminal
    frame, with ``reason=ERROR`` and the bar left where it stopped. A 100 here
    would be a "finished" frame for a batch the orchestrator is about to
    re-raise a 422 from.
    """
    spec = write_spec(
        tmp_path,
        "compress",
        {"good.pdf": build_text_pdf(pages=1), "locked.pdf": encrypted_pdf},
    )

    completed = run_remote_job(spec)

    assert completed.returncode == remote_job.EXIT_OK
    assert all(frame["percent"] != 100.0 for frame in frames(completed))


# --- dispatch: the right per-file function for each operation ----------------


@requires_ocrmypdf
@requires_tesseract
def test_ocr_dispatches_to_ocr_one(tmp_path: Path) -> None:
    spec = write_spec(tmp_path, "ocr", {"scan.pdf": build_scanned_pdf(pages=2)})

    completed = run_remote_job(spec)

    [result] = results(completed)
    assert result["status"] == "ok", result
    assert result["download_name"] == "scan-ocr.pdf"
    assert (tmp_path / "out" / result["output"]).read_bytes().startswith(b"%PDF-")


@requires_pdf2docx
def test_word_dispatches_to_to_word_one(tmp_path: Path) -> None:
    spec = write_spec(tmp_path, "word", {"report.pdf": build_text_pdf(pages=1)})

    completed = run_remote_job(spec)

    [result] = results(completed)
    assert result["status"] == "ok", result
    assert result["download_name"] == "report.docx"
    assert result["media_type"].endswith("wordprocessingml.document")
    assert (tmp_path / "out" / result["output"]).stat().st_size > 0


@requires_anydoc
def test_markdown_dispatches_to_to_markdown_one(tmp_path: Path) -> None:
    spec = write_spec(tmp_path, "markdown", {"notes.pdf": build_text_pdf(pages=1)})

    completed = run_remote_job(spec)

    [result] = results(completed)
    assert result["status"] == "ok", result
    assert result["download_name"] == "notes.md"
    assert (tmp_path / "out" / result["output"]).read_text(encoding="utf-8")


# --- the concurrency limit the sandbox is sized with -------------------------


@pytest.mark.parametrize("requested", ["1", "4"])
def test_the_process_sizes_its_semaphore_from_the_environment(requested: str) -> None:
    """``runner._slots`` binds at import, which is what the sandbox exploits.

    A sandbox gets more cores than the VPS, and ``os.cpu_count()`` inside one
    reports the *runner's* cores, not the sandbox's quota — so the orchestrator
    passes the real figure in as ``MAX_CONCURRENT_JOBS`` and the shim's process
    picks up a correctly-sized limit with no code change in ``runner.py``.
    """
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.services.runner import _slots; print(_slots._value)",
        ],
        cwd=PACKAGE_ROOT,
        capture_output=True,
        text=True,
        check=True,
        env=os.environ | {"MAX_CONCURRENT_JOBS": requested},
    )

    assert completed.stdout.strip() == requested


@requires_ghostscript
def test_a_multi_file_batch_completes_under_a_single_slot(tmp_path: Path) -> None:
    spec = write_spec(
        tmp_path,
        "compress",
        {"a.pdf": build_text_pdf(pages=1), "b.pdf": build_text_pdf(pages=1)},
    )

    completed = run_remote_job(spec, env={"MAX_CONCURRENT_JOBS": "1"})

    assert completed.returncode == remote_job.EXIT_OK
    assert [result["status"] for result in results(completed)] == ["ok", "ok"]
