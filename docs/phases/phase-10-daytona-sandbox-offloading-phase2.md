# Phase 10 (part 2) — Daytona offload: config, `_DaytonaPool`, wired into OCR only

## Goal

Build the first working, end-to-end offload path — config knobs, a real `SandboxPool`
implementation backed by Daytona, and `offload.maybe_offload()` — wired into exactly one
operation, `ocr.ocr()`. `DAYTONA_ENABLED` defaults to `false`, so this phase ships with the
feature dark in production; turning it on is a deliberate, separate act (Phase 5).

## Prerequisites

- Phase 0 (`docs/phases/phase-10-daytona-sandbox-offloading-phase0.md`) — **done, GO**.
  See `STATUS.md`'s "Phase 10 part 0" section for the full numbers; the ones that shape
  this phase are pulled into Context below.
- Phase 1 (`docs/phases/phase-10-daytona-sandbox-offloading-phase1.md`) — **done and
  verified**. `backend/app/tools/remote_job.py` exists, is tested by
  `backend/tests/test_remote_job.py` (17 tests, offline), and is the thing this phase's
  orchestrator invokes inside a sandbox. Read that file before starting this phase — its
  spec format, result contract, and the `run_remote_job()` test helper
  (`backend/tests/test_remote_job.py:80`) are load-bearing here, not just background.
- A **real `pdfkit-toolchain` snapshot must exist before any of this phase's code can be
  exercised against a live sandbox.** Daytona's stock/default snapshots carry no
  Ghostscript, Tesseract, or OCRmyPDF, so `remote_job.py` cannot run at all on one. This
  phase is what builds that snapshot for the first time (see §1) — the CI automation that
  keeps it fresh on every dependency change is Phase 5's job, not this one's.

## Context

`backend` runs on a 2 vCPU / 8 GB Hostinger VPS shared with 18+ Coolify apps; sustained
100% CPU has twice triggered Hostinger's protective throttle. This feature offloads
CPU-heavy work into per-request Daytona sandboxes to keep that from happening again, and —
per Phase 0's real measurement — as a genuine speed win for at least one operation.

**What Phase 0 actually found, and what it changes here:**

| Finding | Effect on this phase |
|---|---|
| VPS↔Daytona median throughput **60.1 MB/s** (not the 1.4 MB/s the plan worried about) | Transfer is noise. `DAYTONA_MIN_BYTES` is a cheap floor, not the economic gate the original design assumed — `DAYTONA_MIN_FILES` and the operation allowlist do the real gating. |
| Create→ready from a named snapshot: **0.79 s**. `app/` tarball (61 KB gz) upload+extract: **0.05 s** | Total fixed overhead per offloaded batch is ~1 s plus ~1.5 s worst-case transfer for a full 50 MB file — call it 2.5 s. `DAYTONA_OVERHEAD_SECONDS` (below) can stay conservative without meaningfully hurting the fallback-vs-wait tradeoff. |
| A Daytona core is **2.62×** a VPS core on OCR (single-core comparison), **3.67×** under realistic 4-vs-2 concurrency. Ghostscript compress only 1.75×, on a run too short (0.3–0.6 s) to be good evidence either way | OCR is the operation this phase wires up. It clears the plan's own "≥2×" kill bar with margin; Compress does not yet have evidence either way and stays out until Phase 3, last. |
| **`os.cpu_count()` / `os.sched_getaffinity(0)` inside a Daytona sandbox report the *runner's* cores (measured 48), not the sandbox's cgroup quota (4)** | Anything that auto-sizes a worker pool from `os.cpu_count()` is wrong inside a sandbox. `runner._slots` already avoids this by reading `config.MAX_CONCURRENT_JOBS`, an explicit env var — Phase 1 already exploits that. OCRmyPDF does **not** avoid it: it has no equivalent explicit knob passed today, so this phase adds one (§5). |

Two later phases build what this one deliberately leaves out:

- **Phase 3**: the same wiring for `compress`, `word`, `markdown`.
- **Phase 4**: splitting a batch across `DAYTONA_MAX_SANDBOXES` > 1 sandboxes and folding
  their progress together.

## 0. First, verify the one thing Phase 0 didn't test: streaming exec

Phase 0's spike (`backend/scripts/spike_offload.py`) talked to Daytona over raw REST via
`urllib`, deliberately avoiding the `daytona` SDK so the throwaway script could run
unmodified in the production image. Its `exec()` (`spike_offload.py:249`) is a **single
blocking call** to `POST {toolbox}/process/execute` — it waits for the whole command and
returns one final `(exit_code, combined_output)`. That was fine for measuring latency; it
is **not** fine for this phase, which needs to relay `remote_job.py`'s stderr progress
frames to the client *while the job is still running*, potentially for minutes on OCR.

Live streaming needs Daytona's **session** API (`process/session` → `session/{id}/exec` →
a log-streaming call against the running command), which the SDK wraps. Before writing
`_DaytonaPool.run()` for real, spend a small amount of time confirming, against the actual
pinned `daytona` package version, that:

1. An async session exec call exists that returns as soon as the command starts (not when
   it finishes), and a log-streaming call exists that delivers stdout/stderr as separate,
   incremental callbacks — the plan's design assumes a shape like
   `get_session_command_logs_async(session_id, cmd_id, on_stdout, on_stderr)`, but treat
   that as this design's *intent*, not a literal signature to paste in: verify the real
   method name and callback shape against whatever version gets pinned in step 1 below,
   the same way Phase 0 verified real numbers instead of trusting the docs.
2. `list()` on that same pinned version does not hit the removed `/sandbox/paginated`
   endpoint (a known bug on the previously-pinned `0.113.1`). This isn't needed until
   Phase 5's orphan sweep, but it costs nothing to confirm now while the SDK is freshly
   installed and being poked at anyway — better to find it now than to build Phase 5 on
   an assumption.

If neither holds on any reasonably current release, treat it as a Phase 0-style kill/reshape
moment for *this specific piece*, not the whole feature: a fallback of polling
`session/{id}/command/{cmdId}` output on a short interval (e.g. every 500 ms) is materially
worse UX (a progress bar that jumps in visible steps) but not fatal, since the median frame
rate a human perceives is forgiving. Don't build the polling fallback pre-emptively — only
reach for it if the callback API genuinely isn't there.

## 1. `backend/Dockerfile`: the `toolchain` stage, and the first `pdfkit-toolchain` snapshot

The `base` stage (`Dockerfile:4`) is already exactly the toolchain-only layer — every apt
package (Ghostscript, Tesseract, qpdf, …) plus `uv sync --locked --no-dev
--no-install-project`, with no `COPY app`. No Dockerfile surgery needed there. Add only:

```dockerfile
FROM base AS toolchain
ENTRYPOINT ["sleep", "infinity"]
```

(`base` itself has no long-running entrypoint — a plain `python:3.12-slim` container drops
into a REPL and exits — Daytona needs something that stays up while `app/` is uploaded and
the shim is exec'd into it.)

Build and push it once, by hand, using the exact recipe Phase 0 already worked out the
hard way (see `STATUS.md`'s "Resulting changes to the plan" under Phase 10 part 0) — this
is a one-off bootstrap for this phase; **Phase 5** is what turns it into a CI job with
content-hash tagging:

```
POST /snapshots   { "name": "pdfkit-toolchain", "buildInfo": { "dockerfileContent": <toolchain stage>, ... } }
```

Two API constraints Phase 0 found, both easy to trip over:

- A top-level `entrypoint` may **not** accompany `buildInfo` — Daytona rejects it with
  "Cannot specify an entrypoint when using a build info entry." The `ENTRYPOINT` belongs
  **in** the Dockerfile content, as above, not as a separate request field.
- `cpu`/`memory`/`disk` may **not** be sent on `POST /sandbox` when creating **from a
  snapshot** — "Cannot specify Sandbox resources when using a snapshot." Resources are
  fixed at snapshot-build time, not per-sandbox-create. This means `DAYTONA_SANDBOX_CPU`
  etc. (§2) size the **snapshot build request**, not every `provision()` call — read that
  config once, at build time, not baked into `_DaytonaPool.provision()`'s per-call body.

Confirm the resulting snapshot with a throwaway sandbox create (`daytona` CLI or a one-off
script) before wiring `_DaytonaPool` against it: exec `ocrmypdf --version`, `gs --version`
inside it and confirm both resolve.

## 2. `backend/app/config.py` — new knobs, all read at call time

Per `CLAUDE.md`'s existing convention (`auth.py`/`ratelimit.py`): every value below is read
as `config.X` **inside the function that uses it**, never imported by name at module scope,
so `monkeypatch` in tests actually works. Follow the existing `_parse_origins` pattern
(`config.py:49`) for the one CSV-shaped value:

```python
DAYTONA_ENABLED = os.getenv("DAYTONA_ENABLED", "false").lower() == "true"
DAYTONA_API_KEY = os.getenv("DAYTONA_API_KEY", "")
DAYTONA_API_URL = os.getenv("DAYTONA_API_URL", "https://app.daytona.io/api")
DAYTONA_TARGET = os.getenv("DAYTONA_TARGET", "eu")
DAYTONA_SNAPSHOT = os.getenv("DAYTONA_SNAPSHOT", "pdfkit-toolchain")

# Only "ocr" until Phase 3 adds the other three drivers' offload heads — a
# CSV naming an operation with no head yet would be a silent no-op, so the
# default names only what this phase can actually do.
DAYTONA_OPERATIONS = _parse_origins(os.getenv("DAYTONA_OPERATIONS", "ocr"))

DAYTONA_MAX_SANDBOXES = int(os.getenv("DAYTONA_MAX_SANDBOXES", "2"))
DAYTONA_SANDBOX_CPU = int(os.getenv("DAYTONA_SANDBOX_CPU", "4"))
DAYTONA_SANDBOX_MEMORY_GB = int(os.getenv("DAYTONA_SANDBOX_MEMORY_GB", "4"))
DAYTONA_SANDBOX_DISK_GB = int(os.getenv("DAYTONA_SANDBOX_DISK_GB", "10"))

DAYTONA_MIN_FILES = int(os.getenv("DAYTONA_MIN_FILES", "2"))
# A cheap floor, not an economic gate — Phase 0 measured 60 MB/s, so byte
# count barely moves the decision. Kept so a single tiny file never pays
# provisioning latency, not because transfer cost is the risk.
DAYTONA_MIN_BYTES = int(os.getenv("DAYTONA_MIN_BYTES", "5242880"))

DAYTONA_PROVISION_TIMEOUT_SECONDS = int(os.getenv("DAYTONA_PROVISION_TIMEOUT_SECONDS", "150"))
DAYTONA_OVERHEAD_SECONDS = int(os.getenv("DAYTONA_OVERHEAD_SECONDS", "90"))

DAYTONA_AUTO_STOP_MINUTES = int(os.getenv("DAYTONA_AUTO_STOP_MINUTES", "5"))
DAYTONA_TTL_MINUTES = int(os.getenv("DAYTONA_TTL_MINUTES", "30"))
DAYTONA_FALLBACK_LOCAL = os.getenv("DAYTONA_FALLBACK_LOCAL", "true").lower() == "true"


def remote_timeout_for(operation: str) -> int:
    """Wall-clock budget for one offloaded batch: the same local budget, plus room
    for sandbox lifecycle and transfer."""
    return timeout_for(operation) + DAYTONA_OVERHEAD_SECONDS
```

Add the `daytona` dependency to `backend/pyproject.toml` — pin whatever version step 0
above was verified against, not blindly "newest." Add all the vars above to
`.env.example` under `# --- Daytona offload (optional; unset = everything runs on the VPS) ---`,
and to `backend.environment` in `docker-compose.yml` as `${VAR:-default}`, matching every
other optional knob in that file.

## 3. `backend/app/services/progress.py` — `Publisher.batch()`

This is needed **now**, not deferred to Phase 4's sharding — even a single sandbox's
relayed progress can't go through the existing `file()`/`step()`/`percent()` methods,
because those recompute an overall percentage from *this process's own* `_index`/`_total`
via `_overall()` (`progress.py:257`), and the number that needs relaying here is one
`remote_job.py` **already folded** inside the sandbox. Recomputing it a second time through
different index/total bookkeeping would double-apply the fold. One new method sidesteps
that entirely:

```python
def batch(self, *, done: float, total: int, index: int, name: str, step: str) -> None:
    """Set an already-computed fraction directly, bypassing _overall().

    `done` and `total` are in "whole files" — done=2.4/total=5 is 48%. `index`
    and `name`/`step` only drive the detail line ("File {index} of {total} —
    {name}"); they don't have to be in lockstep with done/total's arithmetic,
    which is what makes this reusable for both a single relayed shard (Phase 2)
    and a fold across several (Phase 4).
    """
    self._index = index
    self._total = total
    self._name = name
    self._step = step
    self._percent = self._monotonic(round(done / total * 100, 1))
    self._emit(RUNNING)
```

No new state needed — `_index`/`_total`/`_name`/`_step`/`_percent` are already in
`Publisher.__slots__` (`progress.py:235`). `NullPublisher` inherits it for free, since it
overrides only `_emit`. Every existing call path (`file`/`step`/`percent`) is untouched —
this is a pure addition.

**Translating one shard's stderr frame into a call**: a `remote_job.py` frame is
`{"file": i, "total": n, "name": …, "step": …, "percent": p}`, where `p` is already the
sandbox's own overall fold across its `n` files. For a single sandbox handling the whole
batch (this phase — no sharding yet), `n` equals `len(batch.files)`, so the relay is a
direct pass-through:

```python
publisher.batch(done=(frame["percent"] or 0) / 100 * frame["total"], total=frame["total"],
                 index=frame["file"], name=frame["name"], step=frame["step"])
```

which reproduces `frame["percent"]` exactly (division and multiplication by the same
`total` cancel), while going through the one code path (`batch()`) that Phase 4 will reuse
unchanged when `n` is a shard's file count rather than the whole batch's.

## 4. `backend/app/services/offload.py` (new) — the orchestrator

```python
async def maybe_offload(operation: str, batch: UploadBatch, options: dict) -> list[OutputFile] | None
```

Returns `None` when the caller should run locally — the three-line head each batch driver
gains (§6) falls through to its existing loop untouched in that case.

**`SandboxPool` protocol** — everything Daytona-specific sits behind this, so nothing else
in the codebase imports `daytona`:

```python
class SandboxPool(Protocol):
    async def provision(self) -> str: ...                       # -> sandbox id
    async def put(self, sandbox_id: str, path: str, data: bytes) -> None: ...
    async def run(self, sandbox_id: str, command: str, *, cwd: str,
                  env: dict[str, str], on_line: Callable[[str, str], None]) -> int: ...  # -> exit code
    async def get(self, sandbox_id: str, path: str) -> bytes: ...
    async def dispose(self, sandbox_id: str) -> None: ...
```

`on_line` receives `("stdout" | "stderr", line)` per line, the same shape `runner.OnLine`
already uses (`runner.py`) — deliberately, so the callback-handling code in `offload.py`
reads like the callback-handling code every other service already has.

**`_DaytonaPool`** implements this over the `daytona` SDK verified in step 0: `provision`
creates from `config.DAYTONA_SNAPSHOT` with `ephemeral=True`,
`auto_stop_interval=config.DAYTONA_AUTO_STOP_MINUTES`,
`ttl_minutes=config.DAYTONA_TTL_MINUTES`, and a label `{"app": "pdfkit", "job": job_id}`
(consumed by Phase 5's orphan sweep, inert until then); `put`/`get` are the toolbox
upload/download calls Phase 0's spike already proved work
(`files/upload-v2`/`files/download`); `run` opens a session, execs, and streams logs via
whatever step 0 confirmed, calling `on_line` per frame; `dispose` deletes the sandbox.

**Flow for one request** (single sandbox — this phase, no sharding):

1. **Decision gate** — all of: `config.DAYTONA_ENABLED`; `operation in
   config.DAYTONA_OPERATIONS`; `len(batch.files) >= config.DAYTONA_MIN_FILES`; `sum(f.size
   for f in batch.files) >= config.DAYTONA_MIN_BYTES`. Any false → return `None` before
   touching Daytona at all.
2. Provision one sandbox (`config.DAYTONA_PROVISION_TIMEOUT_SECONDS` ceiling).
3. Tar `backend/app/` in memory (~200 KB; Phase 0 measured the round trip for this shape
   at 50 ms), `put` it to `/work/app.tgz`, `run("mkdir -p /app && tar xzf /work/app.tgz -C
   /app")`.
4. `put` each input file plus a generated `spec.json` (per Phase 1's format — see
   `backend/tests/test_remote_job.py::write_spec` for the exact shape) under `/work`.
5. `run("/opt/venv/bin/python -m app.tools.remote_job /work/spec.json", cwd="/app", env=
   {"MAX_CONCURRENT_JOBS": str(config.DAYTONA_SANDBOX_CPU)}, on_line=...)`, timeout
   `config.remote_timeout_for(operation)`. The `on_line` callback: stdout lines are parsed
   as the per-file result contract (§ below); stderr lines are parsed as progress frames
   and relayed via `Publisher.batch()` (§3) — both **non-blocking**, per the plan's own
   warning that a blocking Python callback can drop the log stream: parse JSON, update
   state, return, nothing else.
6. On each **stdout** `status: "ok"` line: `get` the named output file, write it to a local
   temp path, build an `OutputFile`. On a `status: "error"` line: raise
   `HTTPException(status_code=line["http_status"], detail=line["detail"])` **immediately**
   — this is a real document error (an encrypted PDF, say), not an infrastructure failure,
   and must surface exactly as the local path would (`ensure_readable` raises 422
   `password_required`, verbatim per Phase 1). It must **never** trigger a local-fallback
   retry — retrying an encrypted file locally would just fail identically, having also
   burned the sandbox round trip.
7. `finally`: always dispose the sandbox, wrapped in
   `asyncio.shield(asyncio.wait_for(dispose(...), 20))` — an unshielded delete gets
   cancelled by the very cancellation that might have triggered it.

**Fallback rule**: any `DaytonaError`, rate-limit error, provisioning timeout, or shim exit
1 (`remote_job`'s "could not run at all") **before any file's result line has appeared on
stdout** → log it, dispose, return `None` — the caller's three-line head falls through to
the local loop as if offload had never been attempted. Once at least one result line has
appeared, no more silent fallback: a connection loss mid-batch after partial progress
raises `HTTPException(502, "remote_job_interrupted")` rather than quietly re-running
(possibly billed) work locally and duplicating whatever the client already saw. Gated by
`config.DAYTONA_FALLBACK_LOCAL` (default `true`) — with it `false`, any Daytona failure at
all is a hard error instead of a silent local retry, useful for isolating whether a given
failure is Daytona-side during rollout.

**Cancellation**: a watchdog task polls `progress.client_gone()` every 2 s while the exec
runs; on `True`, cancel the exec task (`dispose()` still runs under the shield in `finally`)
and raise `HTTPException(499, progress.CANCELLED)` — the same status the local path raises
from `progress.stop_if_cancelled()` (`progress.py:387`), just coarser-grained (~2 s instead
of per-file, since there is no per-file boundary to check between on the VPS side of a
sandboxed batch).

**Concurrency**: remote work must never touch `runner._slots` — that semaphore protects
the VPS, and a remote batch holds zero VPS job slots by design. `offload.py` gets its own,
built lazily rather than at import (import-time binding is exactly what made `_slots`
awkward to test, per `CLAUDE.md`):

```python
_remote_slots: asyncio.Semaphore | None = None  # rebuilt if config.DAYTONA_MAX_SANDBOXES changes
```

This phase only ever provisions one sandbox per offloaded request, so the ceiling simply
bounds how many requests can be offloaded concurrently — its real job (bounding sandboxes
*within* one request) starts in Phase 4.

## 5. `backend/app/services/ocr.py` — pin `--jobs`, don't let it guess

`ocr_to_path`'s `ocrmypdf` invocation (`ocr.py:234`) never passes `--jobs`, so OCRmyPDF
auto-sizes its own page-parallelism from the process's own view of available cores — which
Phase 0 found reports **48 inside a Daytona sandbox with a real 4-CPU quota**. Untested at
the 6-page scale that spike used (OCRmyPDF caps jobs at page count, so 6 pages never
reaches 48), but a 50-page scan is exactly the case this feature exists for, and 48 workers
thrashing inside a 4-core cgroup would be the kind of self-inflicted slowdown that could
erase the 2.6–3.7× win Phase 0 measured.

Fix at the source, once, since `to_word_one`/`to_markdown_one` share this same function for
their own OCR sub-step (`ocr.py`'s own docstring: "the tools that need a readable document
before they can do their real job... get exactly the same behaviour"), so Phase 3's Word
and Markdown offloading inherit the fix automatically:

```python
"ocrmypdf",
"-l", "+".join(languages),
"--jobs", str(config.MAX_CONCURRENT_JOBS),
...
```

`config.MAX_CONCURRENT_JOBS` is read at call time (already true — it's referenced inside a
function body, not bound at import), and is exactly the right number in both places it
runs: locally it already matches the VPS's real job-concurrency ceiling; inside a sandbox,
Phase 1 already sets that same env var to the sandbox's own vCPU count before exec'ing the
shim (`remote_job.py`'s docstring, `runner._slots` sizing) — so this reuses infrastructure
that already exists rather than inventing a second knob.

## 6. `backend/app/services/ocr.py` — the three-line head

```python
async def ocr(batch: UploadBatch, languages: list[str]) -> list[OutputFile]:
    if (offloaded := await offload.maybe_offload("ocr", batch, {"languages": languages})) is not None:
        return offloaded
    workspace = batch.workspace("out")
    ...  # unchanged
```

`compress.py`/`word.py`/`markdown.py` are untouched in this phase — their drivers gain the
identical head in Phase 3.

## Explicitly out of scope for this phase

- `compress.compress` / `word.to_word` / `markdown.to_markdown` offload heads (Phase 3).
- Sharding into more than one sandbox per request, and the `FanIn` fold (Phase 4) —
  `Publisher.batch()` exists now, but nothing calls it more than once per batch yet.
- Orphan sweep on startup, `snapshot.yml` CI automation, weekly warm cron (Phase 5).
- Flipping `DAYTONA_ENABLED=true` in the real Coolify environment (Phase 5) — this phase
  ships with it `false` by default; only manual local/VPS testing runs it `true`.

## Testing

`backend/tests/test_offload.py` (new), fully offline, no `DAYTONA_API_KEY` required for the
default run:

- `FakeSandboxPool` implementing `SandboxPool` over a tmpdir, reusing
  `tests/test_remote_job.py::run_remote_job` to "exec" the shim as a real local subprocess
  — per that function's own docstring, which already names this as its intended reuse.
  `put`/`get` are file copies; `provision`/`dispose` are directory create/remove.
- Decision-matrix tests: `DAYTONA_ENABLED=False` → `None` without touching the pool;
  `operation not in DAYTONA_OPERATIONS` → `None`; below `DAYTONA_MIN_FILES` → `None`; below
  `DAYTONA_MIN_BYTES` → `None`. All via `monkeypatch.setattr(config, "DAYTONA_...", ...)`,
  which only works because these are read at call time (§2) — the same reason
  `monkeypatch` on `config` is silently useless against an imported name elsewhere in this
  codebase, per `CLAUDE.md`.
- Error round-trip: an encrypted fixture through the fake pool → the real `HTTPException`
  (422, `password_required`) surfaces from `maybe_offload`, and — this is the important
  negative test — the caller does **not** fall back to local (assert the local loop never
  runs, e.g. via a monkeypatched sentinel the head would otherwise call), and `dispose()`
  still ran.
- Fallback: a `FakeSandboxPool.provision` that raises → `maybe_offload` returns `None`,
  `dispose()` was never called (nothing to dispose), and the caller's own local loop runs
  and produces a correct result — proving the fallback path is not just "returns None" but
  "produces the right file."
- Cancellation: a fake `client_gone()` that flips `True` mid-run → `HTTPException(499,
  ...)`, and `dispose()` was called exactly once.
- `Publisher.batch()` unit tests: monotonic clamp (a lower `done` after a higher one holds
  the higher value), and the pass-through identity from §3 (`done=percent/100*total,
  total=total` reproduces `percent`).
- One opt-in live test, `@pytest.mark.skipif(not os.getenv("DAYTONA_API_KEY"), reason=...)`,
  mirroring the existing `requires_qpdf`-style pattern: real OCR on `build_scanned_pdf()`
  through the real `_DaytonaPool` against the real `pdfkit-toolchain` snapshot.

## Verification

- `docker compose run --rm backend-tests` green with **no** `DAYTONA_*` env vars set —
  proves the local path is bit-identical to before this phase (`DAYTONA_ENABLED` defaults
  `false`, so every existing test exercises exactly the old code path).
- Manual matrix with `DAYTONA_ENABLED=true` and a real API key, against the real
  `pdfkit-toolchain` snapshot: OCR `sample-scanned.pdf` — output bytes match the local
  path's output, the SSE bar in the browser rises monotonically to 100 with no flicker, the
  download name is unchanged from the local path's.
- Error parity: an encrypted PDF through OCR returns 422 `password_required` identically
  whether `DAYTONA_ENABLED` is true or false.
- A deliberately wrong `DAYTONA_SNAPSHOT` name → the batch falls back to local and still
  returns a correct file (proves the fallback path end-to-end, not just in the fake-pool
  unit test).
- Cancel a real remote OCR run mid-batch → 499 in the client, and the Daytona dashboard
  shows the sandbox gone within seconds (well inside `DAYTONA_TTL_MINUTES`).
- Watch Hostinger CPU (`df`/`top`/the existing monitoring) during a real offloaded OCR run
  on a multi-page scan — confirm the VPS itself stays near-idle for the duration, which is
  the actual point of the whole feature.
