"""Run a batch inside a Daytona sandbox instead of on the VPS.

The VPS is 2 vCPU and 8 GB, shared with eighteen other Coolify apps, and
sustained 100% CPU has twice tripped Hostinger's protective throttle. This
module is the escape hatch: for the operations that are genuinely CPU-bound a
batch is shipped to a throwaway 4 vCPU sandbox, run there by
:mod:`app.tools.remote_job`, and its outputs pulled back — with the VPS doing
nothing in between but relaying progress.

It is also, for OCR, simply faster: a Daytona core measured 2.62x a VPS core on
identical argv, and 3.67x under the realistic 4-vs-2 concurrency.

**Every driver's opt-in is three lines**, and every one of them is allowed to
be told "not this time":

    if (offloaded := await offload.maybe_offload("ocr", batch, options)) is not None:
        return offloaded

:func:`maybe_offload` returns ``None`` whenever the caller should just run
locally — the feature is off, the operation is not in the allowlist, the batch
is too small to be worth a round trip, or Daytona failed before it produced
anything. That last case is the important one: an infrastructure failure must
be invisible, because the local path can still produce the right answer. A
*document* failure is the exact opposite and must never be retried locally,
where it would fail identically having also burned the round trip.

A batch does not have to go to *one* sandbox. Phase 4 splits it across up to
``DAYTONA_MAX_SANDBOXES`` of them, provisioned and run concurrently, because
creating N sandboxes costs about the wall clock of creating one. The shards'
independent progress streams are folded back into a single coherent bar by
:class:`FanIn`, and their outputs are recombined in the batch's original file
order — so nothing outside this module, the frontend included, can tell how
many sandboxes a batch used.

**Nothing outside this module imports ``daytona``.** Everything
Daytona-specific sits behind :class:`SandboxPool`, which is what lets the tests
run the real shim as a local subprocess against a tmpdir and exercise this
orchestration offline, with no API key and no network.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shlex
import tarfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from fastapi import HTTPException

from app import config
from app.deps import UploadBatch
from app.services import progress
from app.services.responses import OutputFile

logger = logging.getLogger(__name__)

#: Where the sandbox keeps one job: inputs, spec, outputs and scratch.
WORK = "/work"
#: Where ``app/`` is unpacked. The shim runs with this as its working
#: directory, so ``python -m app.tools.remote_job`` resolves without the
#: package ever being installed into the sandbox's virtualenv.
APP_ROOT = "/app"
#: The interpreter ``backend/Dockerfile``'s ``base`` stage builds, and
#: therefore the one the ``pdfkit-toolchain`` snapshot carries.
PYTHON = "/opt/venv/bin/python"

#: Copied rather than imported from :mod:`app.tools.remote_job`: importing that
#: here would be a cycle (it imports every service, and ``ocr`` imports this
#: module). ``tests/test_offload.py`` asserts the two stay equal — the same
#: arrangement ``ocr.MARKER`` already has with its plugin.
MARKER = "pdfkit_progress"

#: How often the watchdog asks whether the client is still there. Coarser than
#: the local path's per-file :func:`progress.stop_if_cancelled`, because a
#: sandboxed batch has no per-file boundary on this side to check between.
WATCHDOG_SECONDS = 2.0

#: Below **both** of these a fold is not published. A sharded batch produces
#: several shims' frames interleaved, and every one of them would otherwise be
#: its own SSE message; the bar only has to read as live. Same shape and the
#: same reasoning as ``compress.MIN_PUBLISH_INTERVAL`` / ``MIN_PUBLISH_DELTA``,
#: copied rather than imported because ``compress`` imports *this* module.
PUBLISH_INTERVAL_SECONDS = 0.25
PUBLISH_DELTA_PERCENT = 1.0

#: Ceiling on the sandbox delete in ``finally``. Short, because by then the
#: client either has its file or has already been told what went wrong.
DISPOSE_TIMEOUT_SECONDS = 20

#: The label every sandbox this app creates carries, and the only thing
#: :func:`sweep_orphans` matches on — so a sweep can never touch a sandbox
#: some other tool on the same Daytona account owns.
LABELS = {"app": "pdfkit"}

#: Ceiling on the whole startup sweep. Deliberately short: a working app that
#: skipped a cleanup pass is strictly better than an app that will not start
#: because Daytona's API had a bad moment.
SWEEP_TIMEOUT_SECONDS = 30

#: A "line" longer than this is not a line. Same reasoning as
#: ``runner.MAX_PENDING_LINE``: hand it over and start again rather than grow a
#: buffer for a producer that is never going to end its line.
MAX_PENDING_LINE = 64 * 1024

#: Raised to the client when a batch that had already produced results lost its
#: sandbox. Deliberately not a silent local retry: the client has seen progress
#: for work that really happened, and some of it is billed.
INTERRUPTED = "remote_job_interrupted"
#: Raised only when ``DAYTONA_FALLBACK_LOCAL`` is off, which is a rollout
#: setting — it turns every Daytona failure into a visible one instead of one
#: hidden behind a successful local run.
FAILED = "offload_failed"

#: Why :func:`_watchdog` says the exec has to stop.
_CANCELLED = "cancelled"
_FAILED_FILE = "failed"


class SandboxPool(Protocol):
    """Everything this module needs from a sandbox provider.

    ``on_line`` takes ``("stdout" | "stderr", line)``, the same shape
    :data:`app.services.runner.OnLine` already uses — deliberately, so the
    callback handling here reads like the callback handling in every other
    service. ``None`` means the same thing it means there: nobody is reading
    this command's output, so an implementation is free to take whatever
    cheaper path that allows.
    """

    async def provision(self) -> str: ...

    async def put(self, sandbox_id: str, path: str, data: bytes) -> None: ...

    async def run(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str,
        env: dict[str, str],
        on_line: Callable[[str, str], None] | None = None,
    ) -> int: ...

    async def get(self, sandbox_id: str, path: str) -> bytes: ...

    async def dispose(self, sandbox_id: str) -> None: ...


class _Abandoned(Exception):
    """Daytona could not do the job, and had not produced anything yet.

    Never leaves this module. The caller sees ``None`` and runs the batch
    locally, exactly as if offload had never been attempted.
    """


# --- the feature's own concurrency ceiling -----------------------------------
#
# Remote work must never touch ``runner._slots``: that semaphore exists to
# protect the VPS's two cores, and a remote batch by design occupies none of
# them. Built lazily rather than at import, because import-time binding is what
# makes ``_slots`` awkward to reason about under monkeypatch.
#
# One permit is one *sandbox*, not one request: since Phase 4 a single batch
# takes as many as it has shards. ``DAYTONA_MAX_SANDBOXES`` therefore still
# means exactly what it says — the most sandboxes this process will ever have
# alive — and a big batch arriving first can legitimately take all of them,
# leaving a request behind it to run on the VPS. That is the same answer this
# module has always given a saturated pool, and the same one the app gave
# before the feature existed.

_remote_slots: asyncio.Semaphore | None = None
_remote_slots_size = 0


def _slots() -> asyncio.Semaphore:
    size = max(1, config.DAYTONA_MAX_SANDBOXES)
    global _remote_slots, _remote_slots_size
    if _remote_slots is None or _remote_slots_size != size:
        _remote_slots = asyncio.Semaphore(size)
        _remote_slots_size = size
    return _remote_slots


def reset() -> None:
    """Drop the semaphore so the next call rebuilds it. Tests only."""
    global _remote_slots, _remote_slots_size, _open
    _remote_slots = None
    _remote_slots_size = 0
    _open = 0


# --- what /health reports ----------------------------------------------------
#
# A process-local count of the sandboxes this process currently owns, kept by
# `_run_shard` — the one place that owns a sandbox's whole life, and provider-
# agnostic, so it is as true of the tests' fake pool as of `_DaytonaPool`.
#
# Deliberately a counter rather than a Daytona round trip: /health is a
# liveness endpoint and must not depend on a third party being up. It can
# therefore lag reality by the length of one `dispose()` — and a dispose that
# failed leaves a sandbox alive that this no longer counts, which is exactly
# what the Daytona dashboard is for during the go-live watch.

_open = 0


def open_sandboxes() -> int:
    """Sandboxes this process believes it has alive right now."""
    return _open


# --- the decision ------------------------------------------------------------


def eligible(operation: str, batch: UploadBatch) -> bool:
    """Whether this batch is worth a sandbox.

    Every value is read as ``config.X`` here rather than imported by name, so
    a test that monkeypatches ``config`` actually changes the answer.
    """
    if not config.DAYTONA_ENABLED:
        return False
    if operation not in config.DAYTONA_OPERATIONS:
        return False
    if len(batch.files) < config.DAYTONA_MIN_FILES:
        return False
    return sum(upload.size for upload in batch.files) >= config.DAYTONA_MIN_BYTES


def pool_factory() -> SandboxPool:
    """The pool one offloaded request uses. Monkeypatched by the tests."""
    return _DaytonaPool()


async def maybe_offload(
    operation: str, batch: UploadBatch, options: dict[str, Any]
) -> list[OutputFile] | None:
    """Run ``batch`` in a sandbox, or return ``None`` to let the caller run it.

    ``None`` is not an error path — it is the ordinary answer whenever
    offloading is not on, not applicable, or not currently possible.
    """
    if not eligible(operation, batch):
        return None

    slots = _slots()
    # One shard per file at most: an empty shard would provision a sandbox to
    # do nothing at all.
    wanted = min(len(batch.files), max(1, config.DAYTONA_MAX_SANDBOXES))
    shards = await _claim(slots, wanted)
    if shards == 0:
        # Every sandbox this process is allowed is already in use. Waiting
        # would stack a queue in front of a queue — the local path has its own
        # — so the honest move is to run this batch on the VPS, which is what
        # would have happened anyway before this feature existed.
        logger.info(
            "all %d remote slots are busy; running %s locally",
            _remote_slots_size,
            operation,
        )
        return None
    if shards < wanted:
        logger.info(
            "only %d of the %d slots %s wanted were free; sharding across %d",
            shards,
            wanted,
            operation,
            shards,
        )

    try:
        return await _offload(operation, batch, options, shards)
    except _Abandoned as error:
        logger.warning("offload of %s abandoned, falling back locally: %s", operation, error)
        if not config.DAYTONA_FALLBACK_LOCAL:
            raise HTTPException(status_code=502, detail=FAILED) from None
        return None
    finally:
        for _ in range(shards):
            slots.release()


async def _claim(slots: asyncio.Semaphore, wanted: int) -> int:
    """Take up to ``wanted`` permits, and never wait for one.

    Awaiting an unlocked semaphore does not suspend — the permit is taken
    before the first yield point — so this loop cannot be interleaved with
    another request's claim, and cannot leave a caller queued behind one.
    Fewer permits than asked for is an ordinary answer: the batch is simply
    split into fewer shards.
    """
    taken = 0
    while taken < wanted and not slots.locked():
        await slots.acquire()
        taken += 1
    return taken


# --- one offloaded batch, in shards ------------------------------------------


async def _offload(
    operation: str, batch: UploadBatch, options: dict[str, Any], shards: int
) -> list[OutputFile]:
    """Split the batch across ``shards`` sandboxes and run them all at once."""
    fan_in = FanIn(len(batch.files))
    # One pool for the whole request: it holds a sandbox per shard, and its
    # per-sandbox session bookkeeping is already keyed by sandbox id.
    pool = pool_factory()
    spans = _split(len(batch.files), shards)
    relays = [_Relay(progress.current(), fan_in, index) for index in range(shards)]

    # `return_exceptions=True` is load-bearing rather than defensive. Without
    # it the first shard to raise returns from here while its siblings are
    # still in flight, unawaited — so their sandboxes are disposed of at some
    # arbitrary later point if at all, and a sandbox nobody deleted bills
    # until its TTL. Every shard is waited for, failures included, and the
    # verdict is worked out afterwards from all of them.
    outcomes = await asyncio.gather(
        *(
            _run_shard(pool, operation, batch, options, span, relay)
            for span, relay in zip(spans, relays)
        ),
        return_exceptions=True,
    )
    return _recombine(outcomes, relays)


def _split(files: int, shards: int) -> list[range]:
    """``shards`` contiguous, roughly-even slices of ``files``.

    Contiguous rather than round-robin because file order is visible to the
    user: the frontend renders "File 4 of 10" from the fold, and the outputs
    come back in the order the files went up. Interleaving would keep both
    honest but make the sandboxes' own logs unreadable for no gain.
    """
    size, extra = divmod(files, shards)
    spans: list[range] = []
    start = 0
    for index in range(shards):
        # The first `extra` shards take one file more than the rest.
        stop = start + size + (1 if index < extra else 0)
        spans.append(range(start, stop))
        start = stop
    return spans


async def _run_shard(
    pool: SandboxPool,
    operation: str,
    batch: UploadBatch,
    options: dict[str, Any],
    span: range,
    relay: _Relay,
) -> list[OutputFile]:
    """One shard's whole life: its own sandbox, its own files, its own teardown.

    Identical to the single-sandbox flow this module had before sharding —
    sharding changes how many of these run at once and how their results are
    put back together, not what one of them does.
    """
    try:
        sandbox_id = await asyncio.wait_for(
            pool.provision(), timeout=config.DAYTONA_PROVISION_TIMEOUT_SECONDS
        )
    except Exception as error:
        # Nothing was created, so there is nothing to dispose of — and the
        # caller has lost nothing but the provisioning attempt.
        raise _Abandoned(f"provision failed: {type(error).__name__}: {error}") from error

    global _open
    _open += 1
    try:
        return await _run_batch(pool, sandbox_id, operation, batch, options, span, relay)
    finally:
        # Decremented whatever happens to the delete below: the count says how
        # many sandboxes this process is *using*, and one it has finished with
        # and failed to delete is the TTL's problem, not the bar's.
        _open -= 1
        # Per shard, not per request: one shard's failure must never leak a
        # sibling's sandbox. An unshielded delete gets cancelled by the very
        # cancellation that might have triggered it, and a sandbox nobody
        # deleted bills until its TTL. Shield it, bound it, and never let it
        # mask the real outcome.
        try:
            await asyncio.shield(
                asyncio.wait_for(pool.dispose(sandbox_id), DISPOSE_TIMEOUT_SECONDS)
            )
        except Exception:  # noqa: BLE001 — auto-stop and the TTL are the backstop
            logger.exception("could not dispose of sandbox %s", sandbox_id)


def _recombine(outcomes: list[Any], relays: list[_Relay]) -> list[OutputFile]:
    """One answer for the whole batch, from however many shards produced one.

    Three verdicts, in this order of precedence:

    * **Any shard raised an ``HTTPException``** — a document that cannot be
      processed, a client that hung up, a batch that outran its budget. It is
      the answer for the request, and re-running it locally would reach it
      again having also burned the round trip. Its siblings are not cut short
      when it happens: they finish their own files and dispose of their own
      sandboxes, which costs a little sandbox time and buys the guarantee that
      nothing is left running.
    * **Any shard failed for an infrastructure reason.** If *no* file anywhere
      has produced a result, nothing has been paid for or shown and the caller
      falls back to the local loop. Once **any** shard has produced **any**
      result the fallback is off the table for the whole batch — a local rerun
      would duplicate work that really happened and is already billed — so a
      lost shard is a hard 502 from there on.
    * **Everything worked** — the shards' outputs, concatenated in shard order,
      which is the batch's original file order because the spans are
      contiguous and ascending. Never completion order: some callers
      (Compress's per-file ``FileStat`` list) zip this against ``batch.files``
      positionally.
    """
    for outcome in outcomes:  # shard order, so the answer is deterministic
        if isinstance(outcome, HTTPException):
            raise outcome
    for outcome in outcomes:
        if isinstance(outcome, asyncio.CancelledError):
            raise outcome
    produced = sum(len(relay.results) for relay in relays)
    for outcome in outcomes:
        if isinstance(outcome, BaseException):
            if produced:
                logger.error(
                    "offload interrupted with %d results already in: %s",
                    produced,
                    outcome,
                )
                raise HTTPException(status_code=502, detail=INTERRUPTED)
            raise _Abandoned(_reason(outcome))
    return [output for outcome in outcomes for output in outcome]


def _reason(outcome: BaseException) -> str:
    """``_Abandoned`` already carries a written reason; anything else needs one."""
    if isinstance(outcome, _Abandoned):
        return str(outcome)
    return f"{type(outcome).__name__}: {outcome}"


async def _run_batch(
    pool: SandboxPool,
    sandbox_id: str,
    operation: str,
    batch: UploadBatch,
    options: dict[str, Any],
    span: range,
    relay: _Relay,
) -> list[OutputFile]:
    """Stage, run and fetch back one shard's slice of the batch.

    Every failure here that is not an ``HTTPException`` leaves as
    ``_Abandoned``. Whether that becomes a silent local fallback or a hard 502
    is not this shard's call to make: it depends on what the *other* shards
    have already produced, which only :func:`_recombine` can see.
    """
    try:
        await _stage(pool, sandbox_id, operation, batch, options, span)
    except Exception as error:
        raise _Abandoned(
            f"could not stage the job: {type(error).__name__}: {error}"
        ) from error

    try:
        exit_code = await _exec(pool, sandbox_id, operation, relay)
    except HTTPException:
        raise
    except Exception as error:
        if relay.failure is None:
            raise _Abandoned(
                f"the remote job failed: {type(error).__name__}: {error}"
            ) from error
        exit_code = 0

    if relay.failure is not None:
        # A document the services genuinely cannot process — an encrypted PDF,
        # say. The local path raises this identical HTTPException, so it
        # surfaces verbatim and is never retried: re-running it on the VPS
        # would fail the same way, having also burned the round trip.
        raise relay.failure

    if exit_code != 0 or len(relay.results) != len(span):
        raise _Abandoned(
            f"remote_job exited {exit_code} with "
            f"{len(relay.results)} of {len(span)} results"
        )

    try:
        return await _collect(pool, sandbox_id, batch, relay.results)
    except Exception as error:
        raise _Abandoned(
            f"could not fetch the outputs: {type(error).__name__}: {error}"
        ) from error


async def _stage(
    pool: SandboxPool,
    sandbox_id: str,
    operation: str,
    batch: UploadBatch,
    options: dict[str, Any],
    span: range,
) -> None:
    """Put ``app/``, this shard's inputs and its spec where the shim expects them.

    A shard's spec is the batch's spec with a subset of its ``files`` — same
    operation, same options — which is the whole reason ``remote_job`` needed
    no change for sharding: it already just processes whatever ``files`` its
    spec names.
    """
    await pool.put(sandbox_id, f"{WORK}/app.tgz", _app_tarball())
    # No on_line: nobody reads a tar's output, and saying so lets the pool
    # skip the streaming machinery — measured at 2.2 s of the 15 s an offloaded
    # 50-page scan took, for a command that finishes in milliseconds.
    unpacked = await pool.run(
        sandbox_id,
        # --no-same-owner: extracting as root, GNU tar otherwise tries to chown
        # each file to whatever uid the archive records, and fails the whole
        # extraction if it cannot. `_without_caches` already writes root/root
        # into the archive; this is the other half of the same defence, for an
        # archive built somewhere this code did not control.
        f"mkdir -p {APP_ROOT} && tar xzf {WORK}/app.tgz -C {APP_ROOT} --no-same-owner",
        cwd=WORK,
        env={},
    )
    if unpacked != 0:
        raise RuntimeError(f"unpacking app/ exited {unpacked}")

    entries = []
    for index in span:
        upload = batch.files[index]
        # The file's position in the *batch*, not in this shard. Nothing is
        # allowed to depend on that — ``deps._save_one`` has already made
        # ``upload.path.name`` unique batch-wide for exactly this reason, and
        # the outputs named after it from every shard land in the one
        # ``batch.workspace("out")`` — but numbering a shard's inputs 00, 01,
        # 02 again would make two sandboxes' specs and logs describe different
        # files with the same name, for no gain.
        remote = f"in/{index:02d}-{upload.path.name}"
        await pool.put(sandbox_id, f"{WORK}/{remote}", upload.path.read_bytes())
        entries.append(
            {
                "input": remote,
                "original_name": upload.original_name,
                "size": upload.size,
            }
        )

    # Relative inputs resolve against the spec's own directory, so neither side
    # has to agree on anything but ``/work``.
    spec = {
        "operation": operation,
        "options": options,
        "files": entries,
        "out_dir": f"{WORK}/out",
        "scratch_dir": f"{WORK}/scratch",
    }
    await pool.put(sandbox_id, f"{WORK}/spec.json", json.dumps(spec).encode("utf-8"))


async def _exec(
    pool: SandboxPool, sandbox_id: str, operation: str, relay: _Relay
) -> int:
    """Run the shim, relaying its progress, until it finishes or must not.

    Three ways this ends early, each a different kind of news: the client hung
    up (499, the same status the local path raises), a file failed in a way no
    amount of waiting will fix (stop, and let the caller re-raise it verbatim),
    or the whole batch outran its budget (504, identical to a local timeout).
    """
    command = f"{PYTHON} -m app.tools.remote_job {WORK}/spec.json"
    # MAX_CONCURRENT_JOBS is how the sandbox learns its own size: `os.cpu_count()`
    # inside one reports the *runner's* cores — measured 48 against a 4-CPU
    # quota. It sizes `runner._slots` in the shim's process, and through
    # `ocr.ocr_to_path` it also pins `ocrmypdf --jobs`.
    env = {"MAX_CONCURRENT_JOBS": str(config.DAYTONA_SANDBOX_CPU)}

    running = asyncio.create_task(
        pool.run(sandbox_id, command, cwd=APP_ROOT, env=env, on_line=relay.on_line)
    )
    watching = asyncio.create_task(_watchdog(relay))
    budget = config.remote_timeout_for(operation)

    try:
        done, _ = await asyncio.wait(
            {running, watching}, timeout=budget, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        watching.cancel()

    if running in done:
        return running.result()

    running.cancel()
    await asyncio.gather(running, watching, return_exceptions=True)

    if watching not in done:
        # Neither finished inside the budget.
        logger.error("offloaded %s outran its %ss budget", operation, budget)
        raise HTTPException(status_code=504, detail="processing_timed_out")
    if watching.result() == _CANCELLED:
        logger.info("client disconnected; abandoning the offloaded batch")
        raise HTTPException(status_code=499, detail=progress.CANCELLED)
    # A per-file failure; ``_run_batch`` re-raises ``relay.failure`` verbatim.
    return 0


async def _watchdog(relay: _Relay) -> str:
    """Why the exec should stop before the shim is done, if it should.

    Polling rather than event-driven, because neither thing it watches for
    needs noticing within milliseconds: a couple of extra seconds of sandbox
    time on a doomed batch is far less than the round trip that produced it.
    """
    while True:
        if relay.failure is not None:
            return _FAILED_FILE
        if await progress.client_gone():
            return _CANCELLED
        await asyncio.sleep(WATCHDOG_SECONDS)


async def _collect(
    pool: SandboxPool,
    sandbox_id: str,
    batch: UploadBatch,
    results: list[dict[str, Any]],
) -> list[OutputFile]:
    """Download what the shim produced into the batch's own workspace.

    Downloads happen here rather than inside ``on_line`` because that callback
    runs on the log pump and must never block — the rule ``runner.OnLine``
    already carries. The wait is the transfer only: about a second for a full
    50 MB file on the measured link.

    Into ``batch.workspace("out")``, the very directory the local path writes
    to, so the response and its cleanup behave identically either way.
    """
    workspace = batch.workspace("out")
    outputs: list[OutputFile] = []
    for result in results:
        remote = f"{WORK}/out/{result['output']}"
        data = await pool.get(sandbox_id, remote)
        expected = int(result.get("result_size") or 0)
        if expected and len(data) != expected:
            raise RuntimeError(
                f"{remote} came back {len(data)} bytes, expected {expected}"
            )
        destination = workspace / Path(str(result["output"])).name
        destination.write_bytes(data)
        outputs.append(
            OutputFile(
                path=destination,
                download_name=str(result["download_name"]),
                media_type=str(result["media_type"]),
            )
        )
    return outputs


# --- reading the shim's two streams ------------------------------------------


@dataclass(slots=True)
class _Relay:
    """Turns one shard's stdout and stderr into results and progress frames.

    Called from the log pump, so every method here is the same kind of code an
    ``runner.OnLine`` implementation is: parse, record, return. No awaits, no
    I/O, no raising — a callback that blocks blocks the log stream, and a
    callback that raises loses it.
    """

    publisher: progress.Publisher
    #: Shared with every other shard's relay: this is where they become one bar.
    fan_in: FanIn
    #: Which shard this relay is reading, as :class:`FanIn` counts them.
    shard: int
    results: list[dict[str, Any]] = field(default_factory=list)
    #: The first per-file ``HTTPException``, rebuilt from its result line.
    failure: HTTPException | None = None

    def on_line(self, stream: str, line: str) -> None:
        if not line.strip():
            return
        if stream == "stdout":
            self._result(line)
        else:
            self._frame(line)

    def _result(self, line: str) -> None:
        """One line of the shim's per-file result contract."""
        try:
            payload = json.loads(line)
        except ValueError:
            logger.warning("unparseable result line from remote_job: %.200s", line)
            return
        status = payload.get("status")
        if status == "error" and self.failure is None:
            self.failure = HTTPException(
                status_code=int(payload.get("http_status") or 500),
                detail=payload.get("detail"),
            )
        elif status == "ok":
            self.results.append(payload)

    def _frame(self, line: str) -> None:
        if MARKER not in line:
            # Anything else on stderr is the shim's own diagnostics, which
            # belong in our log rather than on a progress bar.
            logger.info("remote_job: %.500s", line.strip())
            return
        try:
            frame = json.loads(line)
        except ValueError:
            return
        if not isinstance(frame, dict):
            return
        self.fan_in.update(self.shard, frame)
        self.fan_in.publish(self.publisher)


class FanIn:
    """N shards' independent progress streams, folded into one bar.

    Each shard's frame is ``{"file": i, "total": n, "name": …, "step": …,
    "percent": p}`` — but ``n`` is that **shard's own** file count and ``p``
    that shard's own fold across it, so relaying either one straight to the
    client would make the bar thrash between unrelated 0-100 ranges and then
    freeze wherever ``Publisher._monotonic`` clamped it.

    The fix is to work in whole files, which are shard-size independent. Two
    numbers per shard are enough, because a shard runs its files strictly in
    order: "file 4 of this shard" is itself the news that its files 1-3 are
    finished. So the batch's position is the sum, across shards, of the files
    each has completed plus the fraction of the one it is on.

    That sum cannot go backwards. Within a shard it is
    ``clamp(p * n, i - 1, i)``, and ``p * n`` is non-decreasing because the
    shim's own publisher is monotonic, as is ``i`` — so when a new file starts
    and the fraction drops to zero, the completed count has already risen by
    one to pay for it. ``Publisher._monotonic`` is still the backstop, but it
    never has to do anything here.

    The one thing this deliberately does *not* copy from the design sketch is
    keeping a fraction per ``(shard, file)`` pair: a file's last frame before
    the next one starts is rarely 100% of itself, so summing those would leave
    the bar permanently short of the files it had already finished.
    """

    __slots__ = (
        "_total",
        "_done",
        "_fraction",
        "_name",
        "_step",
        "_published_at",
        "_published",
    )

    def __init__(self, total_files: int) -> None:
        self._total = max(1, total_files)
        #: shard -> whole files it has finished.
        self._done: dict[int, int] = {}
        #: shard -> 0..1 through the file it is working on now.
        self._fraction: dict[int, float] = {}
        self._name = ""
        self._step = ""
        #: When the bar was last pushed, and to what, for the throttle.
        self._published_at = 0.0
        self._published = -1.0

    @property
    def done(self) -> float:
        """Whole files finished across every shard, plus the parts in flight."""
        return sum(self._done.values()) + sum(self._fraction.values())

    def update(self, shard: int, frame: dict[str, Any]) -> None:
        """Record one shard's frame. Nonsense is dropped, never raised."""
        try:
            shard_total = int(frame["total"])
            index = int(frame["file"])
            percent = frame.get("percent")
            position = (float(percent) if percent is not None else 0.0) / 100
        except (KeyError, TypeError, ValueError):
            return
        if shard_total <= 0 or index <= 0:
            return
        # Back this file's own 0..1 fraction out of the shard's own fold: the
        # shim published (files it had finished + this file's fraction) over
        # its own file count.
        finished = index - 1
        self._done[shard] = finished
        self._fraction[shard] = max(0.0, min(1.0, position * shard_total - finished))
        if shard == 0 or not self._name:
            # The detail line follows one shard rather than whichever spoke
            # last, so the name and step change at a believable reading pace
            # instead of flickering between unrelated files. Shard 0 because it
            # holds the batch's first files, which is where a reader expects a
            # batch to start — but until it has said anything, any shard's file
            # is better than a blank line, and it hands over the moment shard 0
            # does speak.
            self._name = str(frame.get("name") or "")
            self._step = str(frame.get("step") or "")

    def publish(self, publisher: progress.Publisher) -> None:
        """Push the fold to the client, unless it has just been pushed.

        ``index``/``name``/``step`` drive the detail line only and are not in
        lockstep with the arithmetic — which is exactly the freedom
        ``Publisher.batch`` was written to allow.
        """
        done = self.done
        percent = done / self._total * 100
        now = time.monotonic()
        if (
            done < self._total
            and now - self._published_at < PUBLISH_INTERVAL_SECONDS
            and percent - self._published < PUBLISH_DELTA_PERCENT
        ):
            return
        self._published_at, self._published = now, percent
        publisher.batch(
            done=done,
            total=self._total,
            index=min(int(done) + 1, self._total),
            name=self._name,
            step=self._step,
        )


class _Lines:
    """Splits a stream into lines across arbitrary chunk boundaries.

    Daytona's log websocket delivers chunks, not lines, so a JSON frame can
    and does arrive in two pieces. ``runner._Pump`` solves the same problem for
    a subprocess pipe; this is the small version of it, for a callback that is
    handed strings.
    """

    __slots__ = ("_name", "_on_line", "_pending")

    def __init__(self, name: str, on_line: Callable[[str, str], None]) -> None:
        self._name = name
        self._on_line = on_line
        self._pending = ""

    def feed(self, chunk: str) -> None:
        self._pending = (self._pending + chunk).replace("\r\n", "\n")
        *lines, self._pending = self._pending.split("\n")
        for line in lines:
            self._emit(line)
        # No separator in sight: hand over what we have in fixed pieces rather
        # than grow a buffer for a producer that never ends its "line".
        while len(self._pending) > MAX_PENDING_LINE:
            self._emit(self._pending[:MAX_PENDING_LINE])
            self._pending = self._pending[MAX_PENDING_LINE:]

    def close(self) -> None:
        """Whatever arrived without a trailing newline is still a line."""
        if self._pending:
            self._emit(self._pending)
            self._pending = ""

    def _emit(self, line: str) -> None:
        try:
            self._on_line(self._name, line)
        except Exception:  # noqa: BLE001 — a broken listener must not kill the job
            logger.exception("offload listener raised on a %s line", self._name)


# --- the app/ payload --------------------------------------------------------

_tarball: bytes | None = None


def _app_tarball() -> bytes:
    """``backend/app/`` as a gzipped tar, built once per process.

    Around 60 KB compressed, measured at 50 ms for the upload and the
    ``tar xzf`` together — cheap enough to pay on every job, which is what
    keeps application code out of the sandbox snapshot and leaves that snapshot
    stale only when the *toolchain* changes.
    """
    global _tarball
    if _tarball is None:
        package = Path(__file__).resolve().parents[1]
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            archive.add(package, arcname="app", filter=_without_caches)
        _tarball = buffer.getvalue()
    return _tarball


def _without_caches(entry: tarfile.TarInfo) -> tarfile.TarInfo | None:
    """Drop compiled caches, and record nothing about the machine we are on.

    The caches go because the sandbox rebuilds them for its own Python.

    The ownership is normalised because of a failure found live on the VPS:
    ``tarfile`` records the *source* file's uid/gid, GNU tar extracting as root
    dutifully tries to chown every file to it, and a uid that is meaningless in
    the sandbox (197609, a Windows-mapped owner arriving via a bind-mounted
    checkout) makes it exit 2 — after writing every file correctly. ``_stage``
    reads that as "the job could not be staged" and the batch falls back to the
    VPS for a reason that has nothing to do with either machine's Python.
    """
    if "__pycache__" in entry.name or entry.name.endswith((".pyc", ".pyo")):
        return None
    entry.uid = entry.gid = 0
    entry.uname = entry.gname = "root"
    return entry


# --- Daytona -----------------------------------------------------------------


_client: Any = None
_client_key: tuple[str, str] | None = None


def _daytona() -> Any:
    """This process's Daytona client, built on first use.

    A singleton so the TLS connection pool is reused across requests, which is
    part of what makes the measured 60 MB/s a per-transfer number rather than a
    per-handshake one. Rebuilt when the credentials change under it, so a
    monkeypatched config in a live test is not silently ignored.

    **The pool it holds belongs to the loop that built it.** Under uvicorn that
    is one loop for the life of the process, the lifespan startup sweep
    included, so nothing in this app crosses one. A harness that boots the app
    through ``TestClient`` does — that runs the lifespan on a portal loop of
    its own — and gets "attached to a different loop" from the first call. The
    fix there is to clear this cache either side of the boot, not to make the
    client per-call: a per-call client would pay a TLS handshake on every
    transfer, which is most of what this exists to avoid.

    Imported inside the function rather than at module scope so this module
    stays importable on a machine with no ``daytona`` installed — every test
    but the opt-in live one injects its own pool and never reaches here.
    """
    from daytona import AsyncDaytona, DaytonaConfig

    global _client, _client_key
    key = (config.DAYTONA_API_KEY, config.DAYTONA_API_URL)
    if _client is None or _client_key != key:
        _client = AsyncDaytona(
            DaytonaConfig(
                api_key=config.DAYTONA_API_KEY,
                api_url=config.DAYTONA_API_URL,
                # Where sandboxes are created. The SDK carries this on the
                # client rather than on each create call, and an empty string
                # means "the organization's default region", not "no region".
                target=config.DAYTONA_TARGET or None,
            )
        )
        _client_key = key
    return _client


# --- the startup sweep -------------------------------------------------------


async def sweep_orphans() -> int:
    """Delete every ``pdfkit`` sandbox alive at startup. Best effort, always.

    A fresh process has nothing running yet, so any sandbox carrying
    :data:`LABELS` at this moment belongs to a process that is gone —
    a Coolify redeploy ``SIGKILL``-ing uvicorn mid-batch skips every
    ``finally`` in this module, which is the one hole ``try/finally`` cannot
    cover.

    This is layer four of four, not the guarantee. ``ephemeral=True``,
    ``auto_stop_interval`` and ``ttl_minutes`` already mean no sandbox can
    outlive ``DAYTONA_TTL_MINUTES`` on its own; the sweep only makes that
    happen in seconds rather than half an hour, and gives an operator a line
    in the startup log saying so.

    Every failure is caught and logged. Startup must not depend on a third
    party being up, and an app that skipped a cleanup pass is strictly better
    than an app that will not start.

    Returns how many sandboxes it deleted — 0 when the feature is off, when
    there was nothing to find, and when it could not look.
    """
    if not config.DAYTONA_ENABLED:
        return 0
    try:
        deleted = await asyncio.wait_for(_sweep(), SWEEP_TIMEOUT_SECONDS)
    except Exception as error:  # noqa: BLE001 — see the docstring
        # Loud on purpose: whether the sweep ran is the thing an operator
        # watching the Daytona dashboard should not have to guess at.
        logger.warning(
            "orphan sweep skipped (%s: %s); relying on ephemeral + auto-stop + "
            "the %s-minute TTL, so nothing can outlive that anyway",
            type(error).__name__,
            error,
            config.DAYTONA_TTL_MINUTES,
        )
        return 0
    logger.info(
        "orphan sweep: deleted %d leftover sandbox(es) labelled %s", deleted, LABELS
    )
    return deleted


async def _sweep() -> int:
    """List the labelled sandboxes and delete them, tolerating each delete.

    The list is materialised before anything is deleted: ``list()`` is a
    paginated async iterator, and deleting out from under its cursor is not a
    thing worth finding out the behaviour of.
    """
    from daytona import ListSandboxesQuery

    orphans = [
        sandbox
        async for sandbox in _daytona().list(ListSandboxesQuery(labels=dict(LABELS)))
    ]
    if not orphans:
        return 0
    logger.warning(
        "found %d sandbox(es) left over from a previous process: %s",
        len(orphans),
        ", ".join(sandbox.id for sandbox in orphans),
    )
    outcomes = await asyncio.gather(
        *(sandbox.delete() for sandbox in orphans), return_exceptions=True
    )
    for sandbox, outcome in zip(orphans, outcomes):
        # One sandbox that will not delete must not cost the others theirs.
        if isinstance(outcome, BaseException):
            logger.warning("could not delete orphan %s: %s", sandbox.id, outcome)
    return sum(not isinstance(outcome, BaseException) for outcome in outcomes)


#: What "the snapshot is there, but Daytona has put it to sleep" looks like.
#: Daytona deactivates a snapshot after roughly two weeks unused and reports it
#: in the create's message rather than as a type the SDK exposes, so this
#: matches on text — narrowly, because the retry costs an API call and a second
#: create, and "snapshot" plus an explicit not-active is as specific as the
#: wire makes possible.
_INACTIVE = ("inactive", "not active", "is not activated")


def _looks_inactive(error: BaseException) -> bool:
    message = str(error).lower()
    return "snapshot" in message and any(phrase in message for phrase in _INACTIVE)


class _DaytonaPool:
    """:class:`SandboxPool` over the ``daytona`` SDK.

    One pool per offloaded request, holding one sandbox per shard — hence the
    mappings: every method is addressed by sandbox id, and a shard's failure
    touches nothing but its own entries.
    """

    __slots__ = ("_sandboxes", "_sessions")

    def __init__(self) -> None:
        self._sandboxes: dict[str, Any] = {}
        #: One shell session per sandbox, created on that sandbox's first
        #: command and reused by every command after it.
        self._sessions: dict[str, str] = {}

    async def provision(self) -> str:
        """A sandbox from the configured snapshot, waking the snapshot if asked.

        The wake-and-retry happens **once**, never in a loop: a snapshot that
        is still refusing after an explicit activate is a real failure, and the
        caller already has a correct answer for one — ``_Abandoned``, then the
        VPS. Two round trips is the most an ordinary request should ever spend
        finding that out.
        """
        try:
            return await self._create()
        except Exception as error:
            if not _looks_inactive(error):
                raise
            logger.warning(
                "snapshot %s looks deactivated (%s); activating and retrying once",
                config.DAYTONA_SNAPSHOT,
                error,
            )
            await _daytona().snapshot.activate(config.DAYTONA_SNAPSHOT)
            return await self._create()

    async def _create(self) -> str:
        from daytona import CreateSandboxFromSnapshotParams

        # No cpu/memory/disk here: the API rejects them alongside a snapshot
        # ("Cannot specify Sandbox resources when using a snapshot"). A
        # snapshot's resources are fixed when it is built, which is why
        # DAYTONA_SANDBOX_CPU and friends are read by scripts/build_snapshot.py
        # and not by this call.
        sandbox = await _daytona().create(
            CreateSandboxFromSnapshotParams(
                snapshot=config.DAYTONA_SNAPSHOT,
                # `dispose` deletes it on the way out; these two are what stop
                # a sandbox outliving a VPS that died mid-request.
                ephemeral=True,
                auto_stop_interval=config.DAYTONA_AUTO_STOP_MINUTES,
                ttl_minutes=config.DAYTONA_TTL_MINUTES,
                # What `sweep_orphans` matches on, and the only thing that
                # tells a sandbox of ours from anything else on the account.
                labels=dict(LABELS),
            ),
            timeout=config.DAYTONA_PROVISION_TIMEOUT_SECONDS,
        )
        self._sandboxes[sandbox.id] = sandbox
        return sandbox.id

    async def put(self, sandbox_id: str, path: str, data: bytes) -> None:
        await self._sandboxes[sandbox_id].fs.upload_file(data, path)

    async def get(self, sandbox_id: str, path: str) -> bytes:
        data = await self._sandboxes[sandbox_id].fs.download_file(path)
        if data is None:
            raise RuntimeError(f"{path} came back empty")
        return data

    async def run(
        self,
        sandbox_id: str,
        command: str,
        *,
        cwd: str,
        env: dict[str, str],
        on_line: Callable[[str, str], None] | None = None,
    ) -> int:
        """Start the command, stream both its pipes, and return its exit code.

        With no ``on_line`` this is a single blocking ``exec`` — one HTTP round
        trip, cwd and env passed natively — because the streaming path below
        costs a session, a websocket and an exit-code poll, and there is no
        point paying those for output nobody will read.

        ``run_async=True`` is what makes the streaming path a stream rather
        than a wait: the
        exec call returns as soon as the command *starts*, handing back a
        command id, and the log websocket then delivers stdout and stderr as
        separate incremental callbacks. The blocking form returns one combined
        blob at the end, which is useless for a progress bar on a job that can
        run for minutes.

        ``SessionExecuteRequest`` carries no cwd or env of its own, so both go
        onto the command line — which is why everything interpolated here is
        quoted.
        """
        from daytona import SessionExecuteRequest

        process = self._sandboxes[sandbox_id].process
        if on_line is None:
            finished = await process.exec(command, cwd=cwd, env=env or None)
            return int(finished.exit_code or 0)

        # One session per sandbox, not per command: a second `create_session`
        # under the same id is a hard DaytonaConflictError, and a session is a
        # shell meant to be reused anyway. Every command still carries its own
        # `cd`, so nothing depends on what the last one left the shell in.
        session_id = self._sessions.get(sandbox_id)
        if session_id is None:
            session_id = f"pdfkit-{sandbox_id}"
            await process.create_session(session_id)
            self._sessions[sandbox_id] = session_id

        exports = "".join(
            f"{name}={shlex.quote(value)} " for name, value in sorted(env.items())
        )
        started = await process.execute_session_command(
            session_id,
            SessionExecuteRequest(
                command=f"cd {shlex.quote(cwd)} && {exports}{command}",
                run_async=True,
            ),
        )

        out, err = _Lines("stdout", on_line), _Lines("stderr", on_line)
        try:
            await process.get_session_command_logs_async(
                session_id, started.cmd_id, out.feed, err.feed
            )
        finally:
            out.close()
            err.close()

        # The log socket closes at EOF, which can beat the command record being
        # updated by a moment; poll briefly rather than report a null exit.
        for _ in range(20):
            finished = await process.get_session_command(session_id, started.cmd_id)
            if finished.exit_code is not None:
                return int(finished.exit_code)
            await asyncio.sleep(0.25)
        raise RuntimeError(f"{session_id} never reported an exit code")

    async def dispose(self, sandbox_id: str) -> None:
        sandbox = self._sandboxes.pop(sandbox_id, None)
        self._sessions.pop(sandbox_id, None)
        if sandbox is not None:
            # Deleting the sandbox takes its sessions with it; there is no
            # point spending a second round trip closing them first.
            await sandbox.delete()
