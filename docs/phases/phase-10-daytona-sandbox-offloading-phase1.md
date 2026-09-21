# Phase 10 (part 1) — Daytona offload: `remote_job.py` shim, zero Daytona

## Goal

Build the sandbox-side shim that will eventually run inside a Daytona sandbox, and prove
it works end to end with a fake, in-process "sandbox" (a real local subprocess) — with
**no Daytona SDK, no config knobs, no network call anywhere in this phase.** Everything
here is testable offline in CI today, and is a pure addition: nothing existing is edited.

## Prerequisites

Phase 0 (`docs/phases/phase-10-daytona-sandbox-offloading-phase0.md`) has returned a
verdict that isn't "abandon the feature." This phase does not depend on Phase 0's actual
throughput number — it builds infrastructure that is useful regardless of the eventual
`DAYTONA_MIN_BYTES` value — but it should not be started if Phase 0 concluded the whole
approach is dead.

**Phase 0 ran on 2026-09-20 and returned GO** (full numbers in `STATUS.md`): 60 MB/s
median VPS↔Daytona throughput, 0.79 s create→ready, 50 ms for the `app/` tarball round
trip, and a Daytona core 2.62× a VPS core on OCR. One result changes this phase's work:
**`nproc` inside a sandbox reports the runner's cores, not the sandbox's quota** —
measured 48 against a 4-CPU `cpu.max`. So the `MAX_CONCURRENT_JOBS` env var described
under *Concurrency* below cannot be derived inside the sandbox from `os.cpu_count()`;
the orchestrator must pass the real figure in, and anything else that auto-sizes a
worker pool (notably `ocrmypdf --jobs`) needs pinning for the same reason.

## Context

The eventual feature moves CPU-heavy work (OCR, Compress, PDF→Word, PDF→Markdown) off the
shared Hostinger VPS into per-request Daytona sandboxes when enabled, falling back to the
existing local path on any failure. The full design lives in
`C:\Users\Zeeshan\.claude\plans\i-would-like-to-replicated-storm.md`; this phase builds
only its first slice: the code that will eventually run **inside** a sandbox, tested
**without** one.

Two later phases build the parts this one deliberately leaves out:

- Phase 2+: `backend/app/services/offload.py` (the local orchestrator — config knobs,
  the real `_DaytonaPool` backed by the `daytona` SDK, `maybe_offload()`, wiring into
  `ocr.ocr` first).
- Phase 4: sharding across N sandboxes and the `Publisher.batch()` progress fold for
  fan-in from parallel shards.

None of that exists yet after this phase, and that is intentional — this phase's own test
suite proves the shim is correct in isolation, before there is anything real to talk to it.

## What already exists that this phase follows the shape of

`backend/app/tools/` already has two shims that invoke a heavy operation as a standalone
process, launched as `[sys.executable, "-m", "app.tools.<name>", ...]`:

- `anydoc_cli.py` (PDF→Markdown): one JSON line per input on **stdout** as the result
  contract (`{"input":…, "status":…, …}`), progress on **stderr**, exit 0 means "the batch
  ran" (per-file failure is a status value, not a nonzero exit), exit 1 means "could not
  run at all."
- `pdf2docx_cli.py` (PDF→Word): same convention, plus a patch to pdf2docx's own word
  spacing.

`remote_job.py` is a third shim in the same family, structurally — same stdout/stderr
split, same exit-code meaning — but it dispatches to **four** existing service functions
instead of wrapping one library, and it runs a batch's worth of files described by a JSON
spec rather than argv, because per-operation options differ shape (`compress` takes
`level`; `word`/`markdown` take `ocr_mode` + `languages`).

The four functions it calls are the existing per-file service functions, unmodified:

| Operation | Per-file function | Batch driver (not touched by this phase) |
|---|---|---|
| `compress` | `compress_one` (`backend/app/services/compress.py:491`) | `compress` (`compress.py:564`) |
| `ocr` | `ocr_one` (`backend/app/services/ocr.py:271`) | `ocr` (`ocr.py:283`) |
| `word` | `to_word_one` (`backend/app/services/word.py:115`) | `to_word` (`word.py:157`) |
| `markdown` | `to_markdown_one` (`backend/app/services/markdown.py:224`) | `to_markdown` (`markdown.py:268`) |

The seam is at the **per-file** function, not the batch driver, and not `runner.run`
itself. `compress_one` alone fires ~20 subprocesses per file interleaved with
`asyncio.to_thread(streams.survey/rebuild)` and `fonts.subset` — pure-Python CPU work with
no argv, and no natural point to hand off to a remote call without either paying ~20 round
trips per file or leaving that CPU work on the VPS, defeating the point of offloading it.

## 1. `backend/app/tools/remote_job.py` (new)

Invoked as `/opt/venv/bin/python -m app.tools.remote_job /work/spec.json`, `cwd=/app`,
inside a Daytona sandbox in later phases — but in **this** phase it is invoked exactly the
same way from a plain local subprocess in tests, since it has no Daytona dependency at
all. Use the venv python by absolute path in the eventual sandbox invocation (this phase
doesn't need to hardcode that path anywhere in the shim itself — the caller decides how to
invoke `python -m app.tools.remote_job`, which is what makes it testable locally with a
plain `sys.executable`).

**Input** — `spec.json`, uploaded/placed alongside the files (in this phase: written to a
tmpdir by the test, since there is no real upload step yet):

```json
{
  "operation": "compress",
  "options": {"level": "recommended"},
  "files": [{"input": "a.pdf", "original_name": "a.pdf", "size": 123456}],
  "out_dir": "/work/out",
  "scratch_dir": "/work/scratch"
}
```

A JSON spec rather than argv, because `compress` takes `level` while `word`/`markdown`
take `ocr_mode` + `languages` — per-operation argv parsing would drift across the four
operations as options change.

**Work** — for each file: build a `SavedUpload` (`backend/app/deps.py:83`, fields `path`,
`original_name`, `size`) over the uploaded path, and call the operation's per-file
function from the table above (`compress_one`, `ocr_one`, `to_word_one`,
`to_markdown_one`) with the workspace/scratch directories from the spec. These are the
exact same functions the local path calls today — this phase adds a caller, not a new
implementation of any of the four operations.

**Concurrency** — when multiple files are in one spec, `MAX_CONCURRENT_JOBS` must be set
as an **environment variable on the process that runs the shim**, sized to that
container's own vCPU count. `runner._slots` is a module-level `asyncio.Semaphore` bound at
import time from `config.MAX_CONCURRENT_JOBS` (`backend/app/services/runner.py:43`) — this
is exploiting that import-time binding rather than fighting it: whatever process runs
`remote_job.py` gets its own correctly-sized semaphore for free, with zero code change to
`runner.py`. In this phase's tests, this just means the test harness sets the env var
before spawning the subprocess and can assert on it; there is no sandbox yet to size
around.

**Progress** — a `_StderrPublisher(progress.Publisher)`, built the same way
`NullPublisher` is (`backend/app/services/progress.py:321`): its own `__init__` setting up
the `Publisher.__slots__` state without a real channel, overriding only `_emit` to write
one JSON object per frame to **stderr**:

```json
{"pdfkit_progress": 1, "scope": "remote", "file": 1, "total": 3, "name": "a.pdf", "step": "Compressing", "percent": 42.0}
```

Bind it once via `progress.bind(...)` for the shim process's lifetime. This reuses the
existing stderr-JSON convention from `anydoc_cli.py`/the OCR progress plugin rather than
inventing a new one, and it means the *services* being called (`compress_one` etc.) need
zero changes — they already call `progress.current()` and publish through whatever
`Publisher` is bound. `stop_if_cancelled()` (called by the batch drivers, e.g.
`ocr.py:291`) is a no-op inside the shim in this phase — cancellation is a VPS-side
concern for the not-yet-built orchestrator, not something the shim itself decides.

**Result contract** (mirrors `anydoc_cli.py`'s, see table above): **exit 0 means the shim
ran** — one JSON line per file on stdout:

```json
{"input": "a.pdf", "status": "ok", "output": "a-compressed.pdf", "download_name": "a.pdf", "media_type": "application/pdf", "result_size": 98304}
```

or, on a per-file failure:

```json
{"input": "b.pdf", "status": "error", "http_status": 422, "detail": "encrypted_input"}
```

produced by catching `HTTPException` per file (the existing services already raise these —
e.g. `ensure_readable` in `backend/app/services/errors.py:40` raises 422 `encrypted_input`
for a locked PDF) and recording `status_code`/`detail` verbatim rather than re-deriving
them. **Exit 1 means the shim itself could not run** (e.g. the spec is malformed, or an
exception escapes that isn't an `HTTPException`) — an eventual orchestrator re-raises
`HTTPException(status_code=…, detail=…)` from the per-file line so error behaviour is
byte-identical to the local path; that orchestrator doesn't exist yet, so for this phase
the contract is proven directly by the test reading stdout, not by any caller consuming it.

`sanitise()` (used by `runner.run` today to scrub subprocess output before it reaches a
client) is not needed inside the shim for the fields on this JSON contract, since
`detail`/`status_code` come from `HTTPException`s the services already raise deliberately
for client consumption — there is no raw subprocess stderr being forwarded here that would
need scrubbing.

## 2. Tests: `backend/tests/test_remote_job.py` (new)

CI has no network and this phase adds nothing that needs one — `remote_job.py` only
imports existing service code and the standard library. Tests invoke it as a **real local
subprocess** (the same way `runner.run`/`_spawn` would, and the same way a sandbox
eventually will) against a tmpdir standing in for the sandbox's `/work`:

- **Round-trip contract**: write a `spec.json` for `compress` over `build_text_pdf()` (the
  existing `backend/tests/conftest.py` builder), run
  `python -m app.tools.remote_job spec.json` as a subprocess, assert exit 0, one stdout
  JSON line, `status: "ok"`, and that the named output file exists and is a valid,
  non-empty PDF.
- **Per-file error passthrough**: same, but with `encrypt_pdf(...)` (existing conftest
  builder) as the input for `compress` — assert the stdout line is
  `{"status": "error", "http_status": 422, "detail": "encrypted_input"}` and exit is still
  0, proving per-file failure is not conflated with "could not run."
- **Cannot-run path**: a malformed `spec.json` (missing `operation`, or an unknown
  operation string) — assert exit 1 and nothing meaningful on stdout.
- **Stderr progress contract**: for a multi-file spec, assert every stderr line parses as
  JSON, carries `"pdfkit_progress": 1`, and `percent` is monotonically non-decreasing
  within a given `file` index — the same shape check `anydoc_cli`'s progress lines get
  today (per `CLAUDE.md`'s note that `MARKER`/shape are kept in sync with
  `tests/test_shims.py`).
- **Per-operation smoke, one file each**: `ocr` on `build_scanned_pdf(pages=2)`, `word` on
  `build_text_pdf()`, `markdown` on `build_text_pdf()` — proving the dispatch table calls
  the right per-file function for all four operations, not just `compress`. Keep these
  minimal (one small file, default options) since the point is dispatch correctness, not
  re-testing each service's own behaviour, which already has its own test coverage
  elsewhere in `backend/tests/`.
- **`MAX_CONCURRENT_JOBS` env is honoured**: set it to `1` on the subprocess env for a
  multi-file spec and confirm the shim still completes correctly (a full concurrency-limit
  race test is unnecessary here — `runner._slots` behaviour is already covered by existing
  runner tests; this just confirms the shim's process actually reads the env var it's
  supposed to size itself from, by checking the semaphore's `_value` is what was requested
  immediately after import, e.g. via a tiny `-c` helper invocation rather than by racing
  real jobs).

All fixtures come from the **conftest builders** (`build_text_pdf`, `build_scanned_pdf`,
`build_photo_pdf`, `encrypt_pdf`) per `CLAUDE.md` — `backend/tests/conftest.py` generates
every PDF at run time by design; do not add a dependency on `frontend/test-fixtures/`.

### Why this counts as "`FakeSandboxPool` tests" per the plan, without `offload.py` existing

The later orchestrator (`offload.py`, Phase 2+) defines a `SandboxPool` protocol
(`provision`, `put`, `run`, `get`, `dispose`) so its tests can inject a `FakeSandboxPool`
that "provisions" a tmpdir and "executes" the shim as a real local subprocess. This phase
does not need that protocol to exist yet — invoking `remote_job.py` directly as a
subprocess against a tmpdir **is** that fake, minus the class wrapper, since there is no
orchestrator yet to inject it into. When Phase 2 introduces `offload.py` and the
`SandboxPool` protocol, its `FakeSandboxPool` should reuse this phase's subprocess-
invocation logic (move it into a small shared test helper if duplication would otherwise
creep in) rather than re-deriving it — the two are the same operation at different levels.

## Explicitly out of scope for this phase

- No `backend/app/services/offload.py`, no `SandboxPool` protocol, no `maybe_offload()`.
- No `daytona` dependency in `backend/pyproject.toml`.
- No config knobs (`DAYTONA_*`) in `backend/app/config.py`.
- No changes to `ocr.py` / `compress.py` / `word.py` / `markdown.py` — their batch drivers
  are not touched until Phase 2 wires in `maybe_offload()`.
- No `Publisher.batch()` — that is additive in a later phase once sharding (Phase 4)
  needs to fold progress across parallel shards; a single shim process in this phase never
  needs it.
- No Dockerfile `toolchain` stage, no snapshot build workflow.

If any of these start to feel necessary to finish this phase cleanly, that's a signal the
phase boundary needs revisiting, not a reason to reach ahead — Phase 2 already exists for
exactly that reason once Phase 1 has been proven.

## Verification

- `docker compose run --rm backend-tests` — full suite green, including the new
  `tests/test_remote_job.py`, with no `DAYTONA_*` env vars set anywhere (there are none to
  set yet) and no network access — proving this phase is entirely self-contained.
- Manually run `python -m app.tools.remote_job spec.json` once by hand inside the backend
  container (`docker compose exec backend ...`) against a spec built from a fixture PDF,
  confirm the stdout/stderr shapes match the contract above by eye, not just by the
  assertions.
- `sanitise()` is not on the hot path for the JSON contract, so it doesn't need a
  dedicated test in this phase — confirm this is still true by re-reading the fields
  every `HTTPException` in the four per-file functions actually carries (they are, by
  construction, values already meant to reach a client).
- Confirm nothing outside `backend/app/tools/remote_job.py` and
  `backend/tests/test_remote_job.py` changed — `git diff --stat` should show exactly those
  two new files (plus `STATUS.md` at session end), proving the "pure addition, nothing
  existing edited" claim in the Goal section actually holds.
