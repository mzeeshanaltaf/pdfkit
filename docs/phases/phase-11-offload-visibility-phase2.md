# Phase 11 (part 2) — Offload visibility: gate logging and /health

## Goal

Close permanently the blind spot Phase 0 had to chase by hand over SSH: make
`eligible()` say *why* it refused, make the success path log too, and expose Daytona's
live posture on `/health` — so an operator can answer "did that offload, and if not which
gate refused" from one curl and one log grep, without SSH.

## Prerequisites

Phase 0's finding (`docs/phases/phase-11-offload-visibility-phase0.md`) — this phase is
the permanent fix for the invisible-gate case that spike diagnosed by hand. Phase 1
(`docs/phases/phase-11-offload-visibility-phase1.md`) is not a hard dependency for the
code in this phase, but its pill is what the end-to-end verification below watches for.

## 1. `eligible()` says why

Return the reason rather than a bare bool — a small `_Refusal` string or `None` — and
have `maybe_offload` log one INFO naming the failing gate and its configured value:

```
offload skipped for ocr: 3 files is under DAYTONA_MIN_FILES=4
```

Every gate, including `disabled`.

## 2. The success path says so too

One INFO in `_offload` (`offload.py:310`):

```
offloading 3 file(s) of ocr across 2 sandbox(es)
```

Today a working feature logs nothing but incidental `remote_job:` relay lines.

## 3. `/health` reports the live Daytona posture

Extend the dict at `main.py:117-129` with a `daytona` block: `enabled`, `api_key` (bool —
never the value), `snapshot`, `operations`, `min_files`, `min_bytes`, `max_sandboxes`,
alongside the existing `sandboxes` counter. All read through `config.X` at call time —
this is the endpoint that would have answered Phase 0's question in five seconds.

## Explicitly out of scope for this phase

- Persisting any of this to Postgres or the admin dashboard — that's Phases 3 and 4.
- Anything about *where a job ran* beyond a log line — that's Phase 1's `placement.py`
  and the response header.

## Files

**Backend** — `app/services/offload.py` (`eligible`, `maybe_offload`, `_offload`),
`app/main.py` (`/health`).

## Testing

Extend `backend/tests/test_offload.py`:

- `eligible()` names each failing gate, including `disabled`.
- The success-path INFO log fires with the right file count and sandbox count.

## Verification

1. `docker compose run --rm --build backend-tests` green.
2. `curl https://api.pdfkit.zeeshanai.cloud/health | jq .daytona` shows `enabled: true`,
   the real snapshot name, and the thresholds.
3. Upload a single small file to OCR and confirm the log says `offload skipped for ocr: 1
   file is under DAYTONA_MIN_FILES=2`.
4. Integration check, tying this phase together with Phase 1's pill: run the 3-file / ~25
   MB OCR batch again and watch the sandbox pill appear (Phase 1), the bar stay monotone
   across both shards, the pill persist on the done screen, and `/health`'s `sandboxes`
   go 0 → 2 → 0.
5. Fallback honesty: set `DAYTONA_SNAPSHOT` to a name that does not exist, run the same
   batch, and confirm the file still comes back, no pill is shown, and the log names the
   provision failure rather than staying silent.
