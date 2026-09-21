# Phase 10 (part 0) — Daytona offload: measurement spike

## Goal

Answer one question before any offload code is written: **what is upload/download
throughput from the Hostinger VPS to Daytona?** Everything else about this feature —
whether it can work at all, which operations qualify, what `DAYTONA_MIN_BYTES` should be —
follows from that one number. This phase produces a throwaway script and a decision, not
shipped code.

## Prerequisites

None from the codebase — this phase touches no application file. It does need a Daytona
account and API key (`DAYTONA_API_KEY`), and SSH access to the VPS (`76.13.7.106`,
`~/.ssh/hostinger_vps_ed25519`) to run the spike from inside the running backend container,
per the note below on why it cannot run from a workstation.

## Context

PDFKit's backend runs on a Hostinger VPS (2 vCPU / 8 GB RAM) shared with 18+ other Coolify
apps. Twice, sustained 100% CPU triggered Hostinger's protective throttle (−25%/hour),
which threatens every service on the box, not just PDFKit. `MAX_CONCURRENT_JOBS=2` exists
to bound that risk, which in turn caps what a user uploading 10–20 large PDFs can get.

The eventual feature (built in later phases, not this one) is an **optional** path that
moves CPU-heavy work (OCR, Compress, PDF→Word, PDF→Markdown) off the VPS into per-request
Daytona sandboxes, falling back to the existing local path on any failure. Decisions
already taken for that design, which this spike either confirms or overturns:

- Per-job create + delete (no warm pool).
- Offload set is `ocr,compress,word,markdown` — Protect/Unlock/Images stay local
  (sub-second `qpdf` calls where a round trip would dominate).
- Toolchain-only snapshot with `app/` uploaded per sandbox, so service code can never go
  stale in the sandbox image.

### Measured latency so far (real, against the live account — from a residential workstation)

| Operation | Time |
|---|---|
| Create from a named pre-built snapshot → ready ← *what the design uses* | **1.06–1.63 s** |
| Create from default snapshot → ready | 1.2–1.6 s |
| Create from ad-hoc image pull (`python:3.12-slim`) — *not used* | 8.4 s |
| `snapshot.create` from a ~1 GB image — one-time, in CI, not per job | 27.3 s |
| Start from *stopped* (the warm-pool benefit) | 1.08 s |
| Stop / delete | 1.57 s / 0.68 s |
| 2 × create **in parallel** (wall clock) | **1.43 s** — fully parallel |
| Upload / download throughput | **~1.4–1.8 MB/s** *(residential workstation, NOT the VPS)* |

Three conclusions already follow from this:

1. **Provisioning is effectively free, and image size does not affect it.** Creating a
   sandbox from a *named* snapshot was 1.06–1.63 s even for a ~1 GB image — identical to
   the default snapshots — because Daytona pre-stages the snapshot at build time. The
   ~2 GB `pdfkit-toolchain` image is therefore paid once in CI (~30 s), never per job.
   Creating N sandboxes in parallel costs the same wall clock as one, so sharding is free.
2. **Per-job create + delete is confirmed correct.** A warm pool would save ~0.5 s
   (1.64 s cold vs 1.08 s warm) while incurring continuous disk billing and permanently
   occupying disk quota. It buys nothing.
3. **Sandbox lifecycle is not the risk — file transfer is, by an order of magnitude.** At
   1.4 MB/s a 50 MB PDF costs ~35 s up + ~35 s down. The entire feasibility of this
   feature rests on throughput **from the Hostinger VPS**, a datacenter link that should
   be far faster than the measured residential one. That is the number this phase exists
   to establish.

### Free-tier sizing (for reference, not this phase's job to change)

Two sandboxes at 4 vCPU / **8** GiB would exceed the account-wide 10 GiB RAM cap.
Daytona's own docs also disagree with themselves on Tier 1 RAM (the "Tiers" table says
10 GiB, the "Limits" table says 20 GiB twelve lines later). Current plan: **2 × (cpu=4,
memory=4, disk=10) = 8 vCPU / 8 GiB / 20 GiB** — fits the strict reading with headroom. If
OCRmyPDF OOMs on a 50 MB scan at 4 GiB, fall back to 1 × (4, 8, 10) and accept no
parallelism. Read live numbers off the Daytona dashboard rather than raising anything
speculatively.

## What to build

One throwaway file: `backend/scripts/spike_offload.py`. Not wired into the app, not
imported by anything, deleted once its answer is recorded (or moved to a `spikes/` dir if
the team wants to keep it — but it is not part of the shipped feature and later phases do
not depend on it existing).

**Run it from inside the running backend container on the VPS**, not from a workstation:

```
docker compose exec backend python scripts/spike_offload.py
```

The residential 1.4–1.8 MB/s figure above is known to be misleading — a datacenter link
should do much better — and the VPS number is the only one that matters for the go/no-go
call. The script is a short, low-CPU network test, so running it does not itself risk the
CPU throttle this feature exists to avoid.

### What to measure (×5 each, report min/median/max)

1. **Round-trip transfer of 5 MB / 25 MB / 50 MB payloads** to and from a Daytona sandbox
   — this is the decisive number the whole feature lives or dies on.
2. **App tarball upload + extract** — tar `backend/app/` in memory (~200 KB is the
   expected size), upload, `exec("mkdir -p /app && tar xzf ... -C /app")`, time the round
   trip. This is the fixed per-request overhead the real design pays on every job.
3. **Shim exec→exit for `compress` and for `ocr`** on a generated scanned PDF
   (`build_scanned_pdf(pages=2)`, same conftest builder pattern used by the backend test
   suite) run inside a 4 vCPU sandbox — i.e., is a Daytona sandbox actually faster than a
   VPS core for the same work, not just "does it complete." (Since `remote_job.py` does
   not exist yet in this phase, this can be a plain shell command / minimal Python script
   uploaded ad hoc for the spike — it does not need to match the real shim's contract.)
4. **Confirm real `pdfkit-toolchain` create→ready** matches the ~1.5 s measured with the
   probe/default snapshot in the table above. (If no `pdfkit-toolchain` snapshot exists
   yet, a comparably-sized ad-hoc image is an acceptable stand-in — the point is
   confirming image size doesn't matter, which is already suggested by the general-account
   numbers above.)

Compare end-to-end (compress/OCR one file) against the same operation run locally in the
same container, so the spike also produces a *speed*, not just a *transfer time*, verdict.

## Kill / reshape criteria

- **VPS throughput < ~5 MB/s → the feature is dead as designed.** A 50 MB file would spend
  20 s+ per direction in transit and no compute saving can repay that. Reshape to a
  small-file-only mode or abandon the feature.
- **5–20 MB/s → viable, but transfer-size gating carries the design.** `DAYTONA_MIN_BYTES`
  and per-operation gating (built in Phase 2+) become load-bearing, not just a
  cold-start-economics nicety. Prefer OCR first among the four candidate operations: it
  has by far the highest compute-per-byte ratio, so it repays transfer cost most easily.
  Compress is the marginal case (fast locally, and moves the same bytes either way).
- **> 20 MB/s → transfer is noise.** Offload freely and let `DAYTONA_MIN_FILES` be the
  only gate, not byte count.
- **A 4 vCPu sandbox not ≥ 2× a VPS core on the same file → the parallelism premise
  fails.** The feature is then only VPS-CPU protection, not a speed win — still worth
  shipping for the throttle protection, but the default thresholds and any user-facing
  copy about speed need to change accordingly.

Provisioning latency is already settled (~1.5 s, table above) and is **not** a kill
criterion for this phase — do not re-spend time re-measuring it in detail; a single
confirmation run (item 4 above) is enough.

## Deliverable

Not code that ships — a decision, recorded in `STATUS.md`, covering:

- The measured VPS→Daytona throughput (min/median/max across the three payload sizes) and
  which bucket above it falls into.
- Whether the 4 vCPU-sandbox-vs-VPS-core speed comparison supports the "offload = faster"
  claim, or only the "offload = protects the VPS" claim.
- Any resulting change to the plan in
  `docs/phases/phase-10-daytona-sandbox-offloading-phase1.md` and the not-yet-written later
  phases (e.g., a different default `DAYTONA_MIN_BYTES`, dropping Compress from the initial
  operation set, or — if throughput is under ~5 MB/s — pausing the feature entirely before
  Phase 1's code is built).
- Whether `pdfkit-toolchain` needs to exist as a real CI-built snapshot before Phase 2, or
  whether the default snapshot is good enough for early phases.

## Verification

- The spike script runs unattended inside the VPS container and prints a table: cold
  start, upload, exec, download, delete, each compared against the same operation's local
  wall clock, for payload sizes 5/25/50 MB.
- Hostinger CPU (via the existing monitoring, or a plain `docker stats`/`top` during the
  run) stays flat while the spike runs — confirming the measurement itself is not a repeat
  of the throttle incident.
- The go/no-go decision above is written down in `STATUS.md` before Phase 1 begins, since
  Phase 1 is only worth building if this phase didn't return a kill verdict.
