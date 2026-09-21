"""``offload``: when a batch goes to a sandbox, and what happens when one breaks.

Fully offline. There is no Daytona here and no API key: everything Daytona-
specific lives behind :class:`~app.services.offload.SandboxPool`, so a fake
over a tmpdir exercises the whole orchestration — staging, the result contract,
progress relay, cancellation and every fallback branch.

Two fakes, because they answer different questions:

* :class:`FakeSandboxPool` runs the **real shim** as a local subprocess (via
  ``tests/test_remote_job.py::run_remote_job``, which that module's docstring
  already names as its intended reuse). It is what proves an offloaded batch
  produces the same file the local path would.
* :class:`ScriptedPool` emits canned lines on a schedule. It is what proves the
  orchestration does the right thing when a sandbox misbehaves — something a
  real shim, being correct, will not do on demand.

The assertion worth keeping honest as this grows is the **negative** one: a
document that cannot be processed must never fall back to the local path. It
would fail there identically, having also burned the round trip and doubled the
wait on a file nobody can process.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import HTTPException

from app import config
from app.deps import SavedUpload, UploadBatch
from app.services import compress as compress_service
from app.services import errors, offload, placement, progress, sandbox_stats
from app.services import markdown as markdown_service
from app.services import ocr as ocr_service
from app.services import word as word_service
from app.tools import remote_job

from .conftest import (
    build_scanned_pdf,
    build_text_pdf,
    has_scalable_font,
    requires_anydoc,
    requires_ghostscript,
    requires_ocrmypdf,
    requires_pdf2docx,
    requires_qpdf,
    requires_tesseract,
)
from .test_convert import docx_text
from .test_remote_job import run_remote_job

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _fresh_offload() -> Iterator[None]:
    """The semaphore is process-global, like every other ceiling in this app."""
    offload.reset()
    progress.bind(progress.NULL, None)
    placement.mark_server()
    yield
    offload.reset()
    progress.bind(progress.NULL, None)
    placement.mark_server()


#: Every operation with an offload head. The gate, the fallbacks and the error
#: contract are all operation-agnostic, so the tests that say so run across the
#: whole set rather than proving it for whichever one happened to be wired first.
OPERATIONS = ("ocr", "word", "markdown", "compress")

#: Stands in for "an allowlist naming every operation but this one" — which can
#: only be built once the parametrized operation is known.
OTHERS = object()


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Offloading on, with gates a two-file fixture batch clears.

    Via ``monkeypatch.setattr(config, ...)``, which only works because
    ``offload`` reads every one of these as ``config.X`` inside the function
    that uses it — an imported name would bind a copy at import and make this
    silently useless.
    """
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    monkeypatch.setattr(config, "DAYTONA_OPERATIONS", list(OPERATIONS))
    monkeypatch.setattr(config, "DAYTONA_MIN_FILES", 1)
    monkeypatch.setattr(config, "DAYTONA_MIN_BYTES", 0)
    monkeypatch.setattr(config, "DAYTONA_FALLBACK_LOCAL", True)


def make_batch(directory: Path, sources: dict[str, bytes]) -> UploadBatch:
    """An ``UploadBatch`` shaped exactly as ``deps.save_uploads`` leaves one."""
    batch = UploadBatch(directory=directory)
    inputs = batch.workspace("in")
    for index, (name, data) in enumerate(sources.items()):
        path = inputs / f"{index:02d}-{name}"
        path.write_bytes(data)
        batch.files.append(
            SavedUpload(path=path, original_name=name, size=len(data))
        )
    return batch


# --- the fake that runs the real shim ----------------------------------------


class FakeSandboxPool:
    """:class:`SandboxPool` over a tmpdir, running the real shim locally.

    ``provision``/``dispose`` are a directory create and remove; ``put``/``get``
    are file copies. The one thing a local subprocess genuinely cannot fake is
    the *path*: the sandbox's ``/work`` is this tmpdir here, so every path is
    translated on the way in and out — including the two inside ``spec.json``,
    which the orchestrator writes as absolute sandbox paths.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.provisioned: list[str] = []
        self.disposed: list[str] = []
        self.commands: list[tuple[str, str, dict[str, str]]] = []
        #: sandbox id -> the spec it was given, kept because ``dispose`` takes
        #: the tmpdir with it and a shard's slice is only visible here.
        self.specs: dict[str, Any] = {}

    # -- the protocol

    async def provision(self) -> str:
        sandbox_id = f"fake-{len(self.provisioned)}"
        (self.root / sandbox_id / "work").mkdir(parents=True)
        self.provisioned.append(sandbox_id)
        return sandbox_id

    async def put(self, sandbox_id: str, path: str, data: bytes) -> None:
        if path.endswith("spec.json"):
            data = self._rewrite_spec(sandbox_id, data)
        local = self._local(sandbox_id, path)
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_bytes(data)

    async def get(self, sandbox_id: str, path: str) -> bytes:
        return self._local(sandbox_id, path).read_bytes()

    async def run(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str,
        env: dict[str, str],
        on_line: Callable[[str, str], None] | None = None,
    ) -> int:
        self.commands.append((sandbox_id, command, dict(env)))
        if "remote_job" not in command:
            # The `tar xzf` that unpacks app/. A local subprocess already has
            # the real package on its PYTHONPATH, so there is nothing to do —
            # but the orchestrator's exit-code check still has to pass.
            return 0

        spec = self._local(sandbox_id, f"{offload.WORK}/spec.json")
        completed = await asyncio.to_thread(run_remote_job, spec, env)
        for line in completed.stdout.splitlines():
            on_line("stdout", line)
        for line in completed.stderr.splitlines():
            on_line("stderr", line)
        return completed.returncode

    async def dispose(self, sandbox_id: str) -> None:
        self.disposed.append(sandbox_id)
        shutil.rmtree(self.root / sandbox_id, ignore_errors=True)

    # -- the tmpdir standing in for /work

    def _local(self, sandbox_id: str, path: str) -> Path:
        relative = path.lstrip("/")
        return self.root / sandbox_id / relative

    def _rewrite_spec(self, sandbox_id: str, data: bytes) -> bytes:
        spec = json.loads(data)
        self.specs[sandbox_id] = spec
        for key in ("out_dir", "scratch_dir"):
            spec[key] = str(self._local(sandbox_id, spec[key]))
        return json.dumps(spec).encode("utf-8")


class ScriptedPool:
    """A pool that emits exactly the lines a test asks for, then an exit code.

    For the failure shapes a correct shim will not produce on demand: a
    provision that dies, a sandbox that disappears mid-batch, a run long enough
    for a client to hang up during it.

    Every ``provision`` hands back its own id, because a sharded batch really
    does hold several sandboxes at once and "disposed exactly once" is only a
    meaningful assertion if they can be told apart. The scripted lines are
    replayed per shard: a two-shard batch sees them twice, once down each.
    """

    def __init__(
        self,
        lines: list[tuple[str, str]] | None = None,
        exit_code: int = 0,
        provision_error: Exception | None = None,
        run_error: Exception | None = None,
        pause: float = 0.0,
        files: dict[str, bytes] | None = None,
    ) -> None:
        self.lines = lines or []
        self.exit_code = exit_code
        self.provision_error = provision_error
        self.run_error = run_error
        self.pause = pause
        self.files = files or {}
        self.provisioned: list[str] = []
        self.disposed: list[str] = []
        self.put_paths: list[str] = []
        self.specs: list[dict[str, Any]] = []

    async def provision(self) -> str:
        if self.provision_error is not None:
            raise self.provision_error
        sandbox_id = f"scripted-{len(self.provisioned)}"
        self.provisioned.append(sandbox_id)
        return sandbox_id

    async def put(self, sandbox_id: str, path: str, data: bytes) -> None:
        self.put_paths.append(path)
        if path.endswith("spec.json"):
            self.specs.append(json.loads(data))

    async def get(self, sandbox_id: str, path: str) -> bytes:
        return self.files[path]

    async def run(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str,
        env: dict[str, str],
        on_line: Callable[[str, str], None] | None = None,
    ) -> int:
        if "remote_job" not in command:
            return 0
        for stream, line in self.lines:
            on_line(stream, line)
            if self.pause:
                await asyncio.sleep(self.pause)
        if self.run_error is not None:
            raise self.run_error
        if self.pause:
            # Long enough for a watchdog tick to land while we are "running".
            await asyncio.sleep(self.pause * 50)
        return self.exit_code

    async def dispose(self, sandbox_id: str) -> None:
        self.disposed.append(sandbox_id)


def use(monkeypatch: pytest.MonkeyPatch, pool: Any) -> Any:
    monkeypatch.setattr(offload, "pool_factory", lambda: pool)
    return pool


def result_line(name: str, output: str, size: int) -> str:
    return json.dumps(
        {
            "input": f"in/{name}",
            "status": "ok",
            "output": output,
            "download_name": output,
            "media_type": "application/pdf",
            "result_size": size,
        }
    )


def frame(
    file: int,
    total: int,
    percent: float | None,
    step: str = "Reading",
    name: str = "",
) -> str:
    return json.dumps(
        {
            offload.MARKER: 1,
            "scope": "remote",
            "file": file,
            "total": total,
            "name": name or f"{file}.pdf",
            "step": step,
            "percent": percent,
        }
    )


# --- the shims agree ---------------------------------------------------------


def test_the_progress_marker_matches_the_shims() -> None:
    """Copied, not imported — importing remote_job here would be a cycle."""
    assert offload.MARKER == remote_job.MARKER


# --- the decision gate -------------------------------------------------------


@pytest.mark.parametrize("operation", OPERATIONS)
async def test_offloading_is_off_by_default(tmp_path: Path, operation: str) -> None:
    """The default config must leave every existing code path untouched.

    `DAYTONA_OPERATIONS` now names all four by default, so the only thing
    standing between a stock deployment and a sandbox is `DAYTONA_ENABLED` —
    worth asserting per operation rather than for whichever one is handy.
    """
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()})
    assert await offload.maybe_offload(operation, batch, {}) is None


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize(
    ("knob", "value"),
    [
        ("DAYTONA_ENABLED", False),
        ("DAYTONA_OPERATIONS", OTHERS),
        ("DAYTONA_MIN_FILES", 5),
        ("DAYTONA_MIN_BYTES", 500_000_000),
    ],
)
async def test_a_failed_gate_never_touches_the_pool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    operation: str,
    knob: str,
    value: object,
) -> None:
    """Every knob gates every operation — nothing here special-cases OCR."""
    if value is OTHERS:
        value = [name for name in OPERATIONS if name != operation]
    monkeypatch.setattr(config, knob, value)
    pool = use(monkeypatch, ScriptedPool())
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert await offload.maybe_offload(operation, batch, {}) is None
    assert pool.provisioned == []


def test_eligible_is_none_when_every_gate_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})
    assert offload.eligible("compress", batch) is None


@pytest.mark.parametrize(
    ("knob", "value", "expected"),
    [
        ("DAYTONA_ENABLED", False, "DAYTONA_ENABLED=false"),
        ("DAYTONA_OPERATIONS", ["word"], "DAYTONA_OPERATIONS=['word']"),
        ("DAYTONA_MIN_FILES", 5, "is under DAYTONA_MIN_FILES=5"),
        ("DAYTONA_MIN_BYTES", 500_000_000, "is under DAYTONA_MIN_BYTES=500000000"),
    ],
)
def test_eligible_names_each_failing_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    knob: str,
    value: object,
    expected: str,
) -> None:
    """Every refusal names the gate that refused and its configured value."""
    monkeypatch.setattr(config, knob, value)
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    reason = offload.eligible("compress", batch)

    assert reason is not None
    assert expected in reason


def test_eligible_uses_the_singular_for_one_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    monkeypatch.setattr(config, "DAYTONA_MIN_FILES", 2)
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert offload.eligible("compress", batch) == "1 file is under DAYTONA_MIN_FILES=2"


async def test_maybe_offload_logs_the_refusal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(config, "DAYTONA_MIN_FILES", 5)
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    with caplog.at_level(logging.INFO, logger="app.services.offload"):
        assert await offload.maybe_offload("compress", batch, {}) is None

    assert "offload skipped for compress: 1 file is under DAYTONA_MIN_FILES=5" in caplog.text


async def test_the_success_path_logs_file_and_sandbox_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """One INFO naming both counts — today a working feature logs nothing else."""
    output = b"%PDF-1.4 x"
    use(
        monkeypatch,
        ScriptedPool(
            lines=[("stdout", result_line("a.pdf", "a-compressed.pdf", len(output)))],
            files={f"{offload.WORK}/out/a-compressed.pdf": output},
        ),
    )
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    with caplog.at_level(logging.INFO, logger="app.services.offload"):
        outputs = await offload.maybe_offload("compress", batch, {})

    assert outputs is not None
    assert "offloading 1 file(s) of compress across 1 sandbox(es)" in caplog.text


async def test_a_saturated_pool_runs_locally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The ceiling bounds sandboxes, and never queues a request behind one."""
    monkeypatch.setattr(config, "DAYTONA_MAX_SANDBOXES", 1)
    pool = use(monkeypatch, ScriptedPool())
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    await offload._slots().acquire()  # stand in for a batch already out there
    try:
        assert await offload.maybe_offload("ocr", batch, {}) is None
    finally:
        offload._slots().release()
    assert pool.provisioned == []


async def test_a_half_busy_pool_shards_into_what_is_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """One permit is one sandbox, so a partly-busy pool means fewer shards.

    Three files would take all three sandboxes; with one already out there
    the batch takes the two that are left rather than queueing for the third.
    """
    monkeypatch.setattr(config, "DAYTONA_MAX_SANDBOXES", 3)
    pool = use(monkeypatch, ScriptedPool(exit_code=1))
    batch = make_batch(
        tmp_path,
        {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf(), "c.pdf": build_text_pdf()},
    )

    await offload._slots().acquire()
    try:
        assert await offload.maybe_offload("compress", batch, {}) is None
    finally:
        offload._slots().release()
    assert pool.provisioned == ["scripted-0", "scripted-1"]


# --- the happy path, through the real shim -----------------------------------


@requires_ghostscript
async def test_a_batch_comes_back_as_real_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    pool = use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(
        tmp_path / "batch", {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf(2)}
    )

    outputs = await offload.maybe_offload(
        "compress", batch, {"level": "recommended"}
    )

    assert outputs is not None
    assert [output.download_name for output in outputs] == [
        "a-compressed.pdf",
        "b-compressed.pdf",
    ]
    for output in outputs:
        # Written into the batch's own workspace, the same directory the local
        # path uses — so the response and its cleanup behave identically.
        assert output.path.is_file()
        assert output.path.parent == batch.directory / "out"
        assert output.path.read_bytes().startswith(b"%PDF-")
    # Two files and the default ceiling of two sandboxes: one shard each.
    assert pool.disposed == pool.provisioned == ["fake-0", "fake-1"]


@requires_ghostscript
async def test_the_sandbox_is_told_its_own_size(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """`os.cpu_count()` inside a sandbox is a lie, so the size is passed in."""
    monkeypatch.setattr(config, "DAYTONA_SANDBOX_CPU", 4)
    pool = use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(tmp_path / "batch", {"a.pdf": build_text_pdf()})

    await offload.maybe_offload("compress", batch, {"level": "recommended"})

    [(_, command, env)] = [
        entry for entry in pool.commands if "remote_job" in entry[1]
    ]
    assert env["MAX_CONCURRENT_JOBS"] == "4"
    assert command.endswith(f"{offload.WORK}/spec.json")


@requires_ghostscript
async def test_only_the_shim_is_streamed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The unpack passes no on_line, so a pool can skip the streaming setup.

    Measured at 2.2 s of the 15 s a real offloaded 50-page scan took, for a
    command that finishes in milliseconds.
    """
    readers: list[tuple[str, bool]] = []

    class Watching(FakeSandboxPool):
        async def run(self, sandbox_id, command, *, cwd, env, on_line=None):
            readers.append((command.split()[0], on_line is not None))
            return await super().run(
                sandbox_id, command, cwd=cwd, env=env, on_line=on_line
            )

    use(monkeypatch, Watching(tmp_path / "sandboxes"))
    batch = make_batch(tmp_path / "batch", {"a.pdf": build_text_pdf()})

    await offload.maybe_offload("compress", batch, {"level": "recommended"})

    assert readers == [("mkdir", False), (offload.PYTHON, True)]


@requires_qpdf
async def test_an_unprocessable_document_never_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    encrypted_pdf: bytes,
) -> None:
    """A 422 from the sandbox is the answer, not a reason to try again locally.

    Retrying an encrypted file on the VPS would fail identically — the same
    ``ensure_readable`` runs in both places — having also burned the round
    trip. The sandbox is still disposed of.
    """
    pool = use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(tmp_path / "batch", {"locked.pdf": encrypted_pdf})

    with pytest.raises(HTTPException) as raised:
        await offload.maybe_offload("compress", batch, {"level": "recommended"})

    assert raised.value.status_code == 422
    assert raised.value.detail == errors.PASSWORD_REQUIRED
    assert pool.disposed == ["fake-0"]


class RecordingPublisher(progress.NullPublisher):
    """Every percentage a service publishes, in order. No __slots__ on purpose."""

    def __init__(self) -> None:
        super().__init__()
        self.seen: list[float | None] = []

    def _emit(self, phase: str) -> None:
        self.seen.append(self._percent)

    def finish(self, reason: str = progress.DONE) -> None:
        self.seen.append(100.0 if reason == progress.DONE else self._percent)


@requires_ghostscript
async def test_relayed_progress_is_the_shim_s_own_numbers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The fold happens once, in the sandbox, and is passed through verbatim."""
    recorder = RecordingPublisher()
    progress.bind(recorder, None)
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(
        tmp_path / "batch", {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()}
    )

    await offload.maybe_offload("compress", batch, {"level": "recommended"})

    moved = [percent for percent in recorder.seen if percent is not None]
    assert moved, "no progress was relayed at all"
    assert moved == sorted(moved), "the bar went backwards"
    assert moved[-1] == 100.0


# --- placement -----------------------------------------------------------


@requires_ghostscript
async def test_placement_is_marked_sandbox_once_a_shard_is_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(tmp_path / "batch", {"a.pdf": build_text_pdf()})

    assert placement.current() == placement.SERVER
    outputs = await offload.maybe_offload("compress", batch, {"level": "recommended"})
    assert outputs is not None
    assert placement.current() == placement.SANDBOX


async def test_placement_reverts_to_server_after_a_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The test that would catch a badge that lies about a silent fallback."""
    use(monkeypatch, ScriptedPool(provision_error=RuntimeError("no capacity")))
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert await offload.maybe_offload("compress", batch, {}) is None
    assert placement.current() == placement.SERVER


# --- fallback ----------------------------------------------------------------


async def test_a_provision_failure_falls_back_silently(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    pool = use(
        monkeypatch, ScriptedPool(provision_error=RuntimeError("no capacity"))
    )
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert await offload.maybe_offload("compress", batch, {}) is None
    assert pool.disposed == [], "there was nothing to dispose of"


@requires_ocrmypdf
@requires_tesseract
async def test_the_caller_s_own_loop_still_produces_the_right_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """Fallback is not "returns None" — it is "the user still gets their file".

    Driven through ``ocr.ocr`` rather than ``maybe_offload`` alone, because the
    thing under test is the three-line head falling through to the loop below
    it.
    """
    pool = use(monkeypatch, ScriptedPool(provision_error=RuntimeError("no capacity")))
    batch = make_batch(tmp_path, {"scan.pdf": build_scanned_pdf()})

    outputs = await ocr_service.ocr(batch, ["eng"])

    assert pool.provisioned == [] and pool.disposed == []
    assert [output.download_name for output in outputs] == ["scan-ocr.pdf"]
    assert outputs[0].path.is_file()


async def test_a_shim_that_could_not_run_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """Exit 1 with nothing on stdout is "the batch did not run"."""
    pool = use(
        monkeypatch,
        ScriptedPool(
            lines=[("stderr", json.dumps({"status": "failed", "error": "boom"}))],
            exit_code=1,
        ),
    )
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert await offload.maybe_offload("compress", batch, {}) is None
    assert pool.disposed == ["scripted-0"]


async def test_a_batch_lost_after_partial_results_is_a_hard_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """Once a file's result has appeared, silent local retry would duplicate work."""
    use(
        monkeypatch,
        ScriptedPool(
            lines=[("stdout", result_line("a.pdf", "a-compressed.pdf", 10))],
            run_error=RuntimeError("connection reset"),
        ),
    )
    batch = make_batch(
        tmp_path, {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()}
    )

    with pytest.raises(HTTPException) as raised:
        await offload.maybe_offload("compress", batch, {})
    assert raised.value.status_code == 502
    assert raised.value.detail == offload.INTERRUPTED


async def test_fallback_can_be_turned_off_for_a_rollout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """With it off, a Daytona failure is visible instead of hidden by a retry."""
    monkeypatch.setattr(config, "DAYTONA_FALLBACK_LOCAL", False)
    use(monkeypatch, ScriptedPool(provision_error=RuntimeError("no capacity")))
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    with pytest.raises(HTTPException) as raised:
        await offload.maybe_offload("compress", batch, {})
    assert raised.value.status_code == 502
    assert raised.value.detail == offload.FAILED


# --- cancellation ------------------------------------------------------------


async def test_a_client_that_hangs_up_stops_the_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """499, the same status the local path raises, and the sandbox goes."""
    monkeypatch.setattr(offload, "WATCHDOG_SECONDS", 0.01)
    gone = False

    async def client_gone() -> bool:
        return gone

    progress.bind(progress.NULL, client_gone)
    pool = use(monkeypatch, ScriptedPool(lines=[("stderr", frame(1, 2, 10.0))], pause=0.02))
    batch = make_batch(
        tmp_path, {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()}
    )

    async def hang_up() -> None:
        nonlocal gone
        await asyncio.sleep(0.05)
        gone = True

    hanging_up = asyncio.create_task(hang_up())
    with pytest.raises(HTTPException) as raised:
        await offload.maybe_offload("compress", batch, {})
    await hanging_up

    assert raised.value.status_code == 499
    assert raised.value.detail == progress.CANCELLED
    assert sorted(pool.disposed) == ["scripted-0", "scripted-1"], (
        "every shard's sandbox must go, exactly once each"
    )


async def test_a_batch_that_outruns_its_budget_times_out_like_a_local_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    monkeypatch.setattr(config, "TIMEOUTS", dict(config.TIMEOUTS, compress=0))
    monkeypatch.setattr(config, "DAYTONA_OVERHEAD_SECONDS", 0)
    monkeypatch.setattr(offload, "WATCHDOG_SECONDS", 30)
    pool = use(monkeypatch, ScriptedPool(pause=0.05))
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    with pytest.raises(HTTPException) as raised:
        await offload.maybe_offload("compress", batch, {})
    assert raised.value.status_code == 504
    assert raised.value.detail == "processing_timed_out"
    assert pool.disposed == ["scripted-0"]


# --- staging -----------------------------------------------------------------


async def test_the_spec_and_the_inputs_land_where_the_shim_looks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    pool = use(monkeypatch, ScriptedPool(exit_code=1))
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    await offload.maybe_offload("compress", batch, {"level": "extreme"})

    assert pool.put_paths[0] == f"{offload.WORK}/app.tgz"
    assert f"{offload.WORK}/spec.json" in pool.put_paths
    assert any(path.startswith(f"{offload.WORK}/in/") for path in pool.put_paths)


def test_the_app_tarball_carries_the_shim_and_no_caches() -> None:
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(offload._app_tarball())) as archive:
        names = archive.getnames()

    assert "app/tools/remote_job.py" in names
    assert "app/services/ocr.py" in names
    assert not [name for name in names if "__pycache__" in name or name.endswith(".pyc")]


def test_the_app_tarball_records_nothing_about_this_machine() -> None:
    """An archive carrying the builder's uid makes the sandbox's tar exit 2.

    Found on the VPS, not here: GNU tar extracting as root chowns each file to
    the uid the archive names, and a uid that means nothing in the sandbox
    (197609, a Windows-mapped owner arriving through a bind-mounted checkout)
    fails the extraction *after* writing every file. `_stage` reads the exit
    code as "could not stage the job", and the whole feature silently stops
    offloading anything.
    """
    import io
    import tarfile

    with tarfile.open(fileobj=io.BytesIO(offload._app_tarball())) as archive:
        members = archive.getmembers()

    assert members
    assert {(member.uid, member.gid) for member in members} == {(0, 0)}
    assert {(member.uname, member.gname) for member in members} == {("root", "root")}


# --- line splitting ----------------------------------------------------------


def test_a_frame_split_across_two_chunks_still_arrives() -> None:
    """Daytona's log socket delivers chunks, not lines."""
    seen: list[tuple[str, str]] = []
    lines = offload._Lines("stderr", lambda stream, line: seen.append((stream, line)))

    lines.feed('{"a":')
    assert seen == []
    lines.feed('1}\n{"b":2}')
    lines.close()

    assert seen == [("stderr", '{"a":1}'), ("stderr", '{"b":2}')]


def test_a_line_that_never_ends_is_handed_over_anyway() -> None:
    seen: list[str] = []
    lines = offload._Lines("stdout", lambda stream, line: seen.append(line))

    lines.feed("x" * (offload.MAX_PENDING_LINE + 5))

    assert len(seen) == 1
    assert len(seen[0]) == offload.MAX_PENDING_LINE


# --- Publisher.batch ---------------------------------------------------------


def published(channel: progress.Channel) -> float | None:
    return channel.snapshot.percent


def test_batch_reproduces_a_percentage_it_is_handed() -> None:
    """The identity the relay relies on: done = percent/100*total, total=total."""
    channel = progress.Channel("j" * 32, claimed=True)
    publisher = progress.Publisher(channel)

    for percent in (0.0, 12.5, 48.0, 99.9, 100.0):
        publisher.batch(
            done=percent / 100 * 5, total=5, index=2, name="b.pdf", step="Reading"
        )
        assert published(channel) == percent


def test_batch_is_monotonic_like_every_other_mover() -> None:
    channel = progress.Channel("k" * 32, claimed=True)
    publisher = progress.Publisher(channel)

    publisher.batch(done=3.0, total=5, index=3, name="c.pdf", step="Reading")
    assert published(channel) == 60.0
    publisher.batch(done=1.0, total=5, index=1, name="a.pdf", step="Reading")
    assert published(channel) == 60.0, "a bar that goes backwards reads as broken"


def test_batch_drives_the_detail_line_independently() -> None:
    """index/name/step need not be in lockstep with done/total — Phase 4 needs that."""
    channel = progress.Channel("l" * 32, claimed=True)
    publisher = progress.Publisher(channel)

    publisher.batch(done=1.5, total=4, index=7, name="g.pdf", step="Rebuilding")

    assert channel.snapshot.file_index == 7
    assert channel.snapshot.file_total == 4
    assert channel.snapshot.file_name == "g.pdf"
    assert channel.snapshot.step == "Rebuilding"
    assert channel.snapshot.percent == 37.5


def test_the_null_publisher_inherits_batch_for_free() -> None:
    progress.NULL.batch(done=1, total=2, index=1, name="a.pdf", step="Reading")


# --- the OCR head ------------------------------------------------------------


@requires_ocrmypdf
@requires_tesseract
async def test_ocr_runs_its_batch_in_the_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The three-line head, end to end, against the real shim."""
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(tmp_path / "batch", {"scan.pdf": build_scanned_pdf()})

    outputs = await ocr_service.ocr(batch, ["eng"])

    assert [output.download_name for output in outputs] == ["scan-ocr.pdf"]
    assert outputs[0].path.read_bytes().startswith(b"%PDF-")


async def test_ocr_with_offloading_off_runs_locally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The head must be inert by default — no pool built, no behaviour change."""

    def explode() -> Any:
        raise AssertionError("the pool must not be built when offloading is off")

    monkeypatch.setattr(offload, "pool_factory", explode)
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert await offload.maybe_offload("ocr", batch, {"languages": ["eng"]}) is None


# --- the other three heads ---------------------------------------------------
#
# Phase 3 wired `word`, `markdown` and `compress` the same way Phase 2 wired
# `ocr`. Dispatch inside the sandbox is already proved by
# `test_remote_job.py::test_word_dispatches_to_to_word_one` and its Markdown
# twin; what these tests are about is the head in each driver and the plumbing
# on this side of the wire — that the right operation name and options go out,
# that the files come back into the batch's own workspace, and that the result
# a caller gets is the same shape it would have got locally.


class _HeadReached(Exception):
    """Raised from a stubbed `maybe_offload` so the local path never runs."""


@pytest.mark.parametrize(
    ("operation", "drive", "expected"),
    [
        pytest.param(
            "compress",
            lambda batch: compress_service.compress(batch, "extreme"),
            {"level": "extreme"},
            id="compress",
        ),
        pytest.param(
            "ocr",
            lambda batch: ocr_service.ocr(batch, ["deu"]),
            {"languages": ["deu"]},
            id="ocr",
        ),
        pytest.param(
            "word",
            lambda batch: word_service.to_word(batch, "off", ["fra"]),
            {"ocr_mode": "off", "languages": ["fra"]},
            id="word",
        ),
        pytest.param(
            "markdown",
            lambda batch: markdown_service.to_markdown(batch, "auto", ["urd"]),
            {"ocr_mode": "auto", "languages": ["urd"]},
            id="markdown",
        ),
    ],
)
async def test_every_head_asks_for_its_own_operation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    drive: Callable[[UploadBatch], Any],
    expected: dict[str, Any],
) -> None:
    """Each driver names itself, and hands over the options the shim needs.

    Needs no tool at all: the stub raises rather than returning ``None``, so
    the local path below the head never starts. A head that named a sibling
    operation — the copy-paste this file exists to catch — would stay
    invisible in every other test here, because the shim would dispatch
    happily and produce a plausible file of the wrong kind.
    """
    seen: list[tuple[str, dict[str, Any]]] = []

    async def record(
        asked: str, _batch: UploadBatch, options: dict[str, Any]
    ) -> None:
        seen.append((asked, dict(options)))
        raise _HeadReached

    monkeypatch.setattr(offload, "maybe_offload", record)
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    with pytest.raises(_HeadReached):
        await drive(batch)

    assert seen == [(operation, expected)]


@requires_pdf2docx
async def test_word_comes_back_from_the_sandbox_as_the_local_path_would(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """Same names, same media type, same visible text — run both ways."""
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    sources = {"report.pdf": build_text_pdf(1), "notes.pdf": build_text_pdf(2)}

    remote = await word_service.to_word(
        make_batch(tmp_path / "remote", sources), "off", ["eng"]
    )
    monkeypatch.setattr(config, "DAYTONA_ENABLED", False)
    local = await word_service.to_word(
        make_batch(tmp_path / "local", sources), "off", ["eng"]
    )

    assert [output.download_name for output in remote] == [
        "report.docx",
        "notes.docx",
    ]
    assert [output.download_name for output in remote] == [
        output.download_name for output in local
    ]
    assert [output.media_type for output in remote] == [
        output.media_type for output in local
    ]
    for output in remote:
        # The batch's own workspace, so the response and its cleanup behave
        # identically to a local run's.
        assert output.path.parent == tmp_path / "remote" / "out"
    assert [docx_text(output.path.read_bytes()) for output in remote] == [
        docx_text(output.path.read_bytes()) for output in local
    ]


@requires_pdf2docx
@requires_ocrmypdf
@requires_tesseract
@pytest.mark.skipif(
    not has_scalable_font(), reason="no scalable font, OCR input would be unreadable"
)
async def test_word_ocrs_a_scan_inside_the_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """`ocr_mode="auto"` is the mode that makes Word worth offloading at all.

    It routes through the same ``ocr_to_path`` OCR itself uses, which is where
    the measured 2.62x lives; the "off" test above is the cheap path.
    """
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(tmp_path / "batch", {"scan.pdf": build_scanned_pdf()})

    outputs = await word_service.to_word(batch, "auto", ["eng"])

    assert [output.download_name for output in outputs] == ["scan.docx"]
    assert "SCANNED" in docx_text(outputs[0].path.read_bytes()).upper()


@requires_anydoc
async def test_markdown_comes_back_from_the_sandbox_as_the_local_path_would(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    sources = {"notes.pdf": build_text_pdf(1), "memo.pdf": build_text_pdf(2)}

    remote = await markdown_service.to_markdown(
        make_batch(tmp_path / "remote", sources), "off", ["eng"]
    )
    monkeypatch.setattr(config, "DAYTONA_ENABLED", False)
    local = await markdown_service.to_markdown(
        make_batch(tmp_path / "local", sources), "off", ["eng"]
    )

    assert [output.download_name for output in remote] == ["notes.md", "memo.md"]
    assert [output.download_name for output in remote] == [
        output.download_name for output in local
    ]
    for output in remote:
        assert output.path.parent == tmp_path / "remote" / "out"
    assert [output.path.read_text(encoding="utf-8") for output in remote] == [
        output.path.read_text(encoding="utf-8") for output in local
    ]


@requires_anydoc
@requires_ocrmypdf
@requires_tesseract
@pytest.mark.skipif(
    not has_scalable_font(), reason="no scalable font, OCR input would be unreadable"
)
async def test_markdown_ocrs_a_scan_inside_the_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """anydoc's two-pass NeedsOcr path, run entirely in the sandbox."""
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(tmp_path / "batch", {"scan.pdf": build_scanned_pdf()})

    outputs = await markdown_service.to_markdown(batch, "auto", ["eng"])

    assert [output.download_name for output in outputs] == ["scan.md"]
    assert "SCANNED" in outputs[0].path.read_text(encoding="utf-8").upper()


@requires_ghostscript
async def test_compress_rebuilds_its_size_report_from_what_arrived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The one head that does more than return the list.

    ``maybe_offload`` hands back ``list[OutputFile]`` like it does everywhere
    else, so the numbers Compress's done screen shows are re-derived in the
    head — the "before" from ``upload.size``, known before anything ran, the
    "after" from the bytes that actually landed on disk.
    """
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    batch = make_batch(
        tmp_path / "batch", {"a.pdf": build_text_pdf(4), "b.pdf": build_text_pdf(1)}
    )

    result = await compress_service.compress(batch, "recommended")

    assert [stat.name for stat in result.files] == ["a.pdf", "b.pdf"]
    assert [stat.original_size for stat in result.files] == [
        upload.size for upload in batch.files
    ]
    # Different page counts, so a report that paired the wrong upload with the
    # wrong output — or repeated one file's numbers — shows up here.
    assert result.files[0].original_size != result.files[1].original_size
    assert [stat.result_size for stat in result.files] == [
        output.path.stat().st_size for output in result.outputs
    ]
    assert all(stat.result_size > 0 for stat in result.files)
    assert result.original_size == sum(upload.size for upload in batch.files)
    assert result.result_size == sum(stat.result_size for stat in result.files)


@requires_ghostscript
async def test_compress_reports_the_same_numbers_on_both_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The done screen's per-file breakdown must not depend on where it ran."""
    use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))
    sources = {"a.pdf": build_text_pdf(4), "b.pdf": build_text_pdf(1)}

    remote = await compress_service.compress(
        make_batch(tmp_path / "remote", sources), "recommended"
    )
    monkeypatch.setattr(config, "DAYTONA_ENABLED", False)
    local = await compress_service.compress(
        make_batch(tmp_path / "local", sources), "recommended"
    )

    assert [output.download_name for output in remote.outputs] == [
        output.download_name for output in local.outputs
    ]
    assert remote.original_size == local.original_size
    assert [(stat.name, stat.original_size) for stat in remote.files] == [
        (stat.name, stat.original_size) for stat in local.files
    ]
    assert [stat.result_size for stat in remote.files] == [
        stat.result_size for stat in local.files
    ]


@requires_ghostscript
async def test_compress_falls_back_to_its_own_loop_with_the_report_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """Fallback has to skip the whole head, walrus and re-derivation alike."""
    pool = use(monkeypatch, ScriptedPool(provision_error=RuntimeError("no capacity")))
    batch = make_batch(
        tmp_path, {"a.pdf": build_text_pdf(4), "b.pdf": build_text_pdf(1)}
    )

    result = await compress_service.compress(batch, "recommended")

    assert pool.provisioned == [] and pool.disposed == []
    assert [output.download_name for output in result.outputs] == [
        "a-compressed.pdf",
        "b-compressed.pdf",
    ]
    assert [stat.name for stat in result.files] == ["a.pdf", "b.pdf"]
    assert result.result_size == sum(stat.result_size for stat in result.files)


@requires_qpdf
@pytest.mark.parametrize(
    ("operation", "drive"),
    [
        pytest.param(
            "compress",
            lambda batch: compress_service.compress(batch, "recommended"),
            id="compress",
        ),
        pytest.param(
            "word",
            lambda batch: word_service.to_word(batch, "off", ["eng"]),
            id="word",
        ),
        pytest.param(
            "markdown",
            lambda batch: markdown_service.to_markdown(batch, "off", ["eng"]),
            id="markdown",
        ),
    ],
)
async def test_a_locked_document_is_the_same_422_on_either_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    encrypted_pdf: bytes,
    operation: str,
    drive: Callable[[UploadBatch], Any],
) -> None:
    """Error parity, driven through the real drivers rather than `maybe_offload`.

    ``ensure_readable`` runs in both places, so the offloaded path has to
    surface the sandbox's 422 verbatim rather than burn a round trip and then
    fail identically on the VPS.
    """
    pool = use(monkeypatch, FakeSandboxPool(tmp_path / "sandboxes"))

    with pytest.raises(HTTPException) as offloaded:
        await drive(make_batch(tmp_path / "remote", {"locked.pdf": encrypted_pdf}))

    monkeypatch.setattr(config, "DAYTONA_ENABLED", False)
    with pytest.raises(HTTPException) as locally:
        await drive(make_batch(tmp_path / "local", {"locked.pdf": encrypted_pdf}))

    assert offloaded.value.status_code == locally.value.status_code == 422
    assert offloaded.value.detail == locally.value.detail == errors.PASSWORD_REQUIRED
    assert pool.disposed == ["fake-0"], "the sandbox is still cleaned up"


# --- sharding ----------------------------------------------------------------
#
# Phase 4 splits a batch across up to `DAYTONA_MAX_SANDBOXES` sandboxes, run at
# the same time, and folds their independent progress streams back into the one
# bar the frontend already knows how to draw. Nothing about the *outside* of
# `maybe_offload` changed, which is why every test above still holds: the same
# `list[OutputFile]` in the same order, the same 422s, the same silent fallback.


def test_a_batch_splits_into_contiguous_roughly_even_shards() -> None:
    """Contiguous, because file order is visible to the user in the fold."""
    assert offload._split(5, 2) == [range(0, 3), range(3, 5)]
    assert offload._split(10, 2) == [range(0, 5), range(5, 10)]
    assert offload._split(7, 3) == [range(0, 3), range(3, 5), range(5, 7)]
    assert offload._split(1, 1) == [range(0, 1)]
    # Never an empty shard: a sandbox provisioned to do nothing is pure cost.
    assert all(len(span) > 0 for span in offload._split(3, 3))


async def test_a_batch_smaller_than_the_ceiling_never_makes_an_empty_shard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """Two files and four sandboxes allowed is two shards, not four."""
    monkeypatch.setattr(config, "DAYTONA_MAX_SANDBOXES", 4)
    pool = use(monkeypatch, ScriptedPool(exit_code=1))
    batch = make_batch(
        tmp_path, {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()}
    )

    assert await offload.maybe_offload("compress", batch, {}) is None
    assert pool.provisioned == ["scripted-0", "scripted-1"]
    assert [len(spec["files"]) for spec in pool.specs] == [1, 1]


async def test_one_file_still_goes_to_one_sandbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The Phase 2 shape is just the one-shard case of this one."""
    pool = use(monkeypatch, ScriptedPool(exit_code=1))
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert await offload.maybe_offload("compress", batch, {}) is None
    assert pool.provisioned == ["scripted-0"]


class ReversedFinishPool(FakeSandboxPool):
    """Two real shards, with the one holding the first files finishing *last*.

    An `asyncio.Event` rather than a sleep, so the order is a fact rather than
    a race the test usually wins. This is the pool that would catch
    recombination done by completion order: its shards finish backwards.
    """

    def __init__(self, root: Path) -> None:
        super().__init__(root)
        self.finished: list[str] = []
        #: The sandbox holding file 0, which is made to finish last.
        self.slow = ""
        self._sibling_done = asyncio.Event()

    async def run(self, sandbox_id, command, *, cwd, env, on_line=None):
        if "remote_job" not in command:
            return await super().run(
                sandbox_id, command, cwd=cwd, env=env, on_line=on_line
            )
        first = str(self.specs[sandbox_id]["files"][0]["input"]).startswith("in/00-")
        if first:
            self.slow = sandbox_id
            await asyncio.wait_for(self._sibling_done.wait(), 120)
        code = await super().run(
            sandbox_id, command, cwd=cwd, env=env, on_line=on_line
        )
        self.finished.append(sandbox_id)
        if not first:
            self._sibling_done.set()
        return code


@requires_ghostscript
async def test_five_files_run_as_two_shards_and_come_back_in_file_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The payoff test: real concurrent subprocesses, recombined by position.

    Both shards run the real shim in their own tmpdir, and the one holding the
    first three files is held back until the other has finished — so if the
    outputs were concatenated in completion order the names below would come
    back rotated.
    """
    monkeypatch.setattr(config, "DAYTONA_MAX_SANDBOXES", 2)
    pool = use(monkeypatch, ReversedFinishPool(tmp_path / "sandboxes"))
    names = ["a.pdf", "b.pdf", "c.pdf", "d.pdf", "e.pdf"]
    batch = make_batch(
        tmp_path / "batch",
        {name: build_text_pdf(index + 1) for index, name in enumerate(names)},
    )

    outputs = await offload.maybe_offload("compress", batch, {"level": "recommended"})

    assert outputs is not None
    assert [output.download_name for output in outputs] == [
        name.replace(".pdf", "-compressed.pdf") for name in names
    ]
    for output in outputs:
        assert output.path.is_file()
        assert output.path.parent == batch.directory / "out"

    # Two shards, split 3/2, each holding a contiguous run of the batch.
    assert len(pool.provisioned) == 2
    assert sorted(pool.disposed) == sorted(pool.provisioned)
    positions = sorted(
        [int(str(entry["input"])[len("in/") :][:2]) for entry in spec["files"]]
        for spec in pool.specs.values()
    )
    assert positions == [[0, 1, 2], [3, 4]]
    # …and the shard holding the first files really did finish last.
    assert pool.finished[-1] == pool.slow
    assert len(pool.finished) == 2


class OneShardBreaks(ScriptedPool):
    """The first sandbox runs its file; the second loses its connection mid-exec."""

    async def run(self, sandbox_id, command, *, cwd, env, on_line=None):
        if "remote_job" not in command:
            return 0
        if sandbox_id == "scripted-1":
            on_line("stderr", frame(1, 1, 10.0))
            raise RuntimeError("connection reset")
        on_line("stdout", result_line("a.pdf", "a-compressed.pdf", len(OUTPUT_BYTES)))
        return 0


OUTPUT_BYTES = b"%PDF-1.4 compressed"


async def test_a_shard_lost_after_a_sibling_produced_results_is_a_hard_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """The Phase 2 rule, now batch-wide: *any* file done anywhere ends fallback.

    Re-running the whole batch locally would duplicate the shard that worked —
    work that really happened, was already billed, and whose progress the
    client has already seen.
    """
    pool = use(
        monkeypatch,
        OneShardBreaks(files={f"{offload.WORK}/out/a-compressed.pdf": OUTPUT_BYTES}),
    )
    batch = make_batch(
        tmp_path, {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()}
    )

    with pytest.raises(HTTPException) as raised:
        await offload.maybe_offload("compress", batch, {})

    assert raised.value.status_code == 502
    assert raised.value.detail == offload.INTERRUPTED
    assert sorted(pool.disposed) == ["scripted-0", "scripted-1"]
    assert len(pool.disposed) == len(set(pool.disposed)), "each sandbox goes once"


async def test_every_shard_is_disposed_even_when_another_one_dies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    """One shard raising must not cancel a sibling out of its own teardown."""
    pool = use(monkeypatch, ScriptedPool(run_error=RuntimeError("connection reset")))
    batch = make_batch(
        tmp_path, {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()}
    )

    # Nothing was produced by either shard, so this is still a silent fallback.
    assert await offload.maybe_offload("compress", batch, {}) is None
    assert sorted(pool.disposed) == ["scripted-0", "scripted-1"]


# --- FanIn -------------------------------------------------------------------
#
# No subprocess and no pool: the fold is arithmetic, and the thing worth
# proving about it is a property — that it never goes backwards however the
# shards interleave, and that it arrives at exactly `total`.


def fold(
    fan: offload.FanIn,
    shard: int,
    file: int,
    total: int,
    percent: float,
    name: str = "",
) -> float:
    """Feed one shard's frame, in the shape the relay parses off stderr."""
    fan.update(shard, json.loads(frame(file, total, percent, name=name)))
    return fan.done


def test_fan_in_is_monotonic_however_the_shards_interleave() -> None:
    """A shard's 0-100 is its own; only whole files are comparable across them."""
    fan = offload.FanIn(5)
    #: (shard, file, that shard's file count, that shard's own percentage)
    script = [
        (0, 1, 3, 0.0),
        (1, 1, 2, 0.0),
        (1, 1, 2, 45.0),  # shard 1 is 90% through its first file …
        (0, 1, 3, 10.0),  # … while shard 0 is 30% through its own
        (1, 2, 2, 50.0),  # shard 1 starts its second file: one whole file done
        (0, 2, 3, 33.3),
        (1, 2, 2, 75.0),
        (0, 3, 3, 66.7),
        (1, 2, 2, 100.0),
        (0, 3, 3, 100.0),
    ]
    seen = [fold(fan, *entry) for entry in script]

    assert seen == sorted(seen), "the fold went backwards"
    assert seen[0] == 0.0
    # Shard 1's second frame is 45% of a two-file shard: nine tenths of one
    # file, whatever the rest of the batch is doing.
    assert seen[2] == pytest.approx(0.9)
    assert fan.done == pytest.approx(5.0), "both shards finished; so has the batch"


def test_fan_in_publishes_a_bar_that_ends_at_a_hundred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(offload, "PUBLISH_INTERVAL_SECONDS", 0.0)
    channel = progress.Channel("n" * 32, claimed=True)
    publisher = progress.Publisher(channel)
    fan = offload.FanIn(4)

    seen: list[float | None] = []
    for shard, file, total, percent in [
        (0, 1, 2, 0.0),
        (1, 1, 2, 0.0),
        (0, 1, 2, 25.0),
        (1, 2, 2, 50.0),
        (0, 2, 2, 100.0),
        (1, 2, 2, 100.0),
    ]:
        fold(fan, shard, file, total, percent)
        fan.publish(publisher)
        seen.append(channel.snapshot.percent)

    assert seen == sorted(seen, key=lambda value: value or 0.0)
    assert seen[0] == 0.0
    assert seen[-1] == 100.0


def test_fan_in_throttles_the_frames_it_relays() -> None:
    """A sharded batch produces several shims' frames; the bar is not a log."""
    channel = progress.Channel("o" * 32, claimed=True)
    publisher = progress.Publisher(channel)
    fan = offload.FanIn(10)

    fold(fan, 0, 1, 5, 0.0)
    fan.publish(publisher)  # the first one always goes
    first = channel.snapshot.percent
    for tick in range(1, 10):  # a hundredth of a file at a time
        fold(fan, 0, 1, 5, tick / 100)
        fan.publish(publisher)

    assert channel.snapshot.percent == first, "a sub-1% move need not be published"


def test_fan_in_follows_one_shard_for_the_detail_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise the file name flickers between unrelated files as shards race."""
    monkeypatch.setattr(offload, "PUBLISH_INTERVAL_SECONDS", 0.0)
    channel = progress.Channel("p" * 32, claimed=True)
    publisher = progress.Publisher(channel)
    fan = offload.FanIn(4)

    # Shard 1 gets there first, and a real file name beats a blank line.
    fold(fan, 1, 1, 2, 0.0, name="y.pdf")
    fan.publish(publisher)
    assert channel.snapshot.file_name == "y.pdf"

    # The moment shard 0 speaks it takes the line over, and keeps it.
    fold(fan, 0, 1, 2, 0.0, name="a.pdf")
    fold(fan, 1, 2, 2, 50.0, name="z.pdf")  # shard 1 has finished its first file
    fan.publish(publisher)

    assert channel.snapshot.file_name == "a.pdf", "shard 0's file, not shard 1's"
    assert channel.snapshot.file_total == 4, "the batch's count, not a shard's"
    # One file of the batch's four is done, and index follows that fold rather
    # than either shard's own cursor.
    assert channel.snapshot.percent == 25.0
    assert channel.snapshot.file_index == 2


def test_fan_in_drops_frames_it_cannot_read() -> None:
    """A progress line must never be able to fail a batch."""
    fan = offload.FanIn(2)

    fan.update(0, {})
    fan.update(0, {"file": 1, "total": 0, "percent": 50.0})
    fan.update(0, {"file": 0, "total": 2, "percent": 50.0})
    fan.update(0, {"file": "one", "total": 2, "percent": 50.0})
    fan.update(0, {"file": 1, "total": 2, "percent": None})

    assert fan.done == 0.0


def test_a_single_shard_relays_the_shim_s_own_numbers_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One shard is the identity case, and Phase 2's behaviour has to survive it."""
    monkeypatch.setattr(offload, "PUBLISH_INTERVAL_SECONDS", 0.0)
    channel = progress.Channel("q" * 32, claimed=True)
    publisher = progress.Publisher(channel)
    fan = offload.FanIn(5)

    for percent in (0.0, 12.0, 48.0, 99.9, 100.0):
        # A single shard's fold *is* the batch's fold, file count and all.
        file = min(int(percent / 100 * 5) + 1, 5)
        fold(fan, 0, file, 5, percent)
        fan.publish(publisher)
        assert channel.snapshot.percent == pytest.approx(percent, abs=0.05)


# --- the startup sweep, and waking a snapshot that went to sleep -------------
#
# Both of these are the one part of the module that is genuinely Daytona-shaped
# rather than pool-shaped: ``sweep_orphans`` reaches for the client directly,
# and the reactivation retry lives inside ``_DaytonaPool`` itself. So the fake
# here stands in for the *client*, not for :class:`SandboxPool` — one level
# lower than every other fake in this file.

requires_daytona = pytest.mark.skipif(
    importlib.util.find_spec("daytona") is None,
    reason="the daytona SDK is only installed in the backend image",
)


class FakeSandbox:
    """One entry in a fake account listing."""

    def __init__(self, sandbox_id: str, delete_error: Exception | None = None) -> None:
        self.id = sandbox_id
        self.delete_error = delete_error
        self.deleted = False

    async def delete(self) -> None:
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted = True


class FakeClient:
    """As much of ``AsyncDaytona`` as the sweep and the retry actually touch."""

    def __init__(
        self,
        sandboxes: list[FakeSandbox] | None = None,
        list_error: Exception | None = None,
        create_errors: list[Exception] | None = None,
    ) -> None:
        self.sandboxes = sandboxes or []
        self.list_error = list_error
        #: Popped one per ``create``; an empty list means "succeed".
        self.create_errors = create_errors or []
        self.queries: list[Any] = []
        self.creates = 0
        self.activated: list[str] = []
        self.snapshot = _FakeSnapshots(self)

    def list(self, query: Any = None) -> Any:
        """An async generator, which is what the real ``list`` hands back."""
        self.queries.append(query)

        async def iterate():
            if self.list_error is not None:
                raise self.list_error
            for sandbox in self.sandboxes:
                yield sandbox

        return iterate()

    async def create(self, params: Any, timeout: float | None = None) -> FakeSandbox:
        self.creates += 1
        if self.create_errors:
            raise self.create_errors.pop(0)
        return FakeSandbox(f"created-{self.creates}")


class _FakeSnapshots:
    def __init__(self, client: FakeClient) -> None:
        self._client = client

    async def activate(self, name: str) -> None:
        self._client.activated.append(name)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Callable[..., FakeClient]:
    """Install a fake Daytona client, and hand it back for assertions."""

    def install(**kwargs: Any) -> FakeClient:
        fake = FakeClient(**kwargs)
        monkeypatch.setattr(offload, "_daytona", lambda: fake)
        return fake

    return install


async def test_the_sweep_does_nothing_at_all_while_the_feature_is_off(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The default posture: no API key, no network, no call."""
    monkeypatch.setattr(config, "DAYTONA_ENABLED", False)
    fake = client(sandboxes=[FakeSandbox("orphan-1")])

    assert await offload.sweep_orphans() == 0
    assert fake.queries == []


@requires_daytona
async def test_the_sweep_deletes_what_a_dead_process_left_behind(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The case ``try/finally`` cannot cover: a redeploy that SIGKILLed uvicorn."""
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    orphans = [FakeSandbox("orphan-1"), FakeSandbox("orphan-2")]
    fake = client(sandboxes=orphans)

    assert await offload.sweep_orphans() == 2
    assert all(sandbox.deleted for sandbox in orphans)
    # Filtered on our own label, so a sandbox something else on the same
    # account owns is never listed, let alone deleted.
    assert fake.queries[0].labels == offload.LABELS


@requires_daytona
async def test_an_empty_account_is_the_ordinary_answer(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    client()

    assert await offload.sweep_orphans() == 0


@requires_daytona
async def test_a_sweep_that_cannot_list_never_blocks_startup(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A working app that skipped a cleanup beats an app that will not start."""
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    client(list_error=RuntimeError("404 /sandbox/paginated"))

    assert await offload.sweep_orphans() == 0


@requires_daytona
async def test_one_orphan_that_will_not_delete_does_not_cost_the_others(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    stuck = FakeSandbox("orphan-1", delete_error=RuntimeError("busy"))
    fine = FakeSandbox("orphan-2")
    client(sandboxes=[stuck, fine])

    assert await offload.sweep_orphans() == 1
    assert fine.deleted


@requires_daytona
async def test_a_sweep_that_hangs_gives_up_rather_than_hanging_startup(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    monkeypatch.setattr(offload, "SWEEP_TIMEOUT_SECONDS", 0.05)

    class Hangs(FakeSandbox):
        async def delete(self) -> None:
            await asyncio.sleep(30)

    client(sandboxes=[Hangs("orphan-1")])

    started = time.monotonic()
    assert await offload.sweep_orphans() == 0
    assert time.monotonic() - started < 5


@requires_daytona
async def test_a_sleeping_snapshot_is_woken_and_retried_exactly_once(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Daytona deactivates a snapshot after ~2 weeks unused; this is that."""
    monkeypatch.setattr(config, "DAYTONA_SNAPSHOT", "pdfkit-toolchain-abc123")
    fake = client(
        create_errors=[RuntimeError("Snapshot pdfkit-toolchain-abc123 is inactive")]
    )

    sandbox_id = await offload._DaytonaPool().provision()

    assert sandbox_id == "created-2"
    assert fake.creates == 2
    assert fake.activated == ["pdfkit-toolchain-abc123"]


@requires_daytona
async def test_a_snapshot_still_asleep_after_waking_is_not_retried_again(
    client: Callable[..., FakeClient], monkeypatch: pytest.MonkeyPatch
) -> None:
    """One retry, never a loop: the caller already has an answer for a failure."""
    monkeypatch.setattr(config, "DAYTONA_SNAPSHOT", "pdfkit-toolchain-abc123")
    asleep = "Snapshot pdfkit-toolchain-abc123 is inactive"
    fake = client(create_errors=[RuntimeError(asleep), RuntimeError(asleep)])

    with pytest.raises(RuntimeError):
        await offload._DaytonaPool().provision()

    assert fake.creates == 2
    assert fake.activated == ["pdfkit-toolchain-abc123"]


@requires_daytona
async def test_any_other_provision_failure_is_raised_without_a_retry(
    client: Callable[..., FakeClient],
) -> None:
    """A stale snapshot name must fall back locally, not cost two creates."""
    fake = client(create_errors=[RuntimeError("Snapshot not found")])

    with pytest.raises(RuntimeError):
        await offload._DaytonaPool().provision()

    assert fake.creates == 1
    assert fake.activated == []


@pytest.mark.parametrize(
    ("message", "inactive"),
    [
        ("Snapshot pdfkit-toolchain is inactive", True),
        ("snapshot pdfkit-toolchain-abc is not active", True),
        ("Snapshot not found", False),
        ("Sandbox is inactive", False),
        ("Cannot specify Sandbox resources when using a snapshot", False),
    ],
)
def test_only_a_sleeping_snapshot_looks_like_one(message: str, inactive: bool) -> None:
    """The retry costs an extra round trip, so the match has to be narrow."""
    assert offload._looks_inactive(RuntimeError(message)) is inactive


# --- the number /health reports ----------------------------------------------


async def test_open_sandboxes_counts_up_while_shards_run_and_back_down_after(
    tmp_path: Path, enabled: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``/health``'s ``sandboxes`` field, which is how a rollout is watched."""
    seen: list[int] = []

    class Counting(ScriptedPool):
        async def run(self, sandbox_id: str, command: str, **kwargs: Any) -> int:
            if "remote_job" in command:
                seen.append(offload.open_sandboxes())
            return await super().run(sandbox_id, command, **kwargs)

    monkeypatch.setattr(config, "DAYTONA_MAX_SANDBOXES", 2)
    pool = use(
        monkeypatch,
        Counting(
            lines=[("stdout", result_line("00-a.pdf", "out.pdf", 13))],
            files={f"{offload.WORK}/out/out.pdf": b"%PDF-1.7 done"},
        ),
    )
    batch = make_batch(tmp_path, {"a.pdf": b"%PDF-a", "b.pdf": b"%PDF-b"})

    assert offload.open_sandboxes() == 0
    await offload.maybe_offload("ocr", batch, {})

    assert len(pool.provisioned) == 2
    # Both shards were in flight at once, which is the whole point of the
    # number: it is sandboxes, not requests.
    assert max(seen) == 2, seen
    # Back to zero once the shards have handed their sandboxes back, whatever
    # the batch's own verdict was.
    assert offload.open_sandboxes() == 0


# --- sandbox telemetry --------------------------------------------------------


@pytest.fixture
def stats_ingest(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Captures every ``sandbox_stats.record`` call instead of posting anywhere."""
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr(sandbox_stats, "record", lambda **kwargs: calls.append(kwargs))
    return calls


async def test_sandbox_telemetry_is_built_with_the_right_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    stats_ingest: list[dict[str, Any]],
) -> None:
    """One record per shard, naming its own sandbox and a plausible clock."""
    monkeypatch.setattr(config, "DAYTONA_MAX_SANDBOXES", 2)
    use(
        monkeypatch,
        ScriptedPool(
            lines=[("stdout", result_line("00-a.pdf", "out.pdf", 13))],
            files={f"{offload.WORK}/out/out.pdf": b"%PDF-1.7 done"},
        ),
    )
    batch = make_batch(tmp_path, {"a.pdf": b"%PDF-aaaa", "b.pdf": b"%PDF-bbbb"})

    await offload.maybe_offload("ocr", batch, {})

    assert len(stats_ingest) == 2
    by_shard = {call["shard_index"]: call for call in stats_ingest}
    assert set(by_shard) == {0, 1}
    assert by_shard[0]["sandbox_id"] == "scripted-0"
    assert by_shard[1]["sandbox_id"] == "scripted-1"
    for call in stats_ingest:
        assert call["operation"] == "ocr"
        assert call["outcome"] == "ok"
        assert call["shard_total"] == 2
        assert call["file_count"] == 1
        assert call["alive_seconds"] >= 0
        assert call["bytes_up"] == len(b"%PDF-aaaa")
        assert call["bytes_down"] == 13


async def test_sandbox_telemetry_names_a_document_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    stats_ingest: list[dict[str, Any]],
) -> None:
    """A file the services genuinely cannot process is ``failed``, not ``abandoned``."""
    use(
        monkeypatch,
        ScriptedPool(
            lines=[
                (
                    "stdout",
                    json.dumps(
                        {"status": "error", "http_status": 422, "detail": "password_required"}
                    ),
                )
            ]
        ),
    )
    batch = make_batch(tmp_path, {"locked.pdf": build_text_pdf()})

    with pytest.raises(HTTPException):
        await offload.maybe_offload("compress", batch, {})

    [call] = stats_ingest
    assert call["outcome"] == "failed"


async def test_sandbox_telemetry_names_an_abandoned_shard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    stats_ingest: list[dict[str, Any]],
) -> None:
    """A shard the shim never finished is ``abandoned`` — an infrastructure reason."""
    use(
        monkeypatch,
        ScriptedPool(
            lines=[("stderr", json.dumps({"status": "failed", "error": "boom"}))],
            exit_code=1,
        ),
    )
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf()})

    assert await offload.maybe_offload("compress", batch, {}) is None

    [call] = stats_ingest
    assert call["outcome"] == "abandoned"


async def test_sandbox_telemetry_names_a_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    enabled: None,
    stats_ingest: list[dict[str, Any]],
) -> None:
    """A client that hangs up mid-batch is ``cancelled``, for every shard still open."""
    monkeypatch.setattr(offload, "WATCHDOG_SECONDS", 0.01)
    gone = False

    async def client_gone() -> bool:
        return gone

    progress.bind(progress.NULL, client_gone)
    use(monkeypatch, ScriptedPool(lines=[("stderr", frame(1, 2, 10.0))], pause=0.02))
    batch = make_batch(tmp_path, {"a.pdf": build_text_pdf(), "b.pdf": build_text_pdf()})

    async def hang_up() -> None:
        nonlocal gone
        await asyncio.sleep(0.05)
        gone = True

    hanging_up = asyncio.create_task(hang_up())
    with pytest.raises(HTTPException):
        await offload.maybe_offload("compress", batch, {})
    await hanging_up

    assert len(stats_ingest) == 2
    assert {call["outcome"] for call in stats_ingest} == {"cancelled"}


async def test_telemetry_is_off_without_both_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset either half of the pair and nothing is even attempted."""
    monkeypatch.setattr(config, "STATS_INGEST_URL", "")
    monkeypatch.setattr(config, "STATS_INGEST_SECRET", "")
    called = False

    async def fail_if_called(*_args: Any, **_kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("must not post while telemetry is disabled")

    monkeypatch.setattr(httpx.AsyncClient, "post", fail_if_called)

    sandbox_stats.record(
        sandbox_id="sbx-1",
        operation="ocr",
        outcome="ok",
        shard_index=0,
        shard_total=1,
        file_count=1,
        alive_seconds=1.0,
        bytes_up=1,
        bytes_down=1,
    )
    await asyncio.sleep(0)
    assert not called


async def test_a_posting_failure_cannot_fail_the_batch(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """``record`` fires a detached task; a broken endpoint is a log line, not a raise."""
    monkeypatch.setattr(config, "STATS_INGEST_URL", "http://example.invalid/stats/sandbox")
    monkeypatch.setattr(config, "STATS_INGEST_SECRET", "secret")

    async def broken_post(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", broken_post)

    with caplog.at_level(logging.WARNING):
        sandbox_stats.record(
            sandbox_id="sbx-1",
            operation="ocr",
            outcome="ok",
            shard_index=0,
            shard_total=1,
            file_count=1,
            alive_seconds=1.2,
            bytes_up=10,
            bytes_down=20,
        )
        for _ in range(10):
            await asyncio.sleep(0)

    assert "could not post sandbox telemetry" in caplog.text


# --- the live one ------------------------------------------------------------


@pytest.mark.skipif(
    not os.getenv("DAYTONA_API_KEY"),
    reason="needs a real Daytona key and the pdfkit-toolchain snapshot",
)
async def test_a_real_sandbox_ocrs_a_real_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Opt-in, and the only test here that costs money.

    Mirrors the ``requires_qpdf``-style pattern: skipped by default, so the
    suite stays offline, and run deliberately when there is a key and a
    snapshot to run it against.
    """
    monkeypatch.setattr(config, "DAYTONA_ENABLED", True)
    monkeypatch.setattr(config, "DAYTONA_API_KEY", os.environ["DAYTONA_API_KEY"])
    monkeypatch.setattr(config, "DAYTONA_MIN_FILES", 1)
    monkeypatch.setattr(config, "DAYTONA_MIN_BYTES", 0)
    batch = make_batch(tmp_path, {"scan.pdf": build_scanned_pdf(2)})

    outputs = await offload.maybe_offload("ocr", batch, {"languages": ["eng"]})

    assert outputs is not None
    assert outputs[0].download_name == "scan-ocr.pdf"
    assert outputs[0].path.read_bytes().startswith(b"%PDF-")
