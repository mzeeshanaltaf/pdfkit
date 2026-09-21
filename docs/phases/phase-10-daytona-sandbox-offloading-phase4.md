# Phase 10 (part 4) — Daytona offload: sharding across N sandboxes

## Goal

Split a large offloaded batch across up to `DAYTONA_MAX_SANDBOXES` sandboxes running
concurrently, instead of Phase 2/3's one-sandbox-per-request, and fold their independent
progress streams into the single coherent bar the frontend already expects — with **no
frontend change**. This is where the parallelism Phase 0 confirmed is "free" (creating N
sandboxes costs the same wall clock as one) actually pays off for a 10–20 file batch.

## Prerequisites

Phase 2 and Phase 3 done — all four operations (`ocr`, `word`, `markdown`, `compress`) go
through `offload.maybe_offload()`, each currently provisioning exactly one sandbox for its
whole batch. `Publisher.batch()` (`progress.py`, added in Phase 2 §3) is what this phase's
fold is built on — read that section before this one; the formula here is a direct
extension of it, not a new mechanism.

## Context

Phase 0's account-level numbers (measured on a residential link, before the VPS-specific
spike): creating 2 sandboxes in parallel took the same **1.43 s** wall clock as creating
one. That is the entire economic basis for sharding — provisioning N sandboxes is not
N times the cost of one. **This specific claim was not re-verified in Phase 0's VPS spike**
(`backend/scripts/spike_offload.py` measured single-sandbox create→ready at 0.79 s from the
VPS, not N-in-parallel) — spot-check it early in this phase, on the real VPS link, before
building sharding logic on an assumption carried over from a different measurement session
on a different network path. If parallel create turns out not to be free from the VPS
specifically, sharding still works, it just costs more up front than this design assumes —
worth knowing before tuning `DAYTONA_MAX_SANDBOXES`.

## 1. Splitting a batch into shards

In `offload.py`, before provisioning: `shard_count = min(len(batch.files),
config.DAYTONA_MAX_SANDBOXES)`. A batch that already fails `DAYTONA_MIN_FILES` never
reaches this — the decision gate from Phase 2 is unchanged and runs first. Split
`batch.files` into `shard_count` roughly-even, contiguous slices (file order matters for
the "File {index} of {total}" detail line the frontend renders, so keep the original
ordering visible across shards rather than round-robin-interleaving them — e.g. shard 0
gets the first files, shard 1 the next chunk, and so on).

Provision all shards' sandboxes **concurrently** (`asyncio.gather`) — this is the
"provisioning is free" premise from Context above, and is also what Phase 0's account-level
numbers found true for 2-in-parallel specifically; re-verify at whatever
`DAYTONA_MAX_SANDBOXES` default (2) ships with here, since that is the only shard count
this phase's own testing will actually exercise live.

Each shard gets its own `spec.json` (a subset of the batch's files, same `operation`/
`options` as the whole batch — `remote_job.py` needs no changes for this, since it already
just processes whatever `files` list its spec names) and its own upload/exec/download
sequence, run **concurrently** across shards via `asyncio.gather`. A single shard's
`_run_compress`-style exec is otherwise identical to Phase 2/3's single-sandbox flow —
sharding only changes how many of those flows run at once and how their results are
recombined, not what each one does.

## 2. `FanIn` — folding N shards' progress into one bar

Each shard's stderr frame is still `{"file": i, "total": n, "name": …, "step": …,
"percent": p}`, exactly as Phase 2 §3 described — but now `n` is that **shard's own** file
count (a subset of the batch), not the whole batch's, and `p` is that shard's own overall
fold. Naively relaying one shard's `p` through `Publisher.batch()` the way Phase 2 does for
a single sandbox would make the bar thrash between shards' independent 0–100 ranges and
`_monotonic`'s clamp would freeze it at whichever shard happened to reach the highest
percentage first — exactly the failure mode the original design's "Progress fidelity" notes
called out.

`offload.FanIn` fixes this by working in **per-file fractions**, which are shard-size
independent:

```python
class FanIn:
    def __init__(self, total_files: int) -> None:
        self._fractions: dict[str, float] = {}  # file key -> 0..1, this file's own completion
        self._total = total_files
        self._shard0_name = ""
        self._shard0_step = ""

    def update(self, shard_index: int, frame: dict) -> None:
        # Back out this file's own 0..1 fraction from the shard's own fold:
        # frame["percent"] is (done_in_shard + this_file_fraction) / shard_total * 100.
        shard_total = frame["total"]
        done_before_this_file = frame["file"] - 1
        fraction = max(0.0, (frame["percent"] or 0) / 100 * shard_total - done_before_this_file)
        self._fractions[f"{shard_index}:{frame['file']}"] = min(1.0, fraction)
        if shard_index == 0:
            self._shard0_name = frame["name"]
            self._shard0_step = frame["step"]

    def publish(self, publisher: Publisher) -> None:
        done = sum(self._fractions.values())
        publisher.batch(
            done=done, total=self._total,
            index=min(int(done) + 1, self._total),
            name=self._shard0_name, step=self._shard0_step,
        )
```

`done = sum(fractions)` is monotonic by construction — no file's fraction ever decreases
once written, since `remote_job.py`'s own `_percent` is itself monotonic within a shard
(`Publisher._monotonic`), and each `(shard_index, file)` key is written by exactly one
shard. The detail line tracks shard 0's current file and changes only at that shard's own
file-completion cadence, which is why the frontend needs **no change at all** — it already
just renders whatever `name`/`step`/`percent`/`index`/`total` the SSE stream carries, and
`Publisher.batch()` (Phase 2) already emits through the exact same `Snapshot`/channel path
every other progress call uses.

Call `FanIn.publish()` from each shard's `on_line` callback after every stderr frame,
throttled the same way `runner`'s own `_threaded_reporter` throttles rapid updates — every
frame does not need its own SSE publish, just often enough that the bar reads as live.

## 3. Recombining results, and what a partial-shard failure means now

Each shard downloads its own `outputs` list (same per-file `status: "ok"`/`"error"` stdout
contract as a single sandbox, from Phase 2). Concatenate shards' outputs back into the
batch's **original file order** (not shard-completion order — a shard finishing later
should not reorder the final file list, since some downstream contracts, e.g. Compress's
`FileStat` list, zip against `batch.files` positionally).

The **fallback rule from Phase 2 gets stricter with N shards**: "any Daytona failure before
any file succeeded → return `None`" now means *any file across any shard* — a fast shard
finishing 3 files while a slow shard's sandbox is still provisioning does not itself block
fallback if the slow shard then fails to provision at all, but once **any** shard has
produced **any** result line, the whole-batch fallback-to-local path is off the table for
the same reason Phase 2 gave: local would duplicate already-billed, already-partially-
surfaced work. A shard that fails after that point (a lost connection mid-exec, say) raises
`HTTPException(502, "remote_job_interrupted")` for the whole request — there is no
partial-success return type in this design, and inventing "return N files done and error on
the rest" would be a client-facing contract change nothing in Phases 0–3 established. If
production data from Phase 5 shows partial-shard failures are common enough to matter,
that is a new decision to make with real numbers, not one to guess at here.

**Teardown**: every shard's sandbox gets its own `try/finally` + shielded `dispose()`
(Phase 2's guarantee, per-shard rather than per-request) — one shard's failure must not
leak another shard's sandbox. `asyncio.gather(..., return_exceptions=True)` across shards'
top-level tasks, so one shard raising doesn't cancel-and-orphan a sibling shard's own
disposal.

## Explicitly out of scope for this phase

- Orphan sweep, `snapshot.yml` CI automation, weekly warm cron, flipping
  `DAYTONA_ENABLED=true` in the real Coolify environment (Phase 5).
- A partial-success result contract (see §3) — deliberately not built speculatively.
- Per-shard resource sizing different from the flat `DAYTONA_SANDBOX_CPU`/`_MEMORY_GB`/
  `_DISK_GB` knobs — every shard gets the same size sandbox; there is no case yet for
  giving a shard with fewer/smaller files a smaller sandbox.

## Testing

Extend `backend/tests/test_offload.py`'s `FakeSandboxPool` to support multiple concurrent
"sandboxes" (multiple tmpdirs, each running its own `run_remote_job` subprocess) so shard
tests exercise real concurrent subprocesses, not a mocked-out `asyncio.gather`:

- A batch of 5 files with `DAYTONA_MAX_SANDBOXES=2` → confirm 2 shards, roughly 3/2 split,
  both provisioned and disposed, results recombined in original file order regardless of
  which shard finishes first (force one shard's fake subprocess to sleep before the other's
  so completion order is deterministic and reversed from file order — this is the test that
  would fail first if recombination is accidentally by completion order).
- `FanIn` unit tests, no subprocess involved: feed a scripted sequence of two shards'
  frames and assert `done` is monotonically non-decreasing across the whole sequence, and
  that the final `publish()` call reports `done == total` when both shards report 100%.
- A batch smaller than `DAYTONA_MAX_SANDBOXES` (e.g. 2 files, max 4 sandboxes) → confirm
  `shard_count == len(batch.files)`, not `DAYTONA_MAX_SANDBOXES` — no empty shards.
- Fallback-after-partial-success: one shard succeeds fully, the other's fake pool raises
  mid-exec → assert `HTTPException(502, ...)`, not a silent local retry, and that both
  shards' `dispose()` were called exactly once each.

## Verification

- `docker compose run --rm backend-tests` green, `DAYTONA_ENABLED` unset — no change to
  the local path from this phase either.
- Manual: a real 10-file OCR batch with `DAYTONA_ENABLED=true`, `DAYTONA_MAX_SANDBOXES=2`
  against the live account — confirm 2 sandboxes appear on the Daytona dashboard
  concurrently, both are gone within seconds of completion, and wall-clock time for the
  10-file batch is meaningfully less than the same batch through a single sandbox
  (Phase 2/3's behavior) — this is the actual payoff this phase exists to prove.
- Watch the SSE bar in the browser during that same 10-file sharded batch: confirm it rises
  smoothly to 100 with no visible backward jump or freeze, and that the file name/step text
  changes at a believable cadence rather than jumping erratically between unrelated
  files — the qualitative check that `FanIn`'s shard-0-tracks-the-detail-line design
  actually reads as coherent to a human, not just monotonic on paper.
- Confirm the parallel-create assumption from Context: time `DAYTONA_MAX_SANDBOXES`
  sandboxes created concurrently from the VPS and record the number in `STATUS.md` next to
  this phase's notes, the same way Phase 0 recorded its own numbers — if it is not
  "roughly the cost of one," say so plainly rather than letting the doc's original
  assumption stand uncorrected.
