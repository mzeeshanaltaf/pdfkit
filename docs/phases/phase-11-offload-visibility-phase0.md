# Phase 11 (part 0) — Offload visibility: diagnosis spike

## Goal

Before writing any code, answer one question over SSH: **why did a 3-file / ~25 MB OCR
batch appear not to offload**, and which of four possible causes it actually was. This
phase produces a finding recorded in `STATUS.md`, not shipped code — later phases may
change based on what it finds (a one-variable Coolify fix should not wait for a deploy).

## Prerequisites

None from the codebase. Needs SSH access to the VPS (`76.13.7.106`,
`~/.ssh/hostinger_vps_ed25519`) and `docker` access to the running backend container.
Phase 10 (`docs/phases/phase-10-daytona-sandbox-offloading-phase5.md`) must already be
live — `DAYTONA_ENABLED=true` is now set in Coolify, so Phase 10's sandbox offloading is
in production for the first time.

## Context

It shipped deliberately dark, and therefore shipped **silent**: nothing in the UI, the
logs, `/health`, or the admin dashboard says whether a given batch ran on the VPS or in a
sandbox. Four consequences, all reported from the first real day of use:

1. A user watching a long OCR has no way to know the work left the VPS.
2. A 3-file / ~25 MB OCR took 10–15 minutes and appears not to have offloaded — and
   **there is no way to tell from the outside whether it even tried**. `offload.eligible()`
   (`backend/app/services/offload.py:223-235`) returns `False` with no log line at all, and
   there is no log line on the success path either, so "ran locally because a gate said
   no" and "ran in a sandbox" look identical from a log tail.
3. Daytona's own spending dashboard is the only place sandbox usage is visible, and it
   lags real consumption by up to 48 hours.
4. The admin dashboard's "Browser vs server" split stops at "server" — it cannot say how
   much of that server work actually happened on the VPS.

This phase closes item 2 far enough to get an answer today, by hand, over SSH — the
permanent instrumentation for it is Phase 2 of this same effort
(`docs/phases/phase-11-offload-visibility-phase2.md`).

### The four candidate causes, and how to tell them apart

3 files at ~25 MB passes every threshold gate — `3 >= DAYTONA_MIN_FILES (2)`,
`26 MB >= DAYTONA_MIN_BYTES (5 MiB)`, and `ocr` is first in the default
`DAYTONA_OPERATIONS`. So the cause is one of four things, and the logs already
distinguish three of them:

| Evidence in the backend container log | Means |
|---|---|
| **no `orphan sweep:` line at boot** | `DAYTONA_ENABLED` is not `true` *in that process* — `main.py:44` never calls the sweep. The single cleanest tell. |
| `offload of ocr abandoned, falling back locally: provision failed: …` | It tried. **Leading suspect**: `DAYTONA_SNAPSHOT` was left at its default `pdfkit-toolchain` (`config.py:129`) instead of the CI content-hashed `pdfkit-toolchain-04701fea2e5e` that STATUS.md §"The one thing left on Phase 10" specifies. If the hand-built snapshot is gone, every provision fails and falls back silently. |
| `all 2 remote slots are busy; running ocr locally` | concurrency, not configuration |
| **none of the above, job just ran slowly** | `eligible()` refused — `DAYTONA_OPERATIONS` overridden, or the thresholds raised. This is the invisible case Phase 2's instrumentation closes. |

## What to do

1. `ssh -i ~/.ssh/hostinger_vps_ed25519 <user>@76.13.7.106`, find the running backend
   container.
2. `docker logs` grepped for `orphan sweep|abandoned|remote slots|remote_job:` — this
   alone answers three of the four rows above.
3. `docker inspect` the running container's resolved environment. Coolify's UI value and
   the running container's value can differ — `config.py` reads env **at import**, so a
   *restart* of a stale container keeps the old environment; only a redeploy changes it.
   Compare the running `DAYTONA_SNAPSHOT` against the CI-built name from `STATUS.md`.
4. `GET /sandbox?labels=…` against the Daytona API to check for stragglers left over from
   a failed or interrupted batch.

## Deliverable

A finding recorded in `STATUS.md`, covering:

- Which of the four rows in the table above actually explains the observed batch, with
  the log line or `docker inspect` output that proves it.
- Whether this is a one-variable Coolify fix (e.g. `DAYTONA_SNAPSHOT` pointing at a
  missing snapshot) to apply immediately, independent of the rest of this plan.
- Confirmation that nothing here changes the design of Phases 1–4 of this effort — the
  instrumentation they add closes this exact blind spot permanently, regardless of which
  row turns out to be the cause this time.

## Verification

- The cause is identified and written down in `STATUS.md` before any code in
  `docs/phases/phase-11-offload-visibility-phase1.md` is started.
- If the cause was a live-environment misconfiguration (not a code gap), it is fixed in
  Coolify and a follow-up batch is re-run to confirm the fix actually offloads —
  independent of, and not blocking, the rest of this plan.
