# Phase 11 (part 1) — Offload visibility: placement travels with the run

## Goal

One idea, reused three times: **the request knows where it ran, and that fact reaches
the live progress bar, the response header, and (in Phase 4) the stats row.** This phase
builds the one source of truth for "server or sandbox" and wires it through the backend
and frontend so the user sees it while a job runs and after it finishes.

## Prerequisites

Phase 10 complete and live (`DAYTONA_ENABLED=true` in Coolify). Read
`docs/phases/phase-11-offload-visibility-phase0.md`'s finding first — if it turned up a
live-environment bug (e.g. a missing `DAYTONA_SNAPSHOT`), fix that first so this phase's
manual verification actually exercises the sandbox path instead of only the fallback.

## 1. Backend — a new `app/services/placement.py`

A tiny module, modelled on `progress.py`'s `ContextVar` arrangement (and kept separate
from it because "where it ran" is not progress):

```python
SERVER = "server"
SANDBOX = "sandbox"
_placement: ContextVar[str] = ContextVar("pdfkit_placement", default=SERVER)

def current() -> str: ...
def mark_sandbox() -> None: ...
def mark_server() -> None: ...   # the honest revert on fallback
```

It lives in its own module rather than in `offload.py` because `responses.py` must read
it and `offload.py` already imports `responses.py` — importing back would be a cycle.

**Who sets it.** `offload.maybe_offload` only, and only in the *request task*:
`mark_sandbox()` right after `_claim` returns a non-zero shard count
(`offload.py:258-278`), and `mark_server()` in the `_Abandoned` handler at
`offload.py:282` before returning `None`. It must not be set inside `_run_shard` — those
are `gather` children with copied contexts, and a write there would not propagate back.

**Who reads it.**

- `progress.Publisher._emit` (`progress.py:245-255`) stamps
  `placement=placement.current()` onto every `Snapshot`. `Snapshot` gains the field
  (default `SERVER`) and `as_event()` gains `"placement"`. Every frame carries it for
  free, the bar corrects itself the moment a fallback happens, and `NullPublisher` needs
  no change because it only overrides `_emit`.
- `responses.file_response` (`responses.py:82-114`) stamps `X-Processed-On:
  server|sandbox` into `extra` for **every** backend response, single file and zip alike.
  One place, so no router can forget it — the same reasoning as `routers/__init__.py`'s
  dependency grouping.
- `main.py` adds `"X-Processed-On"` to CORS `expose_headers` (`main.py:62-67`), or the
  browser cannot read it cross-origin.

## 2. Frontend — no tool workspace needs editing

`ToolRunContext` (`frontend/components/tool/types.ts:58-72`) gains a
`setPlacement: (placement: ToolPlacement | null) => void`, following the precedent its
own `setDetail` docstring sets: a fourth setter, so the six browser-side tools need no
edit and never call it.

`backend-run.ts` does both halves:

- `ProgressState` (lines 16-21) gains `placement`; `render()` (58-66) calls
  `setPlacement(state.placement)` — this is the **live** signal, arriving with the first
  frame.
- after the upload resolves, `runBackendTool` (141-174) reads
  `response.headers["x-processed-on"]` and calls `setPlacement` again. The header is
  **authoritative**: progress is best-effort and may never connect, but a response that
  arrived definitely has the header.

`ToolShell` owns the state, which means it already has the value at each `recordRun` call
site (lines 164, 183, 202, 237) with no plumbing, and can pass it to both views. Reset it
to `null` alongside the other run state at `tool-shell.tsx:146-151`.

`unlock-workspace.tsx` calls `uploadWithPassword` directly rather than `runBackendTool`,
so it needs **one line** to read the same header — otherwise Unlock runs record `null`
and under-count the VPS side of the split (Phase 4's admin panel).

## 3. What the user sees

- **`processing-view.tsx`** — a small pill under the stage line, rendered only when
  `placement === "sandbox"`: a `Cloud` icon (lucide, already a dependency) plus *"Running
  in a secure cloud sandbox"*. Nothing at all for `"server"`: the VPS is the unremarkable
  default and a badge for it would be noise on ten of the twelve tools. Placed between the
  detail line and the Cancel button so the block above the bar does not move.
- **`result-view.tsx`** — the same pill, past tense (*"Processed in a secure cloud
  sandbox"*), under the `{tool.name} is done` heading, so the fact survives a run that
  finished before the user looked at the screen.

Both are one small shared component, `frontend/components/tool/placement-badge.tsx`.

## Explicitly out of scope for this phase

- Naming *why* a job didn't offload (gate reasons, `/health`, logging) — that's Phase 2
  (`docs/phases/phase-11-offload-visibility-phase2.md`).
- Persisting placement anywhere (Postgres, admin dashboard) — that's Phases 3 and 4.

## Files

**Backend** — `app/services/placement.py` (new), `app/services/offload.py`
(`maybe_offload`), `app/services/progress.py` (`Snapshot`, `Publisher._emit`),
`app/services/responses.py` (`file_response`), `app/main.py` (CORS `expose_headers`).

**Frontend** — `components/tool/{types,backend-run,tool-shell,processing-view,result-view}.tsx`,
`components/tool/placement-badge.tsx` (new), `components/tools/unlock/unlock-workspace.tsx`
(one line).

## Testing

Extend `backend/tests/test_offload.py` and `backend/tests/test_progress.py`:

- `test_offload.py` — placement is `sandbox` on the offloaded path and reverts to
  `server` after an `_Abandoned` fallback (the test that would catch a badge that lies).
- `test_progress.py` — `as_event()` carries `placement`.
- A response-header test per operation, asserting `X-Processed-On` on both the
  single-file and zip responses.

## Verification

1. `docker compose run --rm --build backend-tests` green.
2. Run the 3-file / ~25 MB OCR batch from Phase 0 again (with whatever Phase 0 fixed
   already applied) and watch the sandbox pill appear on the processing view, the bar
   stay monotone across shards, and the pill persist on the done screen in past tense.
3. Set `DAYTONA_SNAPSHOT` to a name that does not exist, run the same batch, and confirm
   the file still comes back, no pill is shown at any point, and
   `response.headers["x-processed-on"]` is `server`.
