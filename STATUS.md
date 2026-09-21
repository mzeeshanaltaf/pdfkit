# Status

Last updated: 2026-09-21 (Phase 11 part 3 — offload visibility: sandbox telemetry)

## Current phase

**Phase 11 part 3 is code-complete and unit-tested, not yet verified live.**
Plan: `docs/phases/phase-11-offload-visibility-phase3.md`. Records PDFKit's own
sandbox telemetry — count, sandbox-time, CPU/RAM/disk-seconds, estimated cost —
in the stats Postgres, so the admin dashboard reports Daytona's own cost
immediately and per-operation instead of through Daytona's Spending dashboard,
which lags real consumption by up to 48 hours and has no per-operation
attribution at all. Daytona's public API has no cost or history endpoint (both
probed live and confirmed 404/401), so the approach is to reconstruct billing
from what PDFKit already knows: Daytona bills `resource × seconds alive`, and
`offload._run_shard` is the one place that knows a sandbox's whole lifetime.

**The backend has no database, so it POSTs fire-and-forget to a new Next
route** — `app/services/sandbox_stats.py`, modelled on `progress.py`'s
contract: it must never be able to fail a conversion. Disabled entirely unless
both `STATS_INGEST_URL` and `STATS_INGEST_SECRET` are set; every failure past
that point (a slow endpoint, a dead one, a bug in the module itself) is a
WARNING log line from a detached `asyncio.Task`, never a raise. `httpx` moved
from the dev group to the runtime dependencies in `pyproject.toml` — it was
already resolved as a transitive of `daytona`, so `uv lock` needed no network
access to re-resolve it, but relying on a transitive is exactly what breaks
silently on a pin bump.

**`offload._run_shard` now tracks each shard's own outcome and lifetime.** A
`provisioned_at` clock starts once `provision()` returns and stops just before
`dispose()` — the same window Daytona bills — and the `try/except` around
`_run_batch` now names the outcome as it unwinds: `_Abandoned` → `abandoned`,
an HTTPException with status 499 → `cancelled`, any other HTTPException →
`failed`, a bare `CancelledError` → `cancelled`, anything else → `failed`, and
falling through untouched → `ok`. Bytes up/down are **approximated** rather
than threaded through `pool.put`/`pool.get` as new counters: upload bytes come
from the batch's own upload sizes for that shard's file span, and download
bytes from the shim's own `result_size` field — the same number `_collect`
already verifies the download against. `cpu`/`memory_gb`/`disk_gb` are read
from `config.DAYTONA_SANDBOX_*`, which is what every sandbox this app creates
actually carries (Daytona fixes a snapshot's resources at build time and
rejects them on a per-sandbox create).

**The table** (`pdfkit.sandbox_runs`, in `frontend/lib/stats/{schema,schema.sql}.ts`)
stores the raw facts only — resource-seconds and cost are derived at query
time from `alive_seconds × cpu|memory_gb|disk_gb` in `queries.ts`, not stored,
so a rate change in `lib/stats/daytona-pricing.ts` (overridable by
`DAYTONA_PRICE_CPU_HOUR` / `_RAM_GB_HOUR` / `_DISK_GB_HOUR`) applies uniformly
instead of baking today's prices into old rows. The same migration pass adds
`tool_runs.placement` (Phase 4's column; this phase only ships the `alter
table ... add column if not exists`, since `create table if not exists` will
not add a column to an already-deployed table).

**The admin dashboard** gained a "Sandbox usage" section, above "Browser vs
server": six `StatTile`s (sandboxes, sandbox time, CPU/RAM/disk-hours, est.
cost), a by-operation horizontal-bar breakdown (`sandbox-usage.tsx`, the same
idiom as `tool-bar-list.tsx`), a "live now" quota strip from
`GET /organizations/{orgId}/usage` (`lib/stats/daytona-usage.ts`, server-side,
`cache: "no-store"`, a 5 s `AbortSignal.timeout`, and any failure renders the
strip as unavailable rather than failing the page — the org id comes from
`GET /api-keys/current`, cached per process), and a footnote naming the
estimate as an estimate with a link to Daytona's Spending page.

**No frontend test framework exists in this project** (confirmed: no
`vitest`/`jest` dependency, no `*.test.ts` file anywhere, and Phase 9's own
admin-dashboard work was verified the same way) — the plan's "route test for
`app/api/stats/sandbox/route.ts`" is therefore a manual-verification item
here, consistent with how every prior frontend-only change in this project has
been checked (curl / browser, not an automated suite), not a gap specific to
this phase.

Tests: 7 new in `test_offload.py` — the telemetry record's shape (sandbox id,
operation, `shard_total`, `file_count`, a non-negative `alive_seconds`, the
approximated bytes) through a real two-shard run; each of the four outcomes
(`ok` implicitly by the shape test, `failed` from a document error,
`abandoned` from an exit-1 shim, `cancelled` from both shards on a client
hangup); the feature staying off without both env vars, verified by making a
call to the real endpoint an `AssertionError`; and a broken POST target
producing only a WARNING log line, never a raise, awaited out via a few
`asyncio.sleep(0)` ticks since `record()` fires a detached task.

**Verified:** `uv run pytest -q` locally — **224 passed, 70 skipped**, same
skip set as every prior phase. `uv run ruff check` clean on every changed
file. `npx tsc --noEmit`, `npx eslint` and `npm run build` all clean on the
frontend (29 routes now, `/api/stats/sandbox` alongside `/api/stats/event`,
both dynamic). `docker compose config -q` validates the compose file.
**Not verified in this environment** (no Docker daemon available here):
`docker compose run --rm --build backend-tests` (the full toolchain image);
and everything the plan's own verification section needs a deployed
environment for — an OCR batch large enough to offload landing a row in
`pdfkit.sandbox_runs` with a plausible `alive_seconds`; the dashboard actually
rendering the new tiles/breakdown/live-now strip (or its degraded state);
cross-checking the estimated cost against Daytona's Spending page 48 hours
later; and `psql -c "\d pdfkit.sandbox_runs"` / `\d pdfkit.tool_runs` against a
database that already held rows before this phase.

### Still true from before this part — Phase 11 part 2, and everything before it

**Phase 11 part 2 is code-complete and unit-tested, not yet verified live.**
Plan: `docs/phases/phase-11-offload-visibility-phase2.md`. The permanent fix
for the blind spot part 0 chased by hand over SSH: `offload.eligible()` now
returns `str | None` instead of `bool` — `None` when every gate passes,
otherwise a reason naming the failing gate and its configured value (e.g.
`"3 files is under DAYTONA_MIN_FILES=4"`, singular for one file; `disabled`
reads as `"DAYTONA_ENABLED=false"`). `maybe_offload` logs that reason at INFO
(`offload skipped for ocr: ...`) instead of silently returning `None`, and
`_offload` gained a matching INFO on the success path (`offloading 3 file(s)
of ocr across 2 sandbox(es)`) — previously a working feature logged nothing
but incidental `remote_job:` relay lines. `/health` gained a `daytona` block
(`enabled`, `api_key` as a bool never the value, `snapshot`, `operations`,
`min_files`, `min_bytes`, `max_sandboxes`), alongside the existing
`sandboxes` counter, all read through `config.X` at call time like everything
else in this module.

`eligible()` had exactly one caller (`maybe_offload`, inside the same module),
so the signature change touched nothing else.

Tests: 5 new in `test_offload.py` (`eligible()` is `None` when every gate
passes; each of the four gates names itself and its configured value,
parametrized the same way `test_a_failed_gate_never_touches_the_pool` already
was; the singular "1 file" wording; `maybe_offload` logs the refusal via
`caplog`; the success path logs both counts), 3 new in `test_health.py` (the
full `daytona` block with every knob monkeypatched to a distinguishable
value; the API key coming back `false` when unset — the one field this
endpoint must never leak the real value of).

**Verified:** `uv run pytest -q` locally — **218 passed, 70 skipped**, same
skip set as every prior phase (ghostscript, qpdf, opt-in live Daytona tests
this dev machine lacks). `ruff check` clean on every changed file.
**Not verified:** `docker compose run --rm --build backend-tests` (the full
toolchain image) was not run in this environment. Also outstanding, all
needing a deployed environment per the plan's own verification section:
`curl .../health | jq .daytona` against production; a single-file OCR upload
confirming the exact skip log line; the end-to-end run tying this phase to
part 1's pill (bar monotone across shards, `/health`'s `sandboxes` going
0 → 2 → 0); and the fallback-honesty check with a bad `DAYTONA_SNAPSHOT`.

### Still true from before this part — Phase 11 parts 0-1, and Phase 10's go-live watch

**Phase 11 part 1 is code-complete and unit-tested, verification still
pending a deployed environment.** Plan:
`docs/phases/phase-11-offload-visibility-phase1.md`. Built the one source of
truth for "server or sandbox" (`app/services/placement.py`, a `ContextVar`
module modelled on `progress.py`) and wired it through:
`offload.maybe_offload` marks sandbox once a shard is claimed and reverts to
server in the `_Abandoned` fallback; `progress.Snapshot`/`Publisher._emit`
stamp `placement` onto every SSE frame (`Publisher.finish`'s frame too, which
is built outside `_emit` and would otherwise have reported "server" on the
very last frame of a sandboxed run — not in the plan's line range but needed
for the badge not to flicker just before done); `responses.file_response`
stamps `X-Processed-On` on every backend response; `main.py` exposes it over
CORS. Frontend: `ToolRunContext` gained `setPlacement`, `backend-run.ts`
relays it live from SSE and authoritatively from the response header,
`ToolShell` owns the state and resets it per run, `unlock-workspace.tsx`
reads the header itself (it bypasses `runBackendTool`), and a new shared
`placement-badge.tsx` renders a "secure cloud sandbox" pill on the processing
and done screens — nothing at all for the ordinary VPS path. No other tool
workspace needed an edit.

**Phase 11 part 0 is done, and the misconfiguration it found is fixed and
verified live — see that section below.** `DAYTONA_ENABLED` had been flipped
to `true` in Coolify at some point after Phase 10 part 5 shipped, without this
file being updated (the "shipped dark" claim below is stale). Every offload
attempt since was failing on `DaytonaAuthenticationError` because
`DAYTONA_API_KEY` was empty in Coolify's stored config, and `DAYTONA_SNAPSHOT`
was also still at its default rather than the CI-hashed name. Both are now
set correctly and a redeploy has picked them up; two real production batches
confirm sandboxes actually spin up and tear down now.

**Phase 10 part 5 is code-complete and verified live. The feature is shipped
dark: `DAYTONA_ENABLED` is still `false` in Coolify, and flipping it on is now
a one-variable change with nothing else outstanding.** The suite is **270
passed, 1 skipped** with no `DAYTONA_*` env vars set.

What this part added: a best-effort **orphan sweep** on startup (verified by
actually `SIGKILL`ing a backend mid-batch and watching the next boot clean up
after it), a **content-hashed CI snapshot pipeline**
(`.github/workflows/snapshot.yml`), a **snapshot-reactivation retry**, a
`sandboxes` counter on `/health`, and the docs the feature had none of.

**It also overturned part 4's headline finding.** Part 4 measured Compress as
a wall-clock *loss* with a break-even around 77 files. Re-measured from the
VPS on the real documents in `PDFKit Samples/`, Compress is **1.4x-1.7x
faster offloaded** (three runs, ±15% spread) and leaves the VPS **83-98%
idle** where a local run pegs both cores for three minutes. Part 4's number
was an artifact of its synthetic one-photo-page corpus, exactly as its own
caveat warned. **`compress` stays in `DAYTONA_OPERATIONS`.** See "Compress,
re-measured" below — including why a workstation run is not evidence either
way.

Parts 0-4 are done and written up below.

### The one thing left on Phase 10

**The go-live watch (part 5 §4).** The code is deployed but the flag is off, so
nothing is running in a sandbox yet. To start:

1. In Coolify, on the PDFKit resource: set `DAYTONA_API_KEY`, set
   `DAYTONA_SNAPSHOT=pdfkit-toolchain-04701fea2e5e` (the CI-named snapshot,
   already built and verified on the account), then `DAYTONA_ENABLED=true`.
   Leave every other `DAYTONA_*` at its default. Redeploy.
2. Watch `/health`'s `sandboxes` and `jobs`, and Hostinger CPU, across a few
   days of real traffic touching all four operations.
3. Anything wrong: `DAYTONA_ENABLED=false` and redeploy. One variable, no code
   change, and the local path it falls back to has been correct since Phase 0.
4. Once stable, revisit `DAYTONA_MIN_FILES` / `DAYTONA_MIN_BYTES` against the
   batch sizes real users actually send. The 5 MiB default is still the
   arbitrary number part 2 called it.

A **browser pass** is also still open from part 4 — Compress's done screen and
the SSE bar during a sharded batch, both of which need the flag on.

**Phase 9 (admin dashboard) is built and verified locally, not yet deployed.** PDFKit
itself is live at [pdfkit.zeeshanai.cloud](https://pdfkit.zeeshanai.cloud), API at
`api.pdfkit.zeeshanai.cloud`. See the root [`README.md`](README.md) for deploy notes
(domains, redeploy process, log locations).

Phase 8 shipped on 2026-09-20. The only thing left on it is a browser pass — see
"Left to do" at the end of the Phase 8 section.

## Phase 11 part 0 — offload visibility: diagnosis spike (2026-09-21)

Plan: `docs/phases/phase-11-offload-visibility-phase0.md`. No code changed —
this is the by-hand SSH diagnosis the plan asked for, answering why a 3-file /
~25 MB OCR batch appeared not to offload and took 10-15 minutes.

### Finding: it tried, and it fails auth — not the snapshot the table guessed

`DAYTONA_ENABLED` **is** `true` on the live container (`docker inspect`,
4 chars) — Phase 10 part 5's "shipped dark, flag is off" note is stale; someone
flipped it live without updating this file. The orphan sweep line is present
at every boot (rules out row 1), but it and every offload attempt since
carries the same WARNing:

    orphan sweep skipped (DaytonaAuthenticationError: Authentication
    credentials not found. Set DAYTONA_API_KEY, or both DAYTONA_JWT_TOKEN and
    DAYTONA_ORGANIZATION_ID. ...); relying on ephemeral + auto-stop + the
    30-minute TTL

    offload of ocr abandoned, falling back locally: provision failed:
    DaytonaAuthenticationError: ...
    offload of compress abandoned, falling back locally: provision failed:
    DaytonaAuthenticationError: ...   (5 occurrences, 05:57-07:09 UTC)

`docker inspect`'s resolved environment confirms it directly (values masked,
lengths shown): **`DAYTONA_API_KEY = <0 chars>`** — empty, not merely wrong.
That's row 2 of the diagnosis table, but not the row's own "leading suspect":
the plan guessed a stale `DAYTONA_SNAPSHOT` would be the culprit. It's wrong
too — still its 16-char default `pdfkit-toolchain`, not the 30-char
CI-hashed `pdfkit-toolchain-04701fea2e5e` the go-live checklist calls for —
but that's currently invisible, because auth fails before a snapshot is ever
looked up. Fixing the key alone will surface the snapshot problem next, not
fix offloading outright.

The Daytona account itself is clean: `GET /sandbox?labels={"app":"pdfkit"}`
returns zero sandboxes, so nothing is orphaned or quietly billing (also rules
out row 4 — the WARN lines above are proof it tried and failed loudly, not
proof of silence).

### Is this a one-variable Coolify fix?

No — two variables, and both need a **redeploy**, not a restart
(`config.py` reads env at import, per the plan's own note). `DAYTONA_API_KEY`
needs an actual value in Coolify (the running container is 2 hours old and
matches HEAD `9b6b66f`, so this is Coolify's current stored value, not a
stale pre-redeploy artifact), and `DAYTONA_SNAPSHOT` needs to be set to
`pdfkit-toolchain-04701fea2e5e`.

**Applied and verified live**, with the user's explicit go-ahead (this is a
production change: spends Daytona credits, changes what a real user's batch
runs on). Both vars set via the Coolify API (`PATCH
/api/v1/applications/b1s6cgebvkpxxrzzjp2d2244/envs`), then a redeploy
(`POST /api/v1/deploy`) to pick them up — `config.py` reads env at import, so
a restart alone would not have. The fresh container's `docker inspect` shows
`DAYTONA_API_KEY` non-empty and `DAYTONA_SNAPSHOT` at the full 29-char
CI-hashed name, and its boot log now reads
`orphan sweep: deleted 0 leftover sandbox(es)` at **INFO**, not the WARNING
auth failure from before.

Confirmed with two real batches against production
(`api.pdfkit.zeeshanai.cloud/ocr`, 2 files / ~10.7 MB from
`PDFKit Samples/Offloading Samples/OCR/`, clearing `DAYTONA_MIN_FILES=2` and
`DAYTONA_MIN_BYTES=5242880`): no `abandoned, falling back locally` line
appeared (100% of attempts before the fix had one), and polling `/health`
during the second run caught its `sandboxes` counter directly — `0 → 2 → 1 →
0` as the two-file batch sharded into two sandboxes, one finished, then both
tore down. Both batches returned `200` in ~105 s, against the 10-15 minutes
the original 3-file/25 MB batch took running entirely local. Nothing was left
running on the Daytona account afterwards.

### Confirms Phases 1-4 of this effort are unaffected

Every row in the diagnosis table was reachable purely from `docker logs` /
`docker inspect` / the Daytona API, by hand, today — exactly the blind spot
Phase 2's permanent instrumentation exists to close permanently. Nothing here
changes the design of Phases 1-4.

## Phase 10 part 5 — orphan sweep, CI snapshot builds, go-live (2026-09-21)

Plan: `docs/phases/phase-10-daytona-sandbox-offloading-phase5.md`. Everything
here is either startup-time or build-time; the request path is untouched apart
from two lines in `_DaytonaPool.provision` and a counter in `_run_shard`.

### 1. The orphan sweep — and `list()` really does work now

Parts 0-4 relied on three layers for teardown: the per-shard `try/finally`,
`ephemeral=True`, and `auto_stop_interval` + `ttl_minutes`. Real guarantees,
but all three live inside the process — and a Coolify redeploy `SIGKILL`s
uvicorn, which skips every `finally` there is. `offload.sweep_orphans()` is
the fourth layer: on startup, list everything carrying `{"app": "pdfkit"}` and
delete it. A fresh process owns nothing, so anything alive under that label
belongs to a process that is gone.

**Part 2 §0 flagged `list()` as unverified** — the previously-pinned SDK
`0.113.1` called a removed `/sandbox/paginated` endpoint and raised, and the
plan said to skip the sweep entirely if that was still true. **It is not:**
`daytona==0.214.0`'s `list()` works against the live API, and its
`ListSandboxesQuery(labels=...)` filter works too, which is what keeps the
sweep from ever touching a sandbox some other tool on the account owns. The
sweep ships.

It is best-effort by contract: everything is caught, and the log says which
way it went — `orphan sweep: deleted N` or `orphan sweep skipped (<error>);
relying on ephemeral + auto-stop + the N-minute TTL`. An operator should never
have to guess whether it ran. It is also bounded (`SWEEP_TIMEOUT_SECONDS = 30`)
so a hanging delete cannot hold startup open, and a single stuck sandbox does
not cost its siblings theirs.

**Verified live, twice over.** First against a hand-made orphan: 6/6, with the
sweep adding 0.7 s to startup and finding nothing on a clean account. Then the
real thing — a genuine offloaded OCR batch `SIGKILL`ed mid-flight:

    ORPHANED AFTER SIGKILL: ['06c11f8e-060e-4d8b-9eb0-c34af7132455']
    ... boot the backend, as a Coolify redeploy would ...
    found 1 sandbox(es) left over from a previous process: 06c11f8e-...
    orphan sweep: deleted 1 leftover sandbox(es) labelled {'app': 'pdfkit'}
    startup took 1.80s
    LABELLED SANDBOXES AFTER STARTUP: []

So the hole the plan identified is real, and it is closed.

### 2. The snapshot's name is its content

`pdfkit-toolchain` was hand-built once, by a person, and nothing could tell
from the running system that a `uv.lock` bump had made it stale.
`.github/workflows/snapshot.yml` replaces that. The name is a 12-hex digest of
`backend/Dockerfile` + `pyproject.toml` + `uv.lock` — application code
deliberately excluded, because `app/` is uploaded per job and that is the
whole reason a snapshot only goes stale when the *toolchain* moves.

The digest is computed by `scripts/build_snapshot.py --print-name`, **not by
shell in the workflow**, so a human rebuilding by hand and CI rebuilding on a
push cannot disagree about what to call the result. It normalises CRLF, which
matters: a Windows checkout and a Linux runner hold the same file with
different line endings and must not produce differently-named snapshots from
identical content. Confirmed — both print `pdfkit-toolchain-04701fea2e5e`.

Three new script modes, all exercised against the real account:

| | |
|---|---|
| `--print-name` | `pdfkit-toolchain-04701fea2e5e`, stable across runs, no API call |
| `--skip-existing` | second run on unchanged inputs: `already exists; nothing to build` |
| `--warm` | create + delete one sandbox, so Daytona does not deactivate it |

**The CI-named snapshot is built and verified on the account**: gs 10.00.0,
qpdf 11.3.0, 15 tesseract languages, ocrmypdf 17.12.1, and the 4-CPU quota
(`400000 100000`) the sandbox needs `MAX_CONCURRENT_JOBS` to know about.

**Nothing updates `DAYTONA_SNAPSHOT` automatically**, and the workflow's run
summary says so in as many words. A dependency bump that has not been
snapshotted should fail to create a sandbox and fall back to the VPS — which
`offload.py` already treats as an ordinary failure — rather than silently run
a toolchain that no longer matches its lockfile because a name pointing at
"latest" moved under a running deploy.

The weekly `schedule:` cron (Mon 04:00 UTC, clear of the VPS's own Sunday
Docker cleanup) runs `--warm`. Belt and braces at runtime too:
`_DaytonaPool.provision()` now recognises a "snapshot inactive"-shaped create
failure, calls `snapshot.activate()`, and retries **exactly once** — never a
loop, because the caller already has a good answer for a real failure. The
match is deliberately narrow (`"snapshot"` *and* an explicit not-active), so
"Snapshot not found" still falls straight through to the local path without
paying a second round trip.

`DAYTONA_API_KEY` is set as a repo secret, so the workflow can run.

### 3. Compress, re-measured — part 4's finding does not survive the VPS

Part 4 left this as a blocker: *"Phase 5 must measure Compress on
representative documents before flipping it on"*, having measured a 10-file
synthetic batch as 1.3 s local against 7.0 s offloaded and computed a
break-even around 77 files.

`verify_offload.py` grew a `--corpus-dir` for exactly this, so the harness can
measure the documents users actually upload instead of generated ones. Run
against `PDFKit Samples/` — a 50 MB insurance policy, a 15 MB one, a 4 MB
company profile, a 1.4 MB scan, a 108 KB certificate; 70.7 MB in five files:

**From the VPS — the only machine that serves production:**

| | |
|---|---|
| local (2 vCPU, `--jobs 2`) | **189.0 s** |
| offloaded (2 sandboxes, 4 vCPU each) | **109.2 s** and **131.5 s**, two runs |
| | **1.4x - 1.7x faster** |

Sandbox compute on this identical input measured **105.8 s, 129.3 s and
134.9 s** across three runs — about ±15% run to run, which is the honest
error bar on the speedup and is wider than any single pair suggests. The
conclusion survives the whole spread: even the slowest sandbox run plus the
VPS's 3.7 s of transfer beats 189 s of local Ghostscript. Only one local
baseline was taken, so it carries no error bar at all; treat 189 s as one
sample, not a constant.

**A workstation run is not a comparison, and is not presented as one.** The
same batch on an i7-14700K (20 cores, 64 GB) went 77.2 s local against
171.7 s offloaded — a number about *that desk*, not about whether offloading
helps the VPS. A 20-core CPU beating a 4 vCPU sandbox says nothing either
way, and 44.3 s of the offloaded run was a residential uplink pushing 70 MB.
The one thing it is evidence for is the link: **44.3 s from a workstation
against 3.7 s from the VPS for the same bytes**, which reproduces part 0's
~1.4 MB/s vs ~60 MB/s measurement exactly and is precisely why
`verify_offload.py`'s docstring refuses to let its verdict be believed from
anywhere but the VPS.

The practical corollary: **running the backend locally with
`DAYTONA_ENABLED=true` will look like a regression**, on this hardware
especially. That is correct behaviour, not a bug, and is one more reason the
flag defaults to false.

**And the CPU argument, which part 4 could not test, holds outright.** Sampling
`vmstat` on the VPS through an offloaded Compress of the same five documents:

    upload phase (~7 s)     0-54% idle   <- the VPS pushing 70 MB
    sandbox compute (120 s) 83-98% idle  <- typically 90%+
    download (~2 s)         13-44% idle

Against the ~190 s of both cores pegged that the local path costs, which is
precisely the shape of load that twice tripped Hostinger's throttle. This is
the argument that does not depend on the speedup being 1.4x or 1.7x, or on
its being a speedup at all: the VPS is idle either way.

**Conclusion: `compress` stays in `DAYTONA_OPERATIONS`.** Part 4's caveat was
right about itself — one synthetic photo page per file understates
Ghostscript's share of a real document's time, and that corpus would not even
have cleared `DAYTONA_MIN_BYTES` in production.

### 4. Smaller things

- **`/health` reports `sandboxes`** — a process-local counter, incremented and
  decremented in `_run_shard` (provider-agnostic, so the fake pools count too),
  never a Daytona round trip on a liveness endpoint. It is decremented whatever
  happens to the `dispose`, so it says how many sandboxes this process is
  *using*; one it failed to delete is the TTL's problem and the dashboard's.
- **`.env.example`, `docker-compose.yml`, `backend/README.md`** all document
  the full `DAYTONA_*` surface. The README section covers what the feature
  does, the snapshot lifecycle, and a five-step "if it is misbehaving" list
  (`/health`, the log's WARNING lines, `DAYTONA_FALLBACK_LOCAL=false` to
  separate Daytona faults from document ones, the dashboard, `verify_offload`).
- **`_daytona()`'s client is bound to the loop that built it.** Found while
  writing the live sweep harness: `TestClient` runs the lifespan on a portal
  loop of its own, and the cached client then fails with "attached to a
  different loop". Harmless in production — uvicorn is one loop for the life
  of the process, the lifespan included — but it is now written down in the
  docstring, because the fix is to clear the cache around the boot and not to
  make the client per-call, which would pay a TLS handshake per transfer.

### Tests — 255 → 270

All in `tests/test_offload.py`, all offline. The new fakes stand in for the
*client* rather than for `SandboxPool`, one level lower than everything else in
that file, because the sweep and the reactivation retry are the only parts of
the module that reach for Daytona directly. They are skipped when the SDK is
not importable, in the `requires_qpdf` style.

- **The sweep**: off by default touches nothing; deletes what a dead process
  left; filters on our own label; an empty account is the ordinary answer; a
  list that raises never blocks startup; one stuck orphan does not cost the
  others theirs; a hanging delete times out instead of hanging startup.
- **The retry**: woken and retried exactly once; still asleep after waking is
  *not* retried again (two creates, one activate, no loop); any other failure
  raises with one create and no activate; and five cases pinning how narrow
  `_looks_inactive` is.
- **The counter**: 0, then 2 while both shards are in flight, then 0 again.

### Re-verified against the CI-built snapshot

Everything before this part was verified against the hand-built snapshot from
part 2. This is the first point where the pipeline's own output is what runs,
so the whole matrix was re-run against `pdfkit-toolchain-04701fea2e5e`:

- **`verify_offload.py matrix`: 28/28** — output parity, error parity on an
  encrypted PDF across all four operations, a wrong snapshot name falling back
  with a correct file still produced, a real cancellation with the sandbox gone
  in 2 s, Word and Markdown on both a born-digital document and a scan, and
  Compress's per-file breakdown on a ten-file batch.
- **`verify_offload.py sharding`: 6/6** — 2 sandboxes cost 1.23x one, a 10-file
  OCR batch 27.2 s → 16.7 s (**1.63x**, against part 4's 1.67x on the
  hand-built snapshot), peak 2 alive, 42 monotone frames ending at 100, every
  sandbox gone afterwards.
- The account was confirmed empty of sandboxes afterwards, and the VPS harness
  image and corpus deleted.

## Phase 10 part 4 — sharding a batch across N sandboxes (2026-09-21)

Plan: `docs/phases/phase-10-daytona-sandbox-offloading-phase4.md`. Everything
outside `offload.py` is untouched — the four heads, `remote_job.py`, the
routers, the frontend. `maybe_offload` still takes the same three arguments and
still returns `list[OutputFile] | None` in the same order.

### What is now true

- **A batch is split into `min(len(files), DAYTONA_MAX_SANDBOXES)` contiguous,
  roughly-even shards** (`_split`), each with its own sandbox, its own
  `spec.json` naming a slice of the batch's files, and its own upload / exec /
  download — all run at once under one `asyncio.gather`. `remote_job.py` needed
  no change at all: it already just processes whatever `files` its spec names.
- **One semaphore permit is one sandbox, not one request.** A five-file batch
  with the ceiling at two takes *both* permits, so a second request arriving
  mid-flight gets none and runs locally — the same answer a saturated pool has
  always given, and the behaviour the app had before the feature existed.
  `_claim` takes what is free without ever waiting, so a partly-busy pool means
  fewer shards rather than a queue.
- **`FanIn` folds the shards' independent streams into one bar.** Each shard
  reports a percentage of *its own* file count, so nothing comparable can be
  relayed straight through; the fold works in whole files instead.
- **Outputs are recombined in shard order, never completion order**, because
  Compress's per-file `FileStat` list zips against `batch.files` positionally.
- **The Phase 2 fallback rule went batch-wide.** "Any Daytona failure before
  any file succeeded → run locally" now means any file across any shard: once
  one shard has produced one result line, a lost sibling is a hard 502
  `remote_job_interrupted` rather than a silent local rerun that would
  duplicate already-billed work. `_recombine` owns that decision, since it is
  the only place that can see every shard; a shard itself only ever raises
  `_Abandoned` and lets the verdict be worked out above it.
- **Teardown is per shard**, each with its own shielded, bounded `dispose()`,
  and `gather(..., return_exceptions=True)` is load-bearing: without it the
  first shard to raise returns from `_offload` while its siblings are still in
  flight and unawaited, and a sandbox nobody deleted bills until its TTL.

### `FanIn`, and the one place the plan's formula was wrong

The plan sketched a `dict[(shard, file)] -> fraction` and summed it. That does
not work, and the phase's own acceptance test ("`done == total` when both
shards report 100%") is what fails: a file's *last* frame before the next one
starts is rarely 100% of itself, so every finished file stays stuck at whatever
fraction it was last seen at and the bar ends permanently short.

What ships instead keeps **two numbers per shard** — whole files finished, plus
the fraction of the one in flight — which is exact rather than approximate,
because a shard runs its files strictly in order: "file 4 of this shard" is
itself the news that files 1-3 are done. Within a shard the contribution is
`clamp(p * n, i - 1, i)`, monotone because `p * n` and `i` both are, so when a
new file starts and the fraction drops to zero the completed count has already
risen by one to pay for it. `Publisher._monotonic` stays the backstop and never
has to do anything. It is also smaller: two ints per shard rather than a dict
entry per file.

One deliberate keep from the plan: **the detail line follows shard 0**, not
whichever shard spoke last, so the file name changes at a readable pace instead
of flickering between unrelated files. The one addition is that any shard may
fill it while shard 0 has not spoken yet — a blank name under a moving bar
looked worse than a name that changes once at the start.

Publishing is throttled the way `compress`'s own cursor is (0.25 s / 1.0%),
since N shims' frames interleaved would otherwise be N times the SSE traffic
for a bar that only has to read as live. The constants are copied rather than
imported: `compress` imports `offload`, so importing back would be a cycle.

### Tests — 241 → 255

All in `tests/test_offload.py`. Two of the fakes grew, for reasons sharding
made real rather than for the new tests' convenience:

- **`ScriptedPool` hands out a distinct id per `provision`** (`scripted-0`,
  `scripted-1`, …). "Disposed exactly once" is only a meaningful assertion if
  two sandboxes can be told apart, and with a single constant id the
  cancellation test was passing two disposals off as one.
- **Both fakes record the specs they were handed**, because `dispose` takes the
  tmpdir with it and a shard's slice is otherwise invisible to a test.

The new tests, and what each would catch:

- **`test_five_files_run_as_two_shards_and_come_back_in_file_order`** — the
  payoff test. Two real shims in two tmpdirs, with the shard holding the first
  three files held behind an `asyncio.Event` until the other has finished, so
  completion order is the *reverse* of file order. Proved by mutation:
  concatenating outcomes in completion order fails it.
- **`FanIn` unit tests**, no subprocess: monotone across a scripted
  two-shard interleaving, `done == total` when both report 100, the throttle,
  the detail line, garbage frames dropped, and a single shard reproducing the
  shim's own numbers unchanged (Phase 2's behaviour is the one-shard case of
  this one). Proved by mutation: the plan's per-`(shard, file)` dict fails
  three of them.
- **`test_a_batch_smaller_than_the_ceiling_never_makes_an_empty_shard`** and
  `test_a_half_busy_pool_shards_into_what_is_free` — the two ways shard count
  comes out below `DAYTONA_MAX_SANDBOXES`.
- **`test_a_shard_lost_after_a_sibling_produced_results_is_a_hard_error`** —
  the batch-wide fallback rule, with both sandboxes still disposed exactly once.
- **`test_every_shard_is_disposed_even_when_another_one_dies`** — one shard
  raising must not cancel a sibling out of its own teardown.
- **`test_the_app_tarball_records_nothing_about_this_machine`** — added after
  the live run, for the staging bug described below. The offline suite could
  not have found it: the fake pool returns 0 for the unpack because there is
  nothing to unpack.

### `verify_offload.py sharding`

A third mode beside `matrix` and `timings`, and the only one that runs the same
batch twice: one sandbox, then `DAYTONA_MAX_SANDBOXES`. It answers this phase's
two live questions — whether provisioning N at once really costs about what one
costs, and whether the batch actually finishes sooner — and prints the detail
line deduplicated, because whether it *reads* as coherent is the one thing no
assertion can settle.

Smoke-run offline against the fake pool first (4/4), then **run for real from
the VPS: 6/6**. The numbers it produced are in "The live runs" below.

### The live runs (2026-09-21, from the VPS, real account)

All of it run from a throwaway container on the VPS off the deployed backend
image plus `daytona` and `pytest` (`Dockerfile.harness`), with this phase's
`app/`, `tests/` and `scripts/` bind-mounted over it — the same recipe parts 0
and 2 used, and everything it created was deleted afterwards. The account was
confirmed empty at the end.

**The premise holds: parallel provisioning is free from the VPS.**

| | seconds |
|---|---|
| 1 sandbox | **1.03** |
| 2 sandboxes, concurrently | **1.14** (1.11x the cost of one) |

Phase 0's residential-link claim (2-in-parallel at the same 1.43 s as one)
survives re-measurement on the path that matters. One wrinkle worth keeping:
the **first** create in a process costs ~3.5 s, not 1 s — the client, its TLS
handshake and the snapshot lookup are all paid there. The first run of this
measured 3.46 s for one sandbox against 1.13 s for two, i.e. "0.33x", which is
not a thing that can be true; `parallel_create` now does a throwaway create
first so the comparison is honest.

**The payoff is real: a 10-file, 6-page-each OCR batch.**

| | seconds |
|---|---|
| one sandbox (parts 2/3's behaviour) | **21.1** |
| two sandboxes (this part) | **12.7** |
| | **1.67x faster** |

Not 2x, and it should not be: provisioning, upload and download are largely
fixed, so only the compute halves. Two sandboxes were confirmed alive at once
on the account during the batch, and both were gone 10 s after it finished.
The bar published 41 frames, never went backwards, and ended at exactly 100.

**The detail line reads the way the design intended.** Deduplicated, in order:

    file 1  05.pdf   Reading the pages     <- shard 1 got there first
    file 1  00.pdf   Reading the pages     <- shard 0 speaks, and keeps the line
    file 2  00.pdf … file 10  04.pdf       <- shard 0's files, 00 through 04

One frame from the other shard before shard 0 started, then shard 0's own files
in order while the count climbs with the whole batch's fold. That single
handover at the start is the `or not self._name` clause in `FanIn.update`, and
it is better than the blank name it replaced.

### The bug the live run found — and the fake pool never could

**Every batch was silently falling back to the VPS**, with
`could not stage the job: RuntimeError: unpacking app/ exited 2`. The first
sharding run therefore "measured" two local runs and reported a 1.15x win.

`tarfile` records the *source file's* uid/gid. The archive built from a
bind-mounted checkout carried **uid 197609 / gid 197121** — Windows-mapped
ownership — and GNU tar in the sandbox, running as root, dutifully tried to
`chown` every extracted file to it, failed with `Invalid argument`, and exited
**2 after writing every file correctly**. `_stage` reads a non-zero exit as
"could not stage", and the whole feature turns itself off without a word.

Two fixes, each defending a different half:

- `_without_caches` now normalises the archive to `uid=gid=0`, `root:root`.
  The tarball should say nothing about the machine that built it.
- the unpack command carries `--no-same-owner`, so extraction never attempts a
  chown whatever the archive claims.

Offline test: `test_the_app_tarball_records_nothing_about_this_machine`.

**Production was never hit** — the deployed image's `COPY app ./app` gives
uid 0, and part 2's dev runs were inside that same image — but anyone
bind-mounting a checkout to debug offloading would have been, which is exactly
what happened here.

### Part 3's matrix: 28/28

Output parity, error parity on an encrypted PDF across all four operations, a
wrong snapshot falling back with a correct file still produced, a real
cancellation, Word and Markdown on both a born-digital document and a scan, and
Compress's per-file size breakdown on a ten-file batch (`10 rows, 749,998 B
from 3,186,700 B, local 23.5% / remote 23.5%`).

**Section 4 failed the first time, and it was the harness, not the code.** The
cancellation check hung up on a fixed `sleep(6)`, and the batch it meant to
cancel now finishes in under six seconds — part 2's unpack fix plus a warm
client — so the "client" was hanging up after it already had its file, and the
section reported `no error` exactly as a cancellation regression would. It now
hangs up on the **first progress frame**, which is the earliest moment there is
definitely something to cancel and does not move when the feature gets faster.
With that, `499 cancelled`, sandbox gone in 2 s.

### Compress's economics — the number part 3 was missing, and it is not the expected one

| batch (synthetic photo-page PDFs) | local | offloaded |
|---|---|---|
| 10 files, 3.2 MB | **1.3 s** | **7.0 s** |
| 30 files, 9.5 MB | — | 8.4 s (sandbox compute 6.0 s) |

Sandbox compute went 4.3 s (10 files) → 6.0 s (30 files), so on this corpus:

- **marginal cost 0.085 s/file remote against 0.13 s/file local** — the sandbox
  core really is ~1.5x the VPS core here, as expected;
- on a **fixed ~3.5 s** per offloaded run: two shards' worth of interpreter and
  toolchain start, which the local path has already paid;
- **break-even ≈ 77 files.** Compress is a wall-clock loss at every realistic
  batch size on this corpus.

And the CPU protection argument does not rescue it here either. During the
30-file offloaded batch the VPS sat at 76-89% idle while the sandboxes worked
(dipping to 38-45% for ~3 s of upload and ~2 s of download) — but the local
compress it replaced was **1.3 s of work**. There was no CPU problem to protect
against.

**Caveat, and it matters:** `corpus("compress", …)` is one synthetic photo page
per file. A real Compress input is a 5-50 MB multi-page scan, where Ghostscript's
share of the time is far larger — part 0 measured 1.75x sandbox-over-local on
its realistic input. Note too that the 10-file/3.2 MB batch **would not have
offloaded in production at all**: `DAYTONA_MIN_BYTES` is 5 MB and the harness
sets it to 0.

So this is evidence about one corpus, not a verdict. What it does say is that
**Phase 5 must measure Compress on representative documents before flipping it
on**, and that the per-operation `DAYTONA_MIN_FILES` / `DAYTONA_MIN_BYTES`
override part 3 deliberately deferred is now the likely answer — or simply
leaving `compress` out of the default `DAYTONA_OPERATIONS`.

### Left to run

1. **A browser pass** on Compress's done screen with offloading on, and a watch
   of the SSE bar during a real sharded batch in the UI. Both need the feature
   turned on in a deployed environment, which is Phase 5's job.
2. **Compress on representative documents**, per the section above.

### One reporting trap in `timings`, introduced by sharding

The breakdown sums each call's own duration, and shards' calls overlap — so the
percentages add up to more than 100 and `(unaccounted)` goes negative (-3.78 s
on a two-shard Compress batch). It reads like a bug and is not one. The script
now says so when it is sharding, and `DAYTONA_MAX_SANDBOXES=1` gives a
breakdown that sums.

## Phase 10 part 3 — Word, Markdown and Compress get their heads (2026-09-20)

Plan: `docs/phases/phase-10-daytona-sandbox-offloading-phase3.md`. The plan
called this "three small, mechanical edits plus their tests", and that is what
it was: no new orchestration machinery, `offload.maybe_offload()` unchanged.

### What is now true

- **`word.to_word` and `markdown.to_markdown` each gained the three-line head**,
  passing `{"ocr_mode": ..., "languages": ...}` — the exact two options
  `remote_job._run_word` / `_run_markdown` have been reading since part 1.
  Nothing on the sandbox side changed for either.
- **`compress.compress` gained the one head that is more than "return the
  list."** It returns a `CompressionResult`, not `list[OutputFile]`, so the head
  re-derives `original_size` / `result_size` / per-file `FileStat` from
  `upload.size` (known before anything ran) and the bytes that arrived on disk.
  Those four lines duplicate the local path's own construction rather than being
  factored into a shared helper — the two read from different sources and one
  helper would need a parameter just to say which.
- **`DAYTONA_OPERATIONS` now defaults to `ocr,word,markdown,compress`** in
  `config.py`, `.env.example` and `docker-compose.yml`. Order is
  compute-per-byte, which is documentation: `eligible()` only tests membership.
- **No per-operation `DAYTONA_MIN_FILES` override was added**, even though the
  plan's own Context section flags Compress as the operation most likely to want
  one. That waits for Phase 5's production data rather than being guessed at now.

### Why Word and Markdown before Compress, reversing the original plan

Part 0's measurements, not preference. Ghostscript compress was 1.75x
sandbox-over-local, below the plan's own ">= 2x" bar and on a 0.3–0.6 s
operation that is mostly process startup. OCR was 2.62x per core. Word and
Markdown both route their OCR sub-step through the same `ocr_to_path`, so they
inherit OCR's economics whenever OCR fires and are at worst compress-like
otherwise. Compress stays in the set regardless: its win is **VPS-CPU
protection** on a big batch — ~20 subprocesses per file moved off the box —
more than per-file speed.

### Tests — 212 → 241

All in `tests/test_offload.py`, extending part 2's fakes rather than starting a
new file, because `FakeSandboxPool` and the decision-matrix machinery were
already operation-agnostic.

- **The decision matrix is parametrized across all four operations now.** Both
  `test_offloading_is_off_by_default` and `test_a_failed_gate_never_touches_the_pool`
  run per operation, the latter with an `OTHERS` sentinel that builds "an
  allowlist naming every operation but this one" once the parametrized operation
  is known. This is what says part 2's implementation never silently
  special-cased OCR.
- **`test_every_head_asks_for_its_own_operation`** stubs `maybe_offload` to
  record and then raise, so the local path never starts and the test needs no
  tool at all. It is the only test that catches the copy-paste this phase was
  most exposed to — a head naming a sibling operation — because the shim would
  otherwise dispatch happily and produce a plausible file of the wrong kind.
  (Proved by mutation: flipping markdown's head to `"word"` fails this test.)
- **Word and Markdown round-trips**, each run twice — once offloaded through the
  real shim in the fake pool, once locally — and compared on download name,
  media type and *visible content* (`docx_text` / the Markdown text). Plus a
  scan through each with `ocr_mode="auto"`, the mode that routes through
  `ocr_to_path` and so is the one worth offloading.
- **Compress's size report** gets the dedicated assertion the plan asked for:
  per-file `FileStat` rows paired with the right uploads (the two fixtures have
  deliberately different page counts, so a mis-zip or a repeated row shows up),
  each `result_size` equal to the file that actually arrived, and the totals
  agreeing. Also proved by mutation.
- **Error parity** for `compress` / `word` / `markdown`: a locked PDF returns
  422 `password_required` identically on both paths, driven through the real
  drivers, with the sandbox still disposed of.
- **A compress fallback test** drives `compress.compress` through a failed
  provision, because fallback has to skip the whole head — walrus and
  re-derivation alike — not just `maybe_offload`.

`docker compose run --rm --build backend-tests` → **241 passed, 1 skipped**
(183 → 212 → 241). The skip is still the opt-in live test. **Use `--build`**:
the test image `COPY`s `app/` and `tests/`, so a plain `run` silently tests the
previous commit's code — that mistake cost a confusing "212 passed" here.

### `scripts/verify_offload.py` now covers all four

Part 2 committed this script saying "Phase 3 wants to re-run exactly this". It
was OCR-only, so re-running it would have proved nothing about the new heads.
Extended rather than duplicated:

- A `drive(operation, batch)` / `readable(operation, output)` / `corpus(...)`
  table, since the only thing that differs between the four is which driver to
  call and what a readable output looks like.
- **Section 2 (error parity) now loops over all four operations.**
- **New section 5**: Word and Markdown, each on a born-digital document *and* a
  scan, local vs remote, compared on download name, content and a monotonic bar.
- **New section 6**: Compress on a ten-file batch, asserting the per-file size
  breakdown Phase 8 added — the numbers, not just "a file came back", because
  a wrong re-derivation shows the user plausible nonsense rather than an error.
- `timings` gained `--operation` and `--files`, so the CPU observation during a
  Compress batch is `timings --operation compress --files 10 --remote-only`.

The script's own new code was smoke-run offline against the unit tests'
`FakeSandboxPool` (sections 2, 5 and 6, 21/21 PASS) so it is not shipped
unrun — but that is the fake pool, not Daytona.

### What was left to run — **all of it ran on 2026-09-21, in part 4**

Nothing here was run in part 3's own session; there were no credentials in that
environment. Part 4 ran every item from the VPS against the real account, and
the results live in that section:

1. `matrix --pages 6 --files 10` — **28/28**, including this part's sections 5
   and 6 (Word and Markdown parity, Compress's per-file size breakdown).
2. `timings --operation compress --files 10 --remote-only` from the VPS with
   `vmstat` — done, and the answer is not the one this part assumed. The VPS
   does stay near-idle while the sandboxes work, but the local Compress it
   replaces is so cheap on the measured corpus that **offloading it is a
   wall-clock loss**. See "Compress's economics" in part 4.
3. The browser pass on Compress's done screen is still outstanding: it needs
   the feature turned on in a deployed environment, which is Phase 5's job.

## Phase 10 part 2 — `offload.py`, wired into OCR only (2026-09-20)

Plan: `docs/phases/phase-10-daytona-sandbox-offloading-phase2.md`. **Done, and
verified against a live Daytona account** — the snapshot exists, the matrix passes,
and two real bugs were found by running it for real. See "What the live runs found".

`DAYTONA_ENABLED` defaults to `false`, so this ships dark: every existing test
exercises the old code path unchanged, and turning it on is Phase 5's deliberate,
separate act.

### Step 0 first: the streaming-exec question the spike never answered

The plan opened by insisting this be checked before writing `_DaytonaPool.run`,
because Phase 0's spike used a single blocking `POST /process/execute` and so could
not have discovered a problem here. Verified against the **pinned `daytona`
0.214.0**, by installing it and reading the source — both assumptions hold, with
the method names the plan guessed at:

- `SessionExecuteRequest(command=..., run_async=True)` +
  `process.execute_session_command()` returns as soon as the command *starts*,
  handing back a `cmd_id`;
- `process.get_session_command_logs_async(session_id, cmd_id, on_stdout, on_stderr)`
  streams over a websocket with **separate** stdout/stderr callbacks, sync or
  async. It delivers **chunks, not lines** — so `offload._Lines` splits them, the
  small version of what `runner._Pump` does for a subprocess pipe.
- `process.get_session_command(...).exit_code` is how the exit status comes back,
  polled briefly because the log socket's EOF can beat the command record.
- The `/sandbox/paginated` bug is **gone**: `AsyncDaytona.list()` calls
  `list_sandboxes` → `GET /sandbox` with cursor paging. The deprecated paginated
  endpoint still exists in the generated client but nothing in `list()` reaches it.
  Phase 5's orphan sweep can use `list()` as designed.

The dependency is pinned `daytona==0.214.0`, not floated, because neither of the
first two shapes is guaranteed by semver.

### What is now true

- **`backend/Dockerfile` has a `toolchain` stage** — `FROM base` plus
  `ENTRYPOINT ["sleep", "infinity"]`, two lines. `base` was already exactly the
  right layer (every apt package, `uv sync --no-install-project`, no `COPY app`),
  so no surgery was needed. The entrypoint has to live in the Dockerfile rather
  than the snapshot request, per Phase 0's finding.
- **`backend/scripts/build_snapshot.py`** builds the snapshot from that stage.
  `buildInfo` takes a Dockerfile, not a target, so the script **slices the `base`
  stage out of the real Dockerfile and appends `toolchain`'s own lines** — the apt
  list and the locked dependency install physically cannot drift from what the
  backend image is built with. `pyproject.toml`/`uv.lock` ride along as the build
  context via `Image.dockerfile_commands(..., context_dir=...)`. `--print` dumps
  the flattened Dockerfile touching no API; `--verify` creates a throwaway sandbox
  and execs `gs`/`qpdf`/`tesseract`/`ocrmypdf` in it. Phase 5 turns this into CI
  with content-hash tagging.
- **`config.py` has seventeen `DAYTONA_*` knobs plus `remote_timeout_for()`**,
  every one read as `config.X` at call time.
- **`Publisher.batch()`** sets an already-folded batch percentage directly,
  bypassing `_overall()`. Needed now, not at Phase 4: the shim folds its own files
  into a batch-wide number inside the sandbox, and pushing that back through
  `file`/`step`/`percent` would fold it a second time against this process's own
  bookkeeping. Still monotonic. `NullPublisher` inherits it for free.
- **`app/services/offload.py`** — `maybe_offload()` plus the `SandboxPool`
  protocol and `_DaytonaPool`. Nothing outside this module imports `daytona`, and
  even inside it the import is inside the function, so the module stays importable
  on a machine without the SDK.
- **`ocr.py` pins `--jobs` and gained the three-line head.** `compress`/`word`/
  `markdown` are untouched — Phase 3.

### Decisions made while building it, that Phases 3 and 4 inherit

- **A saturated `DAYTONA_MAX_SANDBOXES` runs the batch locally rather than
  queueing.** Waiting for a remote slot would stack a queue in front of the local
  path's own `QUEUE_TIMEOUT_SECONDS` queue, and falling through is exactly the
  behaviour that existed before the feature. Non-blocking check, no new knob.
- **A per-file error aborts the exec; it does not wait for the shim to finish.**
  The shim keeps going after a `status: "error"` line (it has no per-batch verdict
  to make), so without this a 20-file batch with an encrypted first file would make
  the user wait for all 20. A watchdog task polls both `relay.failure` and
  `progress.client_gone()` every 2 s and cancels the exec; the same loop is what
  gives cancellation its 499.
- **Output files are downloaded after the run, not inside `on_line`.** The plan's
  §6 reads as if the `get` happens on each `status: "ok"` line, but its own §5 says
  the callback must be non-blocking. The callback parses and records; `_collect`
  downloads. `result_size` from the shim is checked against the bytes that arrive.
- **The Daytona client is a process-wide singleton**, rebuilt if the credentials
  change, so the TLS connection pool is reused across requests — part of what makes
  Phase 0's 60 MB/s a per-transfer number. `DAYTONA_TARGET` lives on that client
  (`DaytonaConfig(target=...)`), not on the create call.
- **`MARKER` is copied into `offload.py`, not imported** from `remote_job` —
  importing it would be a cycle, since that module imports every service and `ocr`
  now imports `offload`. `test_offload.py` asserts the two stay equal, the same
  arrangement `ocr.MARKER` already has with its plugin.
- **`--jobs` is a behaviour change on the local path too**, deliberately: OCRmyPDF
  previously auto-sized from `os.cpu_count()`. On the 2 vCPU VPS that already was 2,
  so production is unchanged; on a bigger dev box OCR now uses fewer workers.

### Verified

- `docker compose run --rm backend-tests` → **212 passed, 1 skipped** with no
  `DAYTONA_*` env vars set (183 before this phase, 29 new). The skip is the opt-in
  live test, `@pytest.mark.skipif(not os.getenv("DAYTONA_API_KEY"))`.
- `docker build --target toolchain` builds, and `gs 10.00.0` / `ocrmypdf 17.12.1` /
  `qpdf 11.3.0` / `import ocrmypdf, pypdf, fitz` all resolve inside it.
- **The whole sandbox contract, rehearsed locally in that image**: staged
  `offload._app_tarball()` (79 KB) and a real spec into a volume mounted at
  `/work`, then ran the exact command `_exec` builds —
  `mkdir -p /app && tar xzf /work/app.tgz -C /app && cd /app &&
  MAX_CONCURRENT_JOBS=4 /opt/venv/bin/python -m app.tools.remote_job /work/spec.json`.
  Exit 0, progress frames on stderr rising 0 → 15 → 71.2 → 100, one result line on
  stdout, and a real 9,345-byte OCR'd PDF in `/work/out`. That is everything a live
  sandbox does except the network.
- `tests/test_offload.py` covers the four decision-gate misses, the saturated pool,
  a real round trip through the shim, the encrypted-input 422 **not** falling back,
  relayed progress being monotonic to 100, provision failure → local fallback (and
  `ocr.ocr` then producing a correct file through its own loop), exit 1 → fallback,
  a loss after partial results → 502, `DAYTONA_FALLBACK_LOCAL=false` → 502,
  cancellation → 499 with exactly one dispose, budget overrun → 504, staging paths,
  the tarball's contents, chunk-split line reassembly, and `Publisher.batch()`'s
  identity, monotonicity and detail-line behaviour.

### What the live runs found (2026-09-20, real account)

The offline suite proves the orchestration; it cannot prove Daytona behaves as
assumed. Running it for real found **two bugs the fake pool could not have**.

**The snapshot exists.** `scripts/build_snapshot.py` built `pdfkit-toolchain` in
one pass — ACTIVE, 4 vCPU / 4 GiB / 10 GiB. `--verify` on a throwaway sandbox:
`gs 10.00.0`, `qpdf 11.3.0`, `ocrmypdf 17.12.1`, 15 Tesseract languages, and
`import ocrmypdf, pypdf, fitz` all resolve. The flatten-the-Dockerfile approach
worked first time, entrypoint-in-the-content and all.

**`nproc` inside a sandbox now reports 64**, against `cpu.max` of `400000 100000`
(= 4 CPUs). Phase 0 measured 48. The number is not merely wrong, it *drifts* —
which retires any thought of ever deriving it from inside. The `--jobs` pin is
load-bearing, not precautionary.

**Bug 1, found by the live test — one session per command was a hard conflict.**
`_DaytonaPool.run` derived its session id from the sandbox id, and `run` is called
twice per batch (the unpack, then the shim), so the second call hit
`DaytonaConflictError: session already exists`. The fallback did its job perfectly
— the batch ran locally and the user would have seen nothing — which is exactly
how this would have hidden in production as "offloading mysteriously never works".
Now one session is created per sandbox and reused, which is the SDK's own
documented pattern.

**Bug 2, found by the timings breakdown — the unpack cost 2.19 s.** The `tar xzf`
was paying for a session, a websocket and an exit-code poll to stream output
nobody reads. `SandboxPool.run` now takes `on_line: ... | None`, meaning exactly
what it means on `runner.run`, and `_DaytonaPool` takes a single blocking
`process.exec()` when there is no reader. **2.19 s → 0.18 s** on a workstation, and **0.02 s** on the
VPS — where it had been a third of the entire per-job overhead.

**The matrix passes 8/8** (`scripts/verify_offload.py matrix`, committed so Phase 3
can re-run it): download name unchanged, same text layer word for word, the SSE bar
monotonic to 100, an encrypted PDF giving `422 password_required` identically with
offloading off and on, a wrong `DAYTONA_SNAPSHOT` falling back and still returning a
correct file, a real cancellation returning `499 cancelled` with the sandbox gone
from the account within 2 s.

One correction to the plan's wording: outputs are **not byte-identical** across the
two paths and cannot be — OCRmyPDF stamps a creation time and document id into
every file. Observed difference is 0–1 bytes on a 71 KB output, with identical
extracted text. That is the assertion the script makes.

### Timings at realistic scale — measured on the VPS, which is the only place it counts

`scripts/verify_offload.py timings --pages 50` on a 50-page / 2.3 MB scan. Run
**twice, in two places**, because running it in the wrong place inverts the
answer. Both used a throwaway container off the deployed backend image, Phase 0's
recipe (the deployed image predates this phase, so the SDK and `app/` were
supplied at run time; nothing about the running service was touched).

| | dev workstation | **the VPS** |
|---|---|---|
| local path (`--jobs 2`) | 5.0 s | **20.4 s** |
| remote path, total | 17.7 s | **12.0 s** |
| — sandbox compute (`--jobs 4`) | 8.0 s | 7.5 s |
| — transfer, 2.3 MB up / 0.6 MB down | 6.2 s | **0.9 s** |
| — provision + dispose + unpack | 3.5 s | 3.6 s |
| compute speedup | 0.62x | **2.73x** |
| verdict | offload is a 3.5x *loss* | offload is a **1.7x win** |

The two rows that move are exactly the two Phase 0 predicted would: the transfer
(60+ MB/s from the datacenter against ~0.9 MB/s residential) and the local
baseline (a 2026 workstation is four times a contended VPS core). **2.73x lands
almost exactly on Phase 0's 2.62x**, measured independently, a year of hardware
apart, on a document eight times the size. That is the plan's ">= 2x or the
parallelism premise fails" bar, cleared on the real case rather than a 6-page
proxy.

### Does the VPS actually stay idle? Yes — measured, not argued

The first VPS run could not answer this: it ran the local path and the remote path
back to back in one container, so no CPU sample could be attributed to either.
`verify_offload.py` therefore grew `--remote-only` and prints `REMOTE-START` /
`REMOTE-END` epoch markers, so an external sampler can say which of its samples
belong to the claim. `vmstat` every ~2 s across the whole run:

| phase | mean idle | min idle |
|---|---|---|
| baseline (18 other apps, nothing of ours) | 86.4% | 74% |
| the harness building the fixture + installing deps | 15.6% | **1%** |
| **the sandbox doing the OCR** | **73.0%** | 40% |

and the remote window's samples in order — `41 46 40 · 81 87 87 88 88 95 89 · 61`
— show the shape plainly: a brief dip while 2.3 MB is read and uploaded, then
**~88% idle, indistinguishable from baseline, for the whole time the sandbox is
running Tesseract.** For contrast, the local OCR in the earlier combined run drove
idle to 0–4% and load from 0.52 to 2.86.

So the feature does what it was built for. The VPS is idle during the expensive
part, and the expensive part also finishes sooner.

### Nothing is left open on this phase

The VPS working directory was removed and the credentials file shredded; the
Daytona account holds the `pdfkit-toolchain` snapshot and **zero sandboxes**. VPS
load returned to 0.63 and disk is unchanged at 69%.

Phase 5 still owns flipping `DAYTONA_ENABLED=true` in Coolify, the CI snapshot
rebuild, and the orphan sweep — but none of those are blocked on evidence any more.

## Phase 10 part 1 — the `remote_job.py` shim (2026-09-20)

Plan: `docs/phases/phase-10-daytona-sandbox-offloading-phase1.md`. **Done and verified.**
A pure addition — exactly two new files, nothing existing edited, confirmed with
`git diff --stat`:

- `backend/app/tools/remote_job.py` — the third `app/tools` shim. Reads a JSON spec,
  dispatches each file to the existing per-file service function (`compress_one`,
  `ocr_one`, `to_word_one`, `to_markdown_one`), writes one result line per file to
  **stdout** and progress frames to **stderr**, same conventions as `anydoc_cli`.
- `backend/tests/test_remote_job.py` — 17 tests, all offline, invoking the shim as a real
  local subprocess against a tmpdir standing in for `/work`. No Daytona SDK, no config
  knobs, no network: `docker compose run --rm backend-tests` is 183 passed.

### Decisions made while building it, that Phase 2 inherits

- **Files run one at a time, like the batch drivers.** A single `Publisher` carries one
  file index at a time, so concurrent files would interleave into incoherent progress
  frames — and sequential is what the local path does, which is the behaviour an
  offloaded job has to reproduce. `MAX_CONCURRENT_JOBS` still has to be set on the shim's
  process (it sizes `runner._slots` at import, which is the free win), but it governs the
  subprocess concurrency *inside* a file, not a file-level pool.
- **Exit 1 is "the shim could not run", and its diagnostic goes to stderr**, unlike
  `anydoc_cli`'s, which puts it on stdout because `markdown._parse` reads stdout even on
  failure. Here stdout is strictly the per-file result contract, so leaving it empty makes
  "no results" unambiguous. A per-file `HTTPException` is a `status: "error"` line with
  `http_status`/`detail` verbatim and exit **0**; any other escaping exception aborts the
  batch with exit 1, matching what a batch driver would have done locally (a 500) and
  letting the orchestrator fall back rather than invent a per-file verdict.
- **The terminal 100% frame is only emitted on a clean batch.** Locally it is the
  `job_publisher` dependency that publishes terminality, with `reason=ERROR` and the bar
  left where it stopped on a failure. An unconditional 100 would hand the orchestrator a
  "finished" frame for a batch it is about to re-raise a 422 from.
- **Spec defaults mirror the routers**, so a smoke spec needs only `operation` + `files`:
  `level=recommended`, `languages=["eng"]`, `ocr_mode` `off` for `word` and `auto` for
  `markdown`. Relative `input` paths resolve against the spec's own directory, so the
  orchestrator can write `{"input": "in/a.pdf"}` next to `/work/spec.json` without either
  side agreeing on an absolute path. `out_dir`/`scratch_dir` default to `out`/`scratch`
  beside the spec.
- The plan's example error line says `"detail": "encrypted_input"`; the real value is
  **`password_required`** — `errors.encrypted_input()` raises `422 password_required`.
  The tests assert the real one.
- `_run_compress` reaches for `compress._Cursor`, which is private. Deliberate: it is what
  `compress.compress` passes, and dropping it would silently lose every intra-file step.

### Left for Phase 2, noted here so it is not lost — **both done in part 2**

- ~~**`ocrmypdf --jobs` still needs pinning.**~~ Done: `ocr.ocr_to_path` now passes
  `--jobs str(config.MAX_CONCURRENT_JOBS)`, which `word` and `markdown` inherit for
  free since they share that function.
- ~~`FakeSandboxPool` should reuse `tests/test_remote_job.py::run_remote_job`~~ Done:
  `tests/test_offload.py::FakeSandboxPool.run` calls it in a thread. Its only added
  trick is path translation — the sandbox's `/work` is a tmpdir here, so `spec.json`'s
  `out_dir`/`scratch_dir` are rewritten on the way in.

## Phase 10 part 0 — Daytona offload measurement spike (2026-09-20)

A throwaway measurement, not shipped code. Plan:
`docs/phases/phase-10-daytona-sandbox-offloading-phase0.md`. Script:
`backend/scripts/spike_offload.py` — kept as the spike artifact, deliberately
**stdlib-only** against Daytona's REST API (no `daytona` SDK), so it runs unmodified in
the production runtime image with nothing installed into it. It is not imported by
anything, not copied into the image by `backend/Dockerfile`, and no later phase depends
on it; delete it freely.

Run on the VPS as a throwaway container off the deployed backend image, not by exec'ing
into the live one (same egress path, zero risk to the running service):

```
docker run --rm --env-file daytona.env -v /root/pdfkit-spike:/spike:ro \
  --entrypoint python <backend-image> /spike/spike_offload.py --pages 6
```

### The verdict: GO — transfer is noise, and offloading is also a genuine speed win for OCR

| Measurement (VPS → Daytona, n=5) | min | median | max |
|---|---|---|---|
| upload 5 MB | 5.60 MB/s¹ | 71.70 MB/s | 86.10 MB/s |
| upload 25 MB | 83.53 | **105.09** | 115.11 |
| upload 50 MB | 95.54 | **102.25** | 114.09 |
| download 5 MB | 23.85 | 28.75 | 41.68 |
| download 25 MB | 35.09 | **47.05** | 50.07 |
| download 50 MB | 33.42 | **48.51** | 76.08 |

¹ first sample of the run — TLS handshake, not the link.

**Median across all sizes and both directions: 60.1 MB/s.** That is the plan's
"**> 20 MB/s → transfer is noise**" bucket, by a factor of three. In wall clock a 50 MB
file costs **0.49 s up and 1.03 s down**. The residential 1.4–1.8 MB/s figure the plan
was worried about was an artifact of the measuring workstation, exactly as suspected —
the datacenter link is ~40× faster.

Everything else in the per-job fixed cost is smaller still:

| | min | median | max |
|---|---|---|---|
| create → ready, from a named snapshot | 0.71 s | **0.79 s** | 0.84 s |
| delete | 0.13 s | 0.14 s | 0.15 s |
| `app/` tarball (61 KB gz) upload + `tar xzf` | 0.04 s | **0.05 s** | 0.05 s |

Provisioning off the VPS is *faster* than the 1.06–1.63 s measured residentially, and the
per-request `app/` upload the design pays on every job is 50 ms. **Total fixed overhead
for an offloaded job is ~1 s plus ~1.5 s of transfer for a full 50 MB file — call it
2.5 s worst case.**

### Compute: a Daytona core is ~2.6× a VPS core on OCR

Identical argv on both sides, 6-page generated scan, 2 runs each. "local" is a container
off the same backend image on the VPS (2 vCPU, and genuinely contended — the box was at
load ~0.7 from the other 18 apps throughout, which is the honest baseline).

| operation | sandbox (4 vCPU) | local (VPS) | speedup |
|---|---|---|---|
| Ghostscript compress | 0.32 s | 0.57 s | 1.75× |
| `ocrmypdf --jobs 1` (per-core comparison) | 1.83 s | 4.78 s | **2.62×** |
| `ocrmypdf --jobs 4` vs local `--jobs 2` (real conditions) | 1.07 s | 3.93 s | **3.67×** |

The plan's kill criterion was "a 4 vCPU sandbox not ≥ 2× a VPS core on the same file →
the parallelism premise fails." **For OCR it passes on the honest reading**: a single
Daytona core beats a single VPS core 2.62×, before any parallelism, and the realistic
4-vs-2 comparison is 3.67×. So the feature is a speed win, not only VPS-CPU protection,
and user-facing copy may say so — **for OCR**.

Compress's 1.75× is below the bar, but that row is weak evidence in either direction: the
whole operation is 0.32–0.57 s, so it is mostly process startup. Treat it as consistent
with the plan's own note that Compress is the marginal case, not as a measurement of
Compress at realistic sizes.

### The one surprise, and it is load-bearing for Phase 1

**`nproc` inside a Daytona sandbox reports the runner's core count, not the sandbox's
quota.** Measured: `nproc` = 48 and `len(os.sched_getaffinity(0))` = 48, while
`/sys/fs/cgroup/cpu.max` = `400000 100000` (= 4 CPUs) and `memory.max` = 4 GiB. Anything
that sizes its worker pool from `os.cpu_count()` will start 48 workers inside a four-CPU
quota.

This lands directly on Phase 1's `remote_job.py`: that phase already says
`MAX_CONCURRENT_JOBS` must be set as an env var on the shim process "sized to that
container's own vCPU count" — this measurement says **that number cannot be discovered
from inside the sandbox and must be passed in** by the orchestrator, and that
`ocrmypdf --jobs` needs pinning for the same reason. (Not measurably harmful on the
6-page fixture, because OCRmyPDF caps jobs at page count — 6 pages never reaches 48. The
exposure is a 50-page scan, which this spike did not test.)

### Resulting changes to the plan

- **Phase 1 is unchanged and cleared to start**, plus the `nproc` note above.
- **`DAYTONA_MIN_BYTES` stops being load-bearing.** At 60 MB/s the byte count barely
  affects the decision; the gate should be about *expected compute*, not transfer. With
  ~2.5 s of fixed overhead worst case, offload pays whenever local work would exceed
  ~5 s. `DAYTONA_MIN_FILES` (and operation type) is the honest gate; keep
  `DAYTONA_MIN_BYTES` as a cheap floor but the 5 MiB default is now arbitrary rather than
  economically derived.
- **Keep Compress in the offload set, but last.** Order by compute-per-byte as the plan
  already intended: OCR first, then PDF→Word / PDF→Markdown, Compress last.
- **`pdfkit-toolchain` must exist as a real snapshot before Phase 2 — the default is not
  good enough.** Daytona's stock snapshots carry no Ghostscript, Tesseract or OCRmyPDF,
  so none of the four operations can run on them at all. Building one is cheap and the
  recipe is now known: `POST /snapshots` with `buildInfo.dockerfileContent`, ~3 minutes
  one-time, 0.40 GB, after which create → ready is 0.79 s. Two API constraints found the
  hard way, both worth carrying into the Phase 2 CI step:
  - a top-level `entrypoint` may **not** accompany `buildInfo` ("Cannot specify an
    entrypoint when using a build info entry") — put `ENTRYPOINT ["sleep", "infinity"]`
    in the Dockerfile instead;
  - `cpu`/`memory`/`disk` may **not** be sent on `POST /sandbox` when creating from a
    snapshot ("Cannot specify Sandbox resources when using a snapshot") — sandbox
    resources come from the snapshot, so they are set at snapshot-build time.
  The spike's own `pdfkit-spike-toolchain` (English-only OCR) was deleted afterwards;
  `spike_offload.py` rebuilds it automatically if re-run.
- **Free-tier sizing holds.** One 4 vCPU / 4 GiB / 10 GiB sandbox behaved exactly as
  specified; nothing observed argues against the planned 2 × (4, 4, 10).

### Verified

The run finished in ~40 s of wall clock. VPS load average went 0.62 → 1.80 → back to
0.76 (the spike container peaked at ~98% of *one* core during the OCR section only), so
the measurement was nowhere near the sustained 100%-across-both-cores that triggered
Hostinger's throttle twice before. 800 MB moved, every download byte-verified against
what was uploaded. No Daytona resources leaked: sandbox listing is empty and the spike
snapshot is deleted. The credentials file copied to the VPS for the run was shredded and
`/root/pdfkit-spike/` removed; the raw log is left at `/root/pdfkit-spike-run.log`.

**Not done:** anything at realistic document scale. Every compute number above comes from
a 6-page, 266 KB generated scan — enough to answer "is a sandbox core faster than a VPS
core", not enough to predict a 50-page 50 MB scan, which is precisely the case the
feature exists for. Re-measure that once Phase 2 can run a real job end to end.

## Phase 9 — Admin dashboard at `/admin` (2026-09-20)

A private, password-gated dashboard answering "is anyone using this, and which tool?" —
something Umami's page views can't answer, since a page view isn't a job. Full design in
`docs/phases/phase-9-admin-dashboard.md`.

### What is now true

- **New `pdfkit` schema** on the existing shared Postgres box (`76.13.7.106`), one table
  (`pdfkit.tool_runs`), applied idempotently on first use by `frontend/lib/db.ts` — no
  manual migration step. `frontend/lib/stats/schema.sql` is the human-readable copy;
  `lib/stats/schema.ts` is what actually ships (a template string, not a runtime file read,
  so it survives the `output: "standalone"` bundle untouched).
- **One hook, all twelve tools.** `ToolShell.handleSubmit`/`handleCancel`
  (`components/tool/tool-shell.tsx`) call `recordRun()` (`lib/stats/record.ts`) on every
  `done`/`error`/`cancelled` outcome — a fire-and-forget, `keepalive: true` POST to
  `/api/stats/event` that never awaits and never surfaces an error. No per-tool edits.
- **Ingest is a cost gate, not a trust boundary**: unknown tool → rejected, every numeric
  field clamped, rate-limited at 60/min, always answers `204` regardless of outcome. Derives
  `runs_in` from the registry server-side rather than trusting the client.
- **Visitor identity is `sha256(ip + daily salt + date)`, truncated to 22 chars** — countable
  within a day, unlinkable across days, never an IP on disk.
- **Admin auth reuses the `/api/token` HMAC idiom** (`lib/admin/session.ts`), but over Web
  Crypto so the identical `verifySession` runs in `proxy.ts` and in route/page handlers
  alike. The session payload carries a fingerprint of `ADMIN_PASSWORD`, so rotating the
  password invalidates every live cookie for free — verified: change the password, restart,
  the old cookie stops authenticating.
- **Login throttling has two layers**: the existing Upstash limiter (fails open by design)
  plus a module-level in-process counter as a floor, because a password field failing open
  is the wrong default. Verified against the real Upstash instance.
- **The whole feature degrades quietly with `DATABASE_URL` unset**: ingest still answers
  `204` without touching the network, the dashboard renders a "not configured" panel. This
  was the one non-negotiable verification and it holds — a stopped/misconfigured stats DB
  cannot fail a tool run, because `recordRun` never awaits its own fetch.
- **Dashboard** at `/admin` (behind `proxy.ts`, Next 16's renamed `middleware.ts`): range
  selector (24h/7d/30d/all), tiles (runs, files, pages, bytes in/out, success rate, bytes
  Compress saved, unique visitors, median/p95 duration), a 30-day column chart, ranked
  tool-usage bars, browser-vs-backend split, a failures table, and the last 50 runs. No
  charting dependency — CSS/SVG, matching the project's existing hand-rolled-over-library
  posture. Added the `Table` shadcn primitive (`npx shadcn@latest add table`).
- **`/admin` is invisible everywhere public**: no nav link (`SiteHeader` returns `null` on
  `/admin*`), no footer link, absent from `sitemap.xml` (confirmed), `robots.ts` disallows
  it, and the Umami tracker (now wrapped in `components/layout/analytics.tsx`) doesn't fire
  there either, so admin sessions never pollute public page-view counts.
- **`app/(site)/privacy/page.tsx`** gained an honest paragraph on the anonymous counters;
  `llms.txt` no longer implies zero server-side state.

### A framework surprise worth remembering

This Next.js install (16.3.5) has already renamed `middleware.ts` → `proxy.ts` (function
`middleware()` → `proxy()`); the old convention still works but logs a deprecation warning
and there's a codemod (`npx @next/codemod@canary middleware-to-proxy .`). Proxy also now
defaults to the **Node.js runtime**, not Edge — irrelevant here since `lib/admin/session.ts`
was written against Web Crypto rather than `node:crypto` regardless, specifically so it
would run unmodified wherever Proxy landed.

### Verified

`npm run lint`, `npx tsc --noEmit`, `npm run build` all clean (27 routes, `/admin` and
`/admin/login` both dynamic). `docker compose --profile test run --rm backend-tests` → still
**166 passed** — the backend has zero diff for this phase (`git status --short backend/` is
empty).

Against `next dev` on port 3000 with the real shared Postgres and real Upstash: confirmed
via `psql` that `pdfkit.tool_runs` has the right shape and every `visitor` value is a
22-char hash, never an IP; posted a hand-crafted event with an unknown tool, a negative
`file_count` and a 100 KB `error_code` and confirmed it was rejected with `204` and **no
row written**; ran a real Merge (two real fixture PDFs, in a real headless browser via the
`browse` skill) end to end and confirmed the exact row it produced (`tool=merge,
runs_in=browser, outcome=done, file_count=2, page_count=7`, byte counts matching the actual
files); posted synthetic `error` and `cancelled` events for other tools and confirmed they
show up correctly in the failures table and recent-runs table; confirmed `/admin` with no
cookie 307s to `/admin/login`, and `/admin/login` itself renders a plain, un-hydrated form;
6 wrong-password attempts against the same IP throttle (429) as expected, using the real
Upstash-backed limiter; changed `ADMIN_PASSWORD` and restarted — the previously-valid
session cookie stopped authenticating, then changed it back and confirmed the original
cookie value was never valid again either (a new login was required, as intended — a
session is bound to the password in effect *at the time it was issued*); confirmed the
degrade path by starting a second `next dev` with `DATABASE_URL` forced empty — ingest still
`204`s, dashboard shows "Stats are not configured", nothing else affected. Login page
screenshotted at desktop and 390px width, light and dark — no overflow, matches the
existing design system (same Card/Input/Button primitives, same brand teal).

**Not done, and worth knowing for next session:** the authenticated dashboard itself
(tiles/charts/tables with real data) was verified by inspecting the rendered HTML over curl
with a valid session cookie, not with an in-browser screenshot — by the time synthetic data
existed to look at, the login-throttle window (15 min, shared per-IP bucket with the earlier
curl-based throttle test) was still active for the headless browser's IP, and waiting it out
wasn't worth the wall-clock cost this session. The HTML was byte-checked against expected
values (tile numbers, table rows) and it renders with the same components used everywhere
else in the app, so the risk is low, but a real screenshot of the populated dashboard is the
one item left before calling this phase fully closed.

### Env additions

Six new runtime vars (never `NEXT_PUBLIC_`, never build args): `DATABASE_URL`,
`ADMIN_USERNAME`, `ADMIN_PASSWORD`, `ADMIN_SESSION_SECRET`, `STATS_SALT`,
`STATS_RETENTION_DAYS`. Wired into `docker-compose.yml`, documented in both
`.env.example` files, and added to both local `.env` / `.env.local` files (gitignored) for
this machine — `DATABASE_URL` had to be copied into `frontend/.env.local` specifically,
since Next reads env from the app directory and the repo-root copy alone isn't visible to
`next dev` or the Next build.

### Left to do before this can be called deployed

1. The dashboard screenshot noted above.
2. Generate **production** values for all six vars (not the local-dev ones committed to
   gitignored files here) and add them to the Coolify app as runtime, non-preview
   variables — `ADMIN_SESSION_SECRET` and `STATS_SALT` via `openssl rand -hex 32`, a real
   `ADMIN_PASSWORD`, and `DATABASE_URL` is already known-good (same server Phase 9 was
   built against).
3. Push to `main` and let the existing GitHub Actions workflow deploy it, then repeat the
   curl-based auth/degrade checks against the live domain the way Phase 7/8 did.

## Phase 8 — Live progress + API protection (2026-09-20)

Two production problems, both in the backend path: the progress bar went blind the
moment the upload finished (an indeterminate pulse for the whole server-side job, with no
notion of "file 2 of 5" anywhere in the system), and the API was completely open to
anything that was not a browser.

### What is now true

**Live progress, end to end.** The client generates a job id, opens
`GET /progress/{id}` (SSE), then posts with `X-Job-Id`. All seven backend tools report
file-level progress, and five of them report intra-file percentages:

| Tool | Where the numbers come from |
|---|---|
| Compress | Ghostscript's `Page N` lines (`-dQUIET` removed) plus a fixed weighted cursor over survey / fonts / verify / rewrite / ghostscript |
| OCR | An OCRmyPDF `--plugin` (`app/tools/ocr_progress.py`) emitting JSON on stderr |
| PDF→Word | `pdf2docx_cli` counting `Page.parse` and `Page.make_docx`, weighted 0.8 / 0.2 |
| PDF→Markdown | `anydoc_cli` counting files through the batch |
| Protect / Unlock / extract-images | File-level only — they are milliseconds-scale per file |

**Cancel works, on both sides.** `ToolShell.handleCancel` aborts and resets the phase
itself, and the service loops call `progress.stop_if_cancelled()` between files, so an
abandoned batch stops on the server too rather than running to completion for nobody.

**The API is a cost gate.** Every processing endpoint needs a short-lived HMAC bearer
token minted by the frontend's `/api/token`, and is rate-limited per IP. `/health` and
`GET /ocr/languages` are open. It stops scripted third-party use; it does not stop a token
copied out of devtools, and nothing short of accounts would — that sentence is in
`app/services/auth.py` so nobody later mistakes it for authentication.

### Decisions worth remembering

- **The batched POST stayed.** Splitting into one request per file would have given
  file-level progress for free, but it would have broken the batched anydoc call
  PDF→Markdown depends on, lost server-side zipping and Compress's size-header
  aggregation, and multiplied the request count. File-level events come off the progress
  registry at near-zero extra cost instead.
- **`fetch` + `ReadableStream`, not `EventSource`.** `EventSource` cannot send an
  `Authorization` header, so this is the only reason `/progress` can be authenticated at
  all. It also shares the run's `AbortController` and has no auto-reconnect to suppress.
- **Latest-value snapshot, not a queue** (`app/services/progress.py`). Progress is state,
  not a log: overwrite-and-`set()` coalesces for free and cannot back-pressure a
  subprocess read pump.
- **The publisher travels by `ContextVar`**, bound by the `job_publisher` dependency —
  seven endpoint signatures would still not have reached `runner.run()`. `test_progress.py`
  asserts it survives dependency → endpoint → service → `to_thread`.
- **Progress can never fail a request.** Every path degrades to a no-op publisher, and the
  frontend bridge never rejects: the run's promise is the upload alone.
- **The bar is batch-wide and monotonic.** A per-file percentage that snapped back to zero
  four times in a five-file run reads worse than one that climbs; Compress's cursor
  fast-forwards over skipped steps rather than re-normalising, because re-normalising makes
  it jump *backwards*, which reads as broken.

### Three things that turned out differently than expected

1. **Dropping OCRmyPDF's `--quiet` does nothing.** `ocrmypdf/__main__.py` disables the
   progress bar whenever stderr is not a TTY, which under a pipe is always. There is no
   flag combination that works; the `--plugin` + `get_progressbar_class` hook is the
   supported route, and the plugin deliberately ignores the `disable=True` OCRmyPDF passes
   it. `--quiet` **stays**.
2. **Cancellation had to be bound unconditionally.** First cut attached the
   `is_disconnected` probe only when a valid `X-Job-Id` claimed a channel, which quietly
   made teardown a feature of progress rather than of cancellation. It is now bound even
   with the null publisher.
3. **The runner's pending-line buffer needed splitting, not flushing.** Appending a whole
   64 KiB read chunk before checking the cap let the buffer reach 128 KiB; it now emits in
   exact `MAX_PENDING_LINE` pieces. Caught by `test_runner_streaming.py`.

### The constraint to remember

`runner._slots`, `ratelimit._windows` and `progress.registry` are all **per-process**, and
correct only because `backend/Dockerfile` runs uvicorn with `--workers 1`. Two workers
would silently double every ceiling. The job semaphore already depended on this before
Phase 8; two more things depend on it now.

`FORWARDED_ALLOW_IPS` is the other one to remember: uvicorn's default trusts only
`127.0.0.1`, Traefik connects from a Docker bridge address, so without it
`request.client.host` is *Traefik* for every visitor and the whole site shares one
rate-limit bucket. `/health` echoes the observed client address specifically so this is
one curl away from being obvious.

### Tests

**166 passed, 0 skipped** in `docker compose --profile test run --rm backend-tests` (was
107). New files: `test_runner_streaming.py`, `test_progress.py`, `test_auth.py`,
`test_rate_limit.py`, `test_gs_progress.py`, `test_ocr_plugin.py`, `test_shims.py`.

Two existing things needed changing, both anticipated: `conftest.py`'s session `client`
fixture now mints a long-TTL token so all 166 tests exercise the real auth path, with an
autouse fixture resetting the rate limiter between them (otherwise the suite limits
itself around test 20); and `test_compress.py`'s `fonts.subset` stand-in needed `**kwargs`
to absorb the new `on_step`. A `requires_ocrmypdf` marker was also added — three OCR tests
were failing rather than skipping on a machine that has Tesseract but no `ocrmypdf` on
PATH.

### Verified locally against `docker compose up`

`/health` reports `auth`/`jobs`/`streams`/`client`; no token → `401 auth_required`;
`POST /api/token` mints; a three-file OCR streams `hello` → state frames climbing through
files 1-3 → `end{done}` while the POST still returns its zip; Compress on a scan
fast-forwards to the Ghostscript step and ticks per page; PDF→Word reports OCR then
rebuild; the other four tools report file-level progress; 25 POSTs in a minute → `429`
with `Retry-After`; a third concurrent OCR shows `queued` then `running`; the per-IP
stream cap holds at 4 and a 429 there does not touch processing; an aborted batch logs
"client disconnected; abandoning the rest of the batch" and stops early.
`npm run lint`, `npx tsc --noEmit` and `npm run build` are all clean.

### Deployed and verified in production (2026-09-20)

`API_TOKEN_SECRET` (a fresh `openssl rand -hex 32`, **not** the one in the local `.env`)
and `FORWARDED_ALLOW_IPS` were added to the Coolify app as runtime, non-preview variables
via the API, then `main` was pushed and the usual GitHub Actions workflow deployed it.
Coolify automatically mirrors each new variable into its preview environment too; those
copies are inert, this app has no preview deployments.

Checked against the live domains:

- `/health` → `{"status":"ok","auth":"on","jobs":0,"streams":0,"clients":N,"client":"<a real public IP>"}`.
  **That last field is the proxy-headers proof**: it shows the caller's own public address,
  not a `172.x` Docker bridge one, so uvicorn is trusting Traefik's headers and per-IP
  limits are really per IP. If it ever reads as a bridge address again,
  `FORWARDED_ALLOW_IPS` has been lost and the whole site is sharing one bucket.
- `POST /compress` with no token → `401 auth_required`; `GET /ocr/languages` → 200.
- `POST https://pdfkit.zeeshanai.cloud/api/token` mints, and the backend accepts it —
  so both services genuinely hold the same secret.
- A three-file OCR with `X-Job-Id`: `hello` → state frames climbing 0 → 100 across files
  1-3 → `end{done}`, **arriving live rather than buffered**, and the POST still returned
  its zip. Traefik is not buffering the event stream.
- 20 job requests in a minute → `429 rate_limited` with `Retry-After`, keyed on the real
  public address.

### Left to do

**A browser pass**, which is the one thing curl cannot stand in for: all seven backend
tools with three files each — the file counter, the climbing bar, Cancel mid-OCR returning
to an intact file list, and `/progress` blocked in devtools falling back to the
indeterminate bar. Every one of these is verified server-side; what is unverified is how
they look.

Two smaller ones, both low-risk: a ten-minute idle progress stream to confirm the
15-second keep-alives hold through Traefik without a 502, and the phone-tether half of the
client-IP check (the public address already observed makes this close to redundant).

### A rough edge worth knowing about

With `API_TOKEN_SECRET` unset, the two services disagree about what to do. The backend
degrades to open and says so loudly (startup warning, `"auth":"off"` on `/health`); the
frontend's `/api/token` returns 503, `getToken()` throws, and **every backend tool fails
with a toast**. So a half-configured deploy is an outage rather than a warning. Making the
mint route return a sentinel the client sends as no header at all would restore the
symmetry. Not done — it is beyond what the phase doc specifies, and the variable is set
now — but it is the first thing to fix if this is ever deployed somewhere new.

## Phase 7 — Deploy to Coolify (2026-09-20)

Deployed as a single **Docker Compose** resource (`b1s6cgebvkpxxrzzjp2d2244`, project
"PDFKit") on the existing Coolify instance on the Hostinger VPS, via the
`add-app-to-coolify` skill driving Coolify's REST API directly (`POST
/applications/public` with `build_pack: "dockercompose"` — there is no separate
"create docker-compose app" endpoint; a single `docker_compose_domains` array maps each
compose service to its own domain).

**Two real deploy failures, both fixed and now permanent in the repo:**

1. **`npm ci` failed in the frontend build**: `Missing: @emnapi/runtime, @emnapi/core from
   lock file`. The committed lockfile was last resolved on a Windows dev machine, which
   drops Linux-only optional deps. Fixed by switching `frontend/Dockerfile`'s install step
   from `npm ci` to `npm install` — non-strict, reconciles in-container, no lockfile
   regeneration needed. Don't revert this to `npm ci` without regenerating the lockfile on
   Linux first.
2. **Backend container failed to start**: `Bind for 0.0.0.0:8000 failed: port is already
   allocated`. `docker-compose.yml` published `3000:3000` / `8000:8000` straight to the
   host, and host port 8000 was already held by Coolify's own dashboard/API container —
   this was never a problem locally because nothing else on a dev machine binds 8000.
   Traefik only needs the internal Docker network to reach a container (it already had the
   right labels), so both services now use `expose` instead of `ports`.
   `docker-compose.override.yml` (new, gitignored-adjacent but committed) adds the host
   port mappings back — `docker compose up` merges override files automatically, so local
   dev is unaffected, but Coolify (pointed only at `docker-compose.yml`) never sees them.

**Also fixed as part of this phase:** `NEXT_PUBLIC_SITE_URL` wasn't wired into
`docker-compose.yml`'s frontend `build.args` at all (only `NEXT_PUBLIC_API_URL` was) —
the open item flagged at the end of the SEO pass. Added to both `docker-compose.yml` and
`frontend/Dockerfile`'s `ARG`/`ENV` pair; verified post-deploy that canonical/OG URLs and
the sitemap resolve to `pdfkit.zeeshanai.cloud`, not `localhost:3000`.

**Traefik gotchas the phase doc called out — both turned out to be non-issues on this
instance**: no body-size-limiting middleware and no custom read/idle timeout are
configured anywhere in `/data/coolify/proxy/dynamic/`, so the 50 MB upload cap and the
~900 s worst-case PDF-to-Word-with-OCR request are both bounded only by the backend's own
timeouts, which is what we want (a `504 processing_timed_out` from the app, never a
proxy-level cutoff). Confirmed by running a real `ocr=auto` PDF-to-Word conversion against
the public domain rather than by inspecting config alone.

**Auto-deploy**: GitHub Actions (`.github/workflows/deploy.yml`), not Coolify's built-in
git-push webhook — retries with backoff against `POST /api/v1/deploy`, because the raw
webhook is fire-once and silently drops a deploy on a transient 502. Coolify's own
"Auto Deploy" toggle is off for this app so the two can't double-fire. Repo secrets
`COOLIFY_API_TOKEN` (deploy-scoped) and `COOLIFY_APP_UUID` are set. Verified live: the push
that added the workflow file was itself the trigger, and it deployed successfully.

**Verified against the public domains**: landing page 200 over HTTPS with a real Let's
Encrypt cert (both `pdfkit.zeeshanai.cloud` and `api.pdfkit.zeeshanai.cloud`); `/health` →
`{"status":"ok"}`; canonical/OG/sitemap all resolve to the real domain; CORS preflight from
`https://pdfkit.zeeshanai.cloud` succeeds; Compress and OCR both succeed against the public
API (OCR still lists all 14 languages); the `/tmp/pdfkit` tmpfs mount kept its
`pdfkit:pdfkit` (1001:1001) ownership through Coolify's compose handling — the Phase 4
regression this step exists to catch; a real PDF-to-Word `ocr=auto` job completed in ~6 s
with no proxy-level interruption; `/contact` submitted for real and returned
`{"success":true}` (the n8n webhook and Upstash rate-limit vars were already sitting in
`.env.local` from earlier local testing, so they went straight into Coolify rather than
being left unset). VPS disk: 49% used, 50 GB free, weekly cleanup cron still active.

## OCR languages: 1 → 14 (2026-09-19)

The backend image shipped only `eng`. It now installs 13 more: Arabic, Chinese
(Simplified), Dutch, French, German, Hindi, Italian, Japanese, Portuguese, Russian,
Spanish, Swedish and Urdu. Measured cost: the image went **1.24 GB → 1.27 GB** (+26 MB),
tessdata **15 MB → 46 MB**. Each model is 0.5-6 MB, so more are cheap; `tesseract-ocr-all`
(162 packages, ~668 MB) is not, and should stay off the table.

Three changes, and only the first is needed to add a fourteenth:

1. `backend/Dockerfile` — one `tesseract-ocr-<code>` line per model. Note the package name
   and the Tesseract code differ for some: `tesseract-ocr-chi-sim` gives `chi_sim`.
2. `LANGUAGE_NAMES` in `app/services/ocr.py` — `urd` was missing and would have rendered
   as its own code. Everything else was already listed.
3. `_parse_langs` now sorts by **display name, not code**. With one language that was
   invisible; with fourteen, sorting by code puts German above English and Dutch after
   Japanese. `test_parse_langs_skips_the_header_and_non_languages` asserts the new order.

`OcrLanguagePicker` (shared by OCR, PDF to Word and PDF to Markdown) grew a search box and
pins the selected languages above the list, both switched on only above 8 installed models
so a single-language deployment still renders exactly as it did. Pinning matters because a
filter would otherwise hide a checked language and read as a deselection.

Verified: suite **107 passed**; `GET /ocr/languages` returns all 14, name-sorted, `osd`
excluded, Urdu named; and `POST /ocr` against `sample-scanned.pdf` returns 200 with a real
PDF for `urd`, `chi_sim` and `spa,eng` — so the models load, they are not merely listed.

Driven in a real browser on `/ocr-pdf` (the built frontend, not dev): all 14 rows render
with English pinned and the other 13 name-sorted; typing `urd` narrows the list to Urdu
while the checked English stays pinned and visible; `klingon` shows the empty state;
picking Urdu and Spanish gives "3 of 3", pins the three in selection order under "Your
picks, strongest first." and disables the other 11; and the CTA ran a real `eng,urd,spa`
job through to the download panel.

One gotcha for the next session: serve the frontend on **port 3000**. `CORS_ORIGINS`
defaults to `localhost:3000` only, so on any other port `/ocr/languages` fails CORS and the
picker silently falls back to English — which looks exactly like the models being missing.

## PDF to Word and PDF to Markdown (2026-09-19)

Two tools added, taking the registry to **12**. Both are backend tools and both follow the
existing backend-tool pattern exactly, so nothing about `ToolShell`, `lib/api.ts` or the SEO
layer changed shape.

| Tool | Route | Endpoint | Engine |
|---|---|---|---|
| PDF to Word | `/pdf-to-word` | `POST /convert/word` | `pdf2docx convert`, via its CLI |
| PDF to Markdown | `/pdf-to-markdown` | `POST /convert/markdown` | anydoc, via a subprocess shim |

Both take an `ocr` field (`off` / `auto`) and the same `languages` field `/ocr` takes.

### The two findings that shaped the design

Both were found by running the tools, not by reading docs, and both are the reason the code
looks the way it does. **Do not "simplify" either one away.**

1. **anydoc never accepts an OCR'd page.** It reports `NeedsOcrError` with the exact 1-based
   page numbers, and OCRmyPDF's text layer does *not* change its mind — `pdftotext` and pypdf
   both read the recognised text out of the same file, but anydoc still classifies the page
   as a scan. So "OCR it and convert again" does not work, and the plan's original two-pass
   design had to grow a page-level stage.
2. **pdf2docx ignores invisible text.** OCRmyPDF writes its layer in rendering mode 3 so the
   page still looks like the scan; pdf2docx is a *layout* parser, so by its measure the text
   is not there, and a scanned PDF converted to Word came back as a picture with **zero**
   characters in it. Making the text visible and dropping the page image behind it turns the
   same file into 1650 characters of editable Word content.

### How each tool works

**PDF to Markdown** (`app/services/markdown.py`)

1. Convert the whole document in one anydoc call. If it succeeds — the born-digital case, and
   the common one — that is the best result available, because a table or paragraph spanning
   a page break stays in one piece. Verified: the 5-page text fixture comes back with real
   `#` and `##` headings.
2. On `NeedsOcr` with `ocr=auto`: OCR the whole file once with `--skip-text`, then assemble
   page by page — the pages anydoc named are filled in from the recognised text layer
   (`text_layer.page_texts`, i.e. pypdf), and every other page is split out with pypdf and
   converted by anydoc on its own so its structure survives.
3. The per-page conversions share **one** subprocess. The shim takes a batch, so a 50-page
   mixed document pays for one interpreter start, not fifty.
4. A page neither route can read becomes `_Page N could not be read._` rather than vanishing.
   If *every* page is unreadable it is a `422 needs_ocr` instead, because there is no
   document to hand back.

**PDF to Word** (`app/services/word.py`) — `ensure_readable`, then with `ocr=auto`:
`pages_without_text` on the **input** (after OCR every page has text, so asking later tells
you nothing) → `ocr_to_path` → `reveal_text` on just those pages → `pdf2docx convert`.
`reveal_text` returning False is not an error; the untouched OCR'd file is converted instead.

### Decisions

- **pdf2docx runs as a subprocess, never imported.** `runner.py` can only enforce a timeout
  on something it can kill, and it keeps the AGPL PyMuPDF engine in its own process — the
  same posture the image already has with Ghostscript. Same reasoning for the anydoc shim,
  which additionally means a panic in its Rust core costs one request, not the event loop.
- **`app/tools/anydoc_cli.py` reports per-file status as JSON lines and exits 0.** The exit
  code says whether the *tool ran*; whether a given document converted is per-item data. That
  is what lets one process convert a batch of pages and report a different outcome for each.
- **`ocr` defaults differ per tool, deliberately.** Word defaults to `off` (matching the
  iLovePDF reference screenshot) because pdf2docx produces a document either way. Markdown
  defaults to `auto` because anydoc refuses a scan outright, so defaulting it off would turn
  the commonest scanned document into an error instead of a result.
- **`reveal_text` only touches pages that had no text of their own**, so a figure on a
  born-digital page is never stripped out from under its caption.
- **Download names drop the suffix**: `report.pdf` → `report.docx`, not `report-word.docx`.
  The extension already changed, so there is nothing to disambiguate (`convert_name` in
  `responses.py`, beside the existing `derive_name`).
- **The scanned-file hint nudges, it does not switch modes.** `useScannedProbe` samples up to
  8 pages with pdf.js `getTextContent` and the panel says "one of these files looks like a
  scan". Turning OCR on by itself would silently multiply the wait.

### Frontend

- `lib/tools.ts` (+2 entries, `ToolId` union), `lib/seo/tool-content.ts` (+2 `ToolSeo`
  entries — the `Record<ToolId, ToolSeo>` type makes this a compile error until it is done),
  two routes, two workspaces under `components/tools/`.
- **Shared, new**: `components/tool/ocr-language-picker.tsx` (lifted out of `ocr-options.tsx`
  so OCR, Word and Markdown share one picker), `components/tool/ocr-mode-cards.tsx`,
  `components/tool/use-scanned-probe.ts`, `lib/pdf/text-layer.ts`.
  `use-ocr-languages.ts` **moved** from `components/tools/ocr/` to `components/tool/`.
- Counts that were written out in prose are now derived from `TOOLS.length`: `llms.txt` and
  the footer. The contact page's "there are ten tools" line was reworded to not carry a
  number at all.

### A real bug this found

`useScannedProbe` originally cleared a `live` flag in its effect cleanup. `files` gets a new
identity the moment a page count or thumbnail arrives, so the effect re-ran while the first
probe was still going, cancelled it, and then skipped re-probing because the id was already
in `started` — the answer was discarded and never recomputed, and the banner never appeared.
Only unmounting may invalidate a probe now. The comment in the file says so; keep it.

### Verification

`docker compose --profile test run --rm backend-tests` → **92 passed** (53 before this work,
plus `tests/test_convert.py`). The tests that matter: a mixed document (3 born-digital pages
+ 1 scan) comes back with both "Page 1 of 3" from anydoc *and* the OCR'd text, and no
"could not be read" marker; and the Word scan test asserts **both** halves — no text without
OCR, text with it — so a regression in `reveal_text` cannot pass silently.

Against the **runtime** image with the committed fixtures: born-digital Markdown carries real
headings; `sample-scanned.pdf` with `ocr=off` → `422 needs_ocr`, with `ocr=auto` → recognised
text in 1.8 s; Word gives 4170 characters on the text fixture, 0 on the scan without OCR and
1650 with it (and the OCR'd .docx is 38 KB against 238 KB, because the page image is gone);
both endpoints 422 on `sample-protected.pdf`; two files zip as `pdfkit-word.zip` /
`pdfkit-markdown.zip`; `/tmp/pdfkit` empty afterwards.

Frontend: `npm run lint`, `npx tsc --noEmit` and a clean `npm run build` (26 routes) all
pass. Both tools were then driven through headless Chromium against `next start` + the
Dockerised backend, capturing `URL.createObjectURL` and reading the downloaded bytes back in
Node — 10/10 checks, plus 6/6 regression checks covering the landing grid (12 links), the
refactored OCR tool end to end, the non-PDF guard (0 backend requests) and the
encrypted-PDF guard. Both new routes serve exactly one `h1`, ~920 crawlable words and one
JSON-LD block, and neither overflows at 390 px.

The harness lives in the session scratchpad, not the repo, as in Phase 6.

## Fix: PDF to Word ran the words together (post-Phase 6)

Reported against a bank certificate (`PDFKit Samples/HBL_CC_Tax_Certificate.pdf`):
the .docx came out as `Thisistocertifythat…`. iLovePDF handled the same file
correctly, so it was ours.

**Cause.** A PDF need not write a space character. This one does not write a
single one: each word is its own `Tj`, moved into place by a `Td` offset, and
the reader is expected to infer the gap from the geometry. MuPDF does infer it
— `page.get_text()` returns the sentence spaced correctly — but because each
word arrived with its own positioning, MuPDF puts each synthesised space in a
**span of its own**. pdf2docx then drops every span whose text is blank and
which carries no styling (`pdf2docx/text/Spans.py`, `Spans.restore`), on the
assumption that such a span is a stray blank. On this document that is every
space in the file.

Nothing in our code was wrong, which is why it took reading pdf2docx to find:
real spaces inside a `Tj` survived, so the header lines ("Dated : 05/07/2026",
"Advance Tax Certificate") looked fine and only the body was affected.

**Fix.** `app/tools/pdf2docx_cli.py` — a shim that patches `Spans.restore` to
keep a blank span when it sits *between* two spans with content, and to go on
discarding the ones at either end. `app/services/word.py` now runs
`python -m app.tools.pdf2docx_cli <in> <out>` instead of pdf2docx's own
`pdf2docx convert`; it is still a subprocess, so the runner's timeout and the
AGPL separation are unchanged. This follows the `app/tools/anydoc_cli.py`
pattern already in the tree.

**Why interior-only is the safe form of the patch.** A span between two others
lies inside the line's existing bounding box, so no line's geometry moves — and
pdf2docx's paragraph and table detection works on line bboxes. That was checked
rather than assumed: the line bboxes come out **bit-identical** with and without
the shim on all five documents below, so only the text of the runs differs.

| Document | Line bboxes | Paragraph/table structure | Text |
|---|---|---|---|
| HBL_CC_Tax_Certificate (the report) | identical | identical | spaces restored |
| HBL_Tax_Certificate_TDR | identical | identical | spaces restored |
| BrainyDocs profile (4 MB) | identical | identical | unchanged |
| `sample-text.pdf` fixture | identical | identical | unchanged |
| Folksam MC, pp. 5–14 (280 paragraphs) | identical | identical | unchanged |

**A test that was lying.** `docx_text()` in `tests/test_convert.py` flattened the
document by replacing every XML tag with a space — so it invented a space at
every run boundary and reported this bug's output as correctly spaced. It now
concatenates the `<w:t>` nodes with nothing between them, which is what Word
renders. The new `test_word_keeps_the_spaces_a_pdf_only_implies` was confirmed
to fail (`assert 'Spaces are implied here' in 'Spacesareimpliedhere'`) with the
shim disabled. Its fixture, `build_gapped_text_pdf()`, is a Courier document
whose content stream contains no space character at all.

Suite: 107 passed. Verified end-to-end against the live container:
`POST /convert/word` on the reported file now returns properly spaced text.

**One thing that is not a bug:** the output reads `MUHAMMAD ZEESHAN ALT AF`. The
PDF places a full word-gap between `ALT` and `AF`, so every geometry-honouring
reader splits it — pypdf does too. The name is broken in the source.

## Contact & Privacy pages (2026-09-19)

Built with the `nextjs-contact-form` skill. Two new routes, both in the `(site)` group so
they inherit the footer.

**`/contact`** — Name + Email + Message, posting to `app/api/contact/route.ts`, which
forwards to an n8n webhook with an `x-api-key` header.

- **Progressive enhancement is load-bearing, don't simplify it.** The `<form>` keeps a real
  `action="/api/contact" method="post"` *and* an `onSubmit` fetch. A `"use client"` form
  inside a server component can render correct HTML and still fail to hydrate silently —
  removing the native path turns that into dead UI with no error. The route therefore parses
  both JSON and url-encoded bodies, and answers native posts with a **303** (not 307) so the
  browser re-fetches with GET instead of replaying the POST.
- **Honeypot** is named `hp_field` on purpose. A semantic name (`company`, `phone`, …) would
  be filled by browser/Google autofill and flag real people as bots. Tripping it returns
  success and sends nothing, so bots get no signal to adapt.
- **Rate limit**: `lib/rate-limit.ts`, Upstash sliding window, 5 per 10 min per IP, prefix
  `pdfkit:contact`. It **fails open** when the Upstash vars are absent — a misconfigured env
  must never hard-break the form. The limit check runs *before* the webhook-config check,
  which is also how it can be tested without sending mail.
- `components/ui/textarea.tsx` was added (shadcn had not installed one); the form otherwise
  uses the project's `Input`, `Label`, `Button`.

**`/privacy`** — Privacy policy. The "runs in your browser" and "uses the server" tool lists
are derived from `TOOLS[].runsIn`, so they cannot drift from the registry.

**Wiring** — Contact is in the header (hidden below `sm`, so it is also in the "All tools"
dropdown behind a separator) and, with Privacy, in a new secondary column in the footer. The
footer gained the "Developed with 💖 by [Zeeshan Altaf](https://zeeshanai.cloud)" credit.
Both routes are in `sitemap.ts`; `robots.ts` now disallows `/api/`.

**Env** — four new server-only vars, none `NEXT_PUBLIC_` (they would leak into the client
bundle): `N8N_CONTACT_WEBHOOK_URL`, `N8N_API_KEY`, `UPSTASH_REDIS_REST_URL`,
`UPSTASH_REDIS_REST_TOKEN`. They live in `frontend/.env.local` (Next reads from the app dir,
not the repo root) and are documented in both `.env.example` files. They are **runtime** env,
read per-request in the route handler — passed through `docker-compose.yml`'s frontend
`environment:` block, not as build args.

**Verified against `next start`** — honeypot returns 200 and sends nothing; missing fields
400; bad email 400; native url-encoded post 303 → `/contact?error=email`; rate limiter
allows 5 then 429s on the 6th for a fixed IP; Upstash `/ping` → PONG; one real submission
returned `{"success":true}` from the live n8n webhook. All three of `/`, `/contact`,
`/privacy` render exactly one `h1`, and the header/footer links resolve on tool pages too.
`next build`, `tsc --noEmit` and `eslint` all clean.


## SEO pass (2026-09-19)

Audited with the `seo-audit` skill against the real built output (`next build` + `next start`
+ curl), not against source.

**The finding that mattered:** every tool route served **13 words of body text and no heading
at all**. `ToolPage` is `dynamic(..., { ssr: false })`, so the `h1` and description existed
only after hydration — the ten pages that should rank for "merge pdf", "compress pdf" and so
on were effectively blank, with just 4 crawlable internal links each. The homepage was fine
throughout (288 words, clean hierarchy, all 10 tool links).

**What changed**

- `lib/seo/tool-content.ts` — new. Per-tool search copy: `title`, `h1`, `howTo`, `intro`,
  `steps`, `faqs`. Typed `Record<ToolId, ToolSeo>`, so a new tool will not compile without one.
- `components/seo/tool-seo-section.tsx` — server-rendered section below each workspace,
  carrying the page's single `h1`, the step list, the FAQs and links to all nine other tools.
- `components/seo/json-ld.tsx` — `WebSite` + `WebApplication` on the homepage;
  `BreadcrumbList` + `WebApplication` + `FAQPage` per tool. Rendered server-side, so it is in
  the HTML. Deliberately no `HowTo` (Google retired those rich results in 2023).
- `app/robots.ts`, `app/sitemap.ts`, `app/manifest.ts` — new, all generated from the registry.
- `app/llms.txt/route.ts` — new, `force-static`. Tool list, privacy model and every FAQ, also
  generated from the registry so it cannot drift.
- Metadata titles now come from `TOOL_SEO[id].title` ("Merge PDF Files Online, Free and
  Private" rather than "Merge PDF"), using ~47 of the ~60 characters a SERP shows.
- Workspace headings demoted `h1` → `h2` (`file-dropzone`, `options-sidebar`, `result-view`,
  `tool-shell` error state) so the one `h1` per page is the server-rendered one.
- Footer added to `app/(tools)/layout.tsx`; `ToolPage` gained a `min-h-[calc(100svh-4rem)]`
  floor so the workspace still owns the first viewport.
- Protect's registry description lengthened (66 chars was under the ~70 floor); OG image
  bottom line now opens with a call to action.

**Verified after the change** — all 11 routes: title 45-52 chars, description 73-125, exactly
one `h1`, 288-352 body words, 11 internal links, exactly one JSON-LD block, and every
canonical matches its sitemap entry (the homepage is `SITE_URL` with **no** trailing slash,
which is what Next resolves `canonical: "/"` to). `next build` and `eslint` both clean.

**Open item for Phase 7:** `SITE_URL` falls back to `http://localhost:3000`. Coolify must set
`NEXT_PUBLIC_SITE_URL` **at build time** — it is inlined, not read at runtime. If it is
missing, every canonical, OG URL, sitemap entry and llms.txt link ships pointing at localhost.

## Tools live so far

| Tool | Route | State |
|---|---|---|
| Merge PDF | `/merge-pdf` | ✅ real, browser-side |
| Rotate PDF | `/rotate-pdf` | ✅ real, browser-side |
| Split PDF | `/split-pdf` | ✅ real, browser-side |
| Organize PDF | `/organize-pdf` | ✅ real, browser-side |
| Page numbers | `/add-page-numbers` | ✅ real, browser-side |
| PDF to JPG | `/pdf-to-jpg` | ✅ both modes — pages in the browser, extract-images on the backend |
| Compress PDF | `/compress-pdf` | ✅ real, `POST /compress` |
| Protect PDF | `/protect-pdf` | ✅ real, `POST /protect` |
| Unlock PDF | `/unlock-pdf` | ✅ real, `POST /unlock`, one request per file |
| OCR PDF | `/ocr-pdf` | ✅ real, `POST /ocr` + `GET /ocr/languages` |
| PDF to Word | `/pdf-to-word` | ✅ real, `POST /convert/word` (pdf2docx) |
| PDF to Markdown | `/pdf-to-markdown` | ✅ real, `POST /convert/markdown` (anydoc) |

## Phase checklist

- [x] Phase 0 — Scaffold (git, Next.js, FastAPI, docker-compose, README)
- [x] Phase 1 — Shared UI shell (tool registry, landing page, `ToolShell`, dropzone, grids, result view)
- [x] Phase 2 — Browser tools batch 1 (Merge, Rotate, Split)
- [x] Phase 3 — Browser tools batch 2 (PDF→JPG page mode, Organize, Page Numbers)
- [x] Phase 4 — Backend services (Compress, Protect, Unlock, OCR, Extract images) + tests
- [x] Phase 5 — Wire backend tools into UI — **feature-complete**
- [x] Phase 6 — Polish (responsive, metadata, edge cases, a11y) — **deploy-ready**
- [x] Phase 7 — Deploy to Coolify — **live** at pdfkit.zeeshanai.cloud

## What Phase 1 built

All under `frontend/`.

**Registry and app chrome**
- `lib/tools.ts` — the 10-tool registry plus `getTool` / `getToolBySlug` / `relatedTools` /
  `toolMetadata` and the per-accent Tailwind classes. Fields are the planned ones plus
  `runsIn` (`browser | backend | hybrid`), which is what gates the 50 MB cap.
- `lib/constants.ts` (`APP_NAME`, tagline, `MAX_UPLOAD_BYTES`), `lib/format.ts`,
  `lib/download.ts`.
- `components/layout/` — `site-header` (brand, three quick links, "All tools" dropdown built
  from the registry, theme toggle), `site-footer`, `brand`.
- `components/theme-provider` + `theme-toggle` (next-themes, class strategy).
- Route groups: `app/(site)/` has the footer, `app/(tools)/` does not, so a tool workspace
  fills the viewport under the 64px header.

**Landing page** (`app/(site)/page.tsx`) — hero, the 10 `ToolCard`s driven by the registry
(each card says where it runs), and a "Built so your documents stay yours" section.

**Tool shell** (`components/tool/`)
- `tool-shell.tsx` — owns the state machine and the two-column layout. Status is derived,
  not stored: `phase` is `idle | processing | done | error`, and `idle` renders the dropzone
  or the canvas depending on whether there are files.
- `use-tool-files.ts` — the `{ id, file, name, size, pageCount, thumbnail, rotation, error }`
  list, validation, background page-count/thumbnail loading, reorder/sort/rotate/remove.
- `use-tool-pages.ts` — page-level state for the PageGrid tools, merging user edits
  (reorder, rotate, delete) with the current file list. **Deleted in Phase 3**; Organize owns
  that model now, in `components/tools/organize/organize-state.ts`.
- `file-dropzone`, `file-grid` / `file-card`, `page-grid` / `page-card`, `thumbnail`,
  `sortable-grid`, `add-files-button`, `sort-button`, `options-sidebar`, `processing-view`,
  `result-view`, `encrypted-notice`, `tool-shell-context`.
- `tool-page.tsx` / `tool-workspace.tsx` — the `next/dynamic` + `{ ssr: false }` boundary and
  the placeholder processing every stub route currently uses.

**Browser PDF layer** (`lib/pdf/`) — `pdfjs.ts` (worker wiring), `load.ts` (File → pdf.js
proxy or pdf-lib document, `PdfLoadError` with kind `encrypted | invalid | too-large`,
per-File document cache and release), `thumbnails.ts` (page → JPEG data URL, cached per
file + page + rotation + size).

## Decisions made in Phase 1

- **Accent is a single `--brand` token** in `app/globals.css`: a deep teal,
  `oklch(0.48 0.1 200)` light / `oklch(0.74 0.11 200)` dark, deliberately not iLovePDF red.
  `--primary` and `--ring` both point at it, so every shadcn component inherits it, and
  `--color-brand` exposes `bg-brand` / `text-brand`. Changing those two lines re-themes the
  whole app.
- **Tool cards are colour-coded by category, not per tool**: teal for the page-editing tools,
  indigo for Compress, amber for the converters, rose for the password tools. Keeps the grid
  scannable without turning it into a paint chart.
- **Rotation is a CSS transform on the thumbnail**, never a re-render. A quarter turn also
  applies `scale(0.75)` (the thumbnail frame's aspect ratio) or the preview gets clipped.
- **Single-file tools replace rather than append.** Dropping a second file on Split swaps it.
- **`lib/format.ts` regex** uses `/\.[a-z0-9]+$/i`; do not "fix" it to a character class with
  an escaped backslash, bash heredocs mangle that.
- **pdf-lib cannot be trusted to report encryption.** With the AES-256 file qpdf produces it
  throws a plain parse error, not `EncryptedPDFError`, so `load.ts` also scans the bytes for
  an `/Encrypt` entry before calling a file corrupt. pdf.js does raise `PasswordException`
  correctly, and it is what the file list probes with first.
- `@dnd-kit/modifiers` is **not** installed, so `SortableGrid` has no `restrictToParentElement`.
  Add the package if a future phase needs it (remember the Linux lockfile rule).
- Deleted the unused create-next-app SVGs and `app/page.tsx` (moved to `app/(site)/page.tsx`).
- `public/pdf.worker.min.mjs` is now in the eslint ignore list; it was contributing ~1570
  warnings and 6 errors to `npm run lint`.

## Phase 1 verification results

`npm run lint` and `npm run build` are both clean (12 static routes). The rest was driven
through a real headless Chrome (`browse ... --local`) against `npm run dev`:

- Landing page renders 10 cards from the registry, in light and dark, no horizontal scroll.
- Merge: two PDFs dropped in, thumbnails and `3.7 KB · 5 pages` metadata correct; A→Z sort
  reorders and the button flips to Z→A; remove drops the file and the sidebar recounts;
  CTA → processing → "Merge PDF is done" with Download, Start over and three "Continue to"
  links; Start over returns to the select screen.
- Organize: 7 pages from 2 files in one grid with A/B source chips and positions 1-7; rotate
  applies `rotate(90deg) scale(0.75)`; delete renumbers the rest.
- `sample-protected.pdf` → "This PDF is password protected" banner with a working
  `/unlock-pdf` link, the card shows the error, and the CTA is disabled.
- `notes.txt` → toast "notes.txt is not a PDF."
- A 52 MB file on Compress → toast "huge.pdf is over the 50 MB limit." (Browser tools are
  not capped.)
- Compress stub: stage text goes "Uploading" with the bar filling 0→100%, then
  "Running Compress PDF" with the indeterminate bar.
- 390px viewport: sidebar stacks under the grid, `scrollWidth === clientWidth`, nothing
  overflows.

## What Phase 2 built

**PDF operations** (`frontend/lib/pdf/`)
- `save.ts` — `pdfToBlob`, the one place a pdf-lib document becomes a downloadable blob.
- `zip.ts` — `zipBlobs`, used by any tool that produces more than one file. De-duplicates
  entry names (`a.pdf`, `a (2).pdf`) because a zip entry silently overwrites otherwise.
- `merge.ts` — `mergePdfs(files, onProgress)`, `copyPages` in list order.
- `rotate.ts` — `rotatePdf(file, delta)`, adds the delta to each page's existing `/Rotate`.
  Exports `normalizeAngle`, which rounds to the nearest quarter turn.
- `split.ts` — the whole split model: `parsePageExpression`, `validateRanges`, `fixedRanges`,
  `planSplit` (pure, drives the preview and the error message) and `splitPdf` (does the work).

**Tool workspaces** (`frontend/components/tools/<tool>/`)
- `merge/` — `merge-workspace` + `merge-options` (numbered order list mirroring the grid).
- `rotate/` — `rotate-workspace`, `rotate-options` (Left/Right for all, per-file degree
  readout, "Reset all"), `rotate-file-action` (the per-card hover button).
- `split/` — `split-workspace`, `split-state` (panel state ⇄ `SplitInput`), `split-options`
  (Range | Pages tabs), `split-preview` (one card per output document, first…last page).

**Shell changes**
- `tool-page.tsx` is now the dispatcher: one `next/dynamic` + `{ ssr: false }` component per
  tool, so each route only downloads its own logic. Tools with no entry fall through to the
  Phase 1 placeholder.
- `tool-shell.tsx`'s `canSubmit` now also accepts a predicate over the readable files.
- `components/tool/page-thumbnail.tsx` — read-only, lazily rendered single-page preview.

## Decisions made in Phase 2

- **`canSubmit` became `boolean | ((files: ToolFile[]) => boolean)`.** The file list lives
  inside `ToolShell` but the CTA gate depends on it (Merge needs two files, Split validates
  its ranges against the real page count), and a predicate was much less invasive than
  lifting the file list out of the shell.
- **`planSplit` is pure and separate from `splitPdf`.** The sidebar's error text, the CTA
  gate and the canvas preview all call it, so they cannot disagree about what the current
  options mean.
- **Empty range bounds mean "the natural end"** — blank From is page 1, blank To is the last
  page, and the input placeholders show the value that will be used. Without this, a
  freshly-added range greets the user with a validation error before they have typed.
- **Split output naming**: `<base>-1-3.pdf` for a range, `<base>-page-5.pdf` for a single
  page, `<base>-split.pdf` when merged, `<base>-split.zip` for the archive.
- **ZIPs use DEFLATE level 1**, not the default 6 or STORE. PDF image data will not shrink,
  but pdf-lib's object streams do, and level 1 gets most of that without seconds of
  main-thread time.
- **Rotate includes unrotated files in the ZIP.** Asking for a set back and receiving only
  part of it is worse than a few bytes of redundancy.
- **Rotate's CTA is gated on at least one non-zero rotation**, so running it can never hand
  back the input unchanged.
- **`pdfToBlob` asserts `Uint8Array<ArrayBuffer>`.** TS 5.9 rejects pdf-lib's
  `Uint8Array<ArrayBufferLike>` as a `BlobPart` because the union admits `SharedArrayBuffer`;
  it never is one here, and asserting beats copying a file that can run to 50 MB.
- Split's panel state deliberately survives "Start over" — re-splitting several documents the
  same way is the common case, and the ranges are re-validated against the new page count.

## Phase 2 verification results

`npm run lint` and `npm run build` are clean (12 static routes). The tools were driven
through a real headless Chrome (`browse ... --local`) against `npm run dev`, and every
output blob was captured (by hooking `URL.createObjectURL`) and read back in Node with
pdf.js, so these are assertions about the actual bytes, not about the screen:

- **Merge** `sample-text.pdf` + `sample-scanned.pdf`, sorted A→Z (which swaps them) →
  7 pages: p1-p2 have no text (the scanned file), p3-p7 are "Page 1 of 5" … "Page 5 of 5"
  in order. Sort button flipped to Z→A.
- **Merge guard**: adding `sample-protected.pdf` shows the Phase 1 encrypted banner with the
  Unlock link, marks the card, and the CTA goes disabled — one readable file is not two.
- **Rotate**, one file: Right ×2 → sidebar reads 180°, thumbnail `rotate(180deg)`, CTA and
  "Reset all" enabled; Reset all → 0°, no transform, CTA disabled again.
- **Rotate**, two files with per-card buttons (text 180°, scanned 90°) → ZIP of
  `sample-text-rotated.pdf` (5 pages, all `rotate=180`, text intact) and
  `sample-scanned-rotated.pdf` (2 pages, all `rotate=90`).
- **Split, custom ranges** 1-2 and 4-5 → ZIP of `sample-text-1-2.pdf` (pages 1,2) and
  `sample-text-4-5.pdf` (pages 4,5); page 3 correctly absent.
- **Split, fixed every 2** on 5 pages → 3 PDFs: `1-2`, `3-4`, `page-5`.
- **Split, pages `1,3-5` + merge** → a single 4-page PDF containing pages 1, 3, 4, 5 in order.
- **Split validation** (each disables the CTA and shows the message in the sidebar, and the
  canvas falls back to a placeholder): `9` → "This PDF has 5 pages, so page 9 does not
  exist."; `abc` → "\"abc\" is not a page number or a range like 3-5."; `5-2` → "Range 5-2
  ends before it starts."; `0` → "Page numbers start at 1."; empty → "Enter the pages you
  want, for example 1,3-5."
- 390px viewport on Split: preview card, tabs and radio cards all stack,
  `scrollWidth === clientWidth`. Checked in both light and dark.

## What Phase 3 built

**PDF operations** (`frontend/lib/pdf/`)
- `pdfToJpg.ts` — `pdfToJpg(sources, { quality, onProgress, signal })`. Renders each page
  with pdf.js (no explicit `rotation`, so the page's own `/Rotate` is honoured), fills the
  canvas white first (JPEG has no alpha), and encodes with `canvas.toBlob`. `JPG_QUALITIES`
  is the single source of the two presets — Normal scale 2 / quality 0.85 / ≈144 dpi, High
  scale 3 / 0.92 / ≈216 dpi — and the panel reads its labels and dpi from it.
- `organize.ts` — `organizePdf(items, sources, onProgress)`, where an item is
  `{ fileId, pageNumber, rotation }` and `fileId: null` means an inserted blank page. Opens
  each source once and copies all of its wanted pages in a single `copyPages` call.
- `pageNumbers.ts` — `planPageNumbers` (pure, throws `PageNumberError`) and
  `addPageNumbers(file, options, onProgress)`. Covers mode single/facing, the 9-cell
  position, three margins, first number, from/to page, template, font family, size,
  bold/italic (as separate standard faces), underline (a drawn line) and hex colour.

**Tool workspaces** (`frontend/components/tools/<tool>/`)
- `pdf-to-jpg/` — `pdf-to-jpg-workspace` + `pdf-to-jpg-options` (mode cards with the live
  "N JPGs will be created" count, quality radios). Uses the default file grid as its canvas.
- `organize/` — `organize-workspace`, `organize-state` (the pure page-list model),
  `organize-canvas` (the combined `PageGrid`), `organize-options` (file list with colour
  chips and surviving page counts, sort, add-blank, reset).
- `page-numbers/` — `page-numbers-workspace`, `page-numbers-state` (panel state ⇄
  `PageNumberOptions`, plus `planFromState` and `previewFile`), `page-numbers-options` (the
  full panel) and `page-numbers-preview` (thumbnails with the red position dot).

**Shell changes**
- `components/tool/source-chip.tsx` — `SourceChip` / `sourceLetter` / `sourceChipClass`: the
  A, B, C… letter and its colour, assigned by position in the file list.
- `ToolPage.fileId` is now `string | null`, `null` meaning an inserted blank page, and
  `PageCard` / `PageGrid` render that as a white sheet labelled "Blank". `PageCard` also
  gained `onInsertAfter` and takes a `sourceIndex` instead of a plain letter.
- `components/tool/use-tool-pages.ts` was **deleted**; Organize owns that model now (see
  the decisions below).
- `tool-workspace.tsx` lost `PAGE_LEVEL_TOOLS` / `PageCanvas` — no placeholder tool needs a
  page grid any more. The four remaining stubs are all file-grid, backend tools.

## Decisions made in Phase 3

- **Organize's page list lives in the workspace, not in the shell**, as a plain value with
  pure operations (`movePage`, `rotatePage`, `deletePage`, `insertBlankAfter`, `sortPages`).
  `process` has to turn that list into a document, and `ToolShell` only hands `process` the
  file list, so the Split pattern — state outside, pure derivation — was the only way for
  the canvas, the sidebar, the CTA gate and the run to agree. This is why
  `use-tool-pages.ts` went: its state was inside the shell where `process` cannot see it,
  and its model had no way to express a blank page.
- **`syncOrganize(state, files)` is pure and idempotent**, keyed on a signature of the file
  list. Every consumer calls it and every edit starts from its result, so no effect is
  needed to reconcile the grid after a file is added or removed, and there is no frame where
  the grid and the output would disagree. Emptying the workspace resets it, so a leftover
  blank page cannot outlive the document it was inserted into.
- **Deleted page ids are remembered, blank ids are not.** A deleted page must not come back
  when the next file is added; a blank page only exists in the list, so remembering it would
  just leak an entry per insert-then-delete.
- **A blank page takes the size of the document's first real page**, falling back to A4, so
  inserting one into a Letter document does not produce a stray A4 sheet.
- **Page numbers lays out in "visual" space and converts to user space at the end.**
  A viewer turns a page clockwise by its `/Rotate` before showing it, so for a sideways page
  the corner the user points at is not the corner pdf-lib draws in. `toUserSpace` does that
  mapping and the text is drawn with `rotate: degrees(rotation)` to cancel the page's own
  turn — which is what makes a number land bottom-right and upright on a `/Rotate 270` page.
- **`{N}` is the last number stamped, not the document's page count.** With the defaults they
  are the same; once numbering starts partway through or at a number other than 1,
  "Page 3 of 6" should count the numbers rather than the paper.
- **The page range is validated against the previewed file but clamped per file at run time.**
  The tool takes several files and they need not be the same length: a range that runs off
  the end of a shorter document numbers what it can, and one starting past the end leaves
  that document alone. `planPageNumbers` stays strict for the UI; `addPageNumbers` clamps.
- **Standard-font text is folded to WinAnsi before drawing.** pdf-lib throws rather than
  dropping characters it cannot encode, and curly quotes and dashes are exactly what someone
  pastes into a custom template, so those are mapped to ASCII and the rest dropped.
- **PDF→JPG caps the rendered edge at 8000px.** Browsers silently return blank bitmaps past
  their canvas limit, so a poster-sized page at High quality loses a little resolution rather
  than coming out black. Each canvas is also zeroed after encoding so a long document does
  not hold one full-size bitmap per page until the next GC.
- **JPG filenames are zero-padded** (`page-01`, not `page-1`) so the extracted folder sorts
  in page order.
- **The blank-page card is white in both themes.** It stands for white paper, and a dark card
  beside the real thumbnails reads as a failed render.

## Phase 3 verification results

`npm run lint`, `npx tsc --noEmit` and `npm run build` are clean (12 static routes). The
tools were driven through a real headless Chrome (`browse … --local`) against `npm run dev`,
and every output blob was captured (by hooking `URL.createObjectURL`) and read back in Node
with pdf-lib and pdf.js — so these are assertions about the actual bytes, not the screen.

- **PDF→JPG, quality**: `sample-text.pdf` at Normal → ZIP of 5 JPEGs, each 840×1190;
  at High → 1260×1785, exactly 1.5× (284 KB vs 737 KB for the ZIP). Entries are
  `sample-text-page-1.jpg` … `-page-5.jpg`.
- **PDF→JPG, single page**: a one-page PDF → no ZIP, a single `image/jpeg` blob (19 KB) and
  the button reads "Download" rather than a count. Five pages → "Download 5 JPG images".
- **PDF→JPG panel**: the count is live from the loaded page total ("5 JPGs will be created,
  one per page"), and "Extract images" renders with a "Coming soon" badge and is disabled.
- **Organize, combined grid**: `sample-text.pdf` + `sample-scanned.pdf` → 7 cards, chipped
  A×5 and B×2. A real pointer drag (`browse mouse drag`) moved card 7 (B p2) to the front,
  then rotate on position 1, delete on position 3, and insert-blank after position 1 gave
  `[B2 rotated 90°, blank, A1, A3, A4, A5, B1]`, with the sidebar reading "7 pages, 1 of
  them blank, 1 rotated".
- **Organize, output**: the resulting PDF is exactly that list — p1 rotate=90 with one image
  (the scanned page), p2 with **zero draw operations** (genuinely blank) at 420×595 like its
  neighbours, p3/p4/p5/p6 carrying "Page 1 of 5", "Page 3 of 5", "Page 4 of 5", "Page 5 of 5"
  (page 2 correctly absent) and p7 the other scanned page.
- **Page numbers, facing**: bottom-right, "Page {n} of {N}", facing on, from page 2 →
  page 1 unstamped; pages 2 and 4 stamped bottom-**left**, pages 3 and 5 bottom-**right**,
  with texts "Page 1 of 4" … "Page 4 of 4" ({N} = 4, the last number stamped). The preview
  dots matched: `left:9%` on even pages, `left:91%` on odd, none on page 1.
- **Page numbers, rotated pages**: a fixture with `/Rotate` 0, 90, 180 and 270 → all four
  numbers land bottom-right **in the displayed page** (including the 595×420 landscape
  views) and all four read upright once the text direction is pushed through the viewport
  transform.
- **Page numbers, style**: Times + bold + italic + underline + 20 pt → the output embeds
  `/Times-BoldItalic`, pdf.js reports the stamp as serif at height 20, one stroked path per
  page for the underline, and the fill colour is the chosen `#222222`.
- **Page numbers, several files**: `sample-text.pdf` + `sample-scanned.pdf` with to-page 5 →
  ZIP of `sample-text-numbered.pdf` (5 stamps) and `sample-scanned-numbered.pdf`
  (2 stamps, text "Page 1 of 2"), i.e. the range clamped to the shorter document and `{N}`
  recomputed for it.
- **Page numbers, validation**: from page 9 on a 5-page file → "This PDF has 5 pages, so that
  range does not exist." in an `alert`, and the CTA goes disabled.
- 390px viewport on all three tools: `scrollWidth === clientWidth`, nothing overflows.

## What Phase 4 built

All under `backend/`. `backend/README.md` now carries the full endpoint and error-code
table — that is the reference Phase 5 should code the client against.

**Shared infrastructure**
- `app/config.py` — `MAX_UPLOAD_MB` 50, `MAX_FILES_PER_REQUEST` 20, `MAX_CONCURRENT_JOBS` 2,
  `MAX_OCR_LANGUAGES` 3, `QUEUE_TIMEOUT_SECONDS`, `CORS_ORIGINS`, and a per-operation
  `TIMEOUTS` map read through `timeout_for()` (OCR gets 600 s, qpdf 60 s).
- `app/deps.py` — `save_uploads()` streams each upload to a per-request temp directory in
  1 MB chunks, rejecting >50 MB (413), non-`%PDF-` (415) and empty (400) as it goes.
  `display_name` / `sanitise_filename` are the two name cleaners; `UploadBatch` owns the
  temp directory and `upload_batch()` is the context manager that guarantees cleanup on
  failure.
- `app/services/runner.py` — the only place a subprocess is spawned. Global
  `Semaphore(MAX_CONCURRENT_JOBS)`, per-operation `asyncio.wait_for`, an explicit
  `process.kill()` on timeout, and `sanitise()` to strip absolute paths out of any tool
  output before it reaches a client.
- `app/services/responses.py` — `file_response()`: one output as itself, several as a
  DEFLATE-1 zip, `Content-Disposition` from the original upload name, and a
  `BackgroundTask` that deletes the temp directory after the body is sent.
- `app/services/errors.py` — `mentions_password()` (reading tool stderr) and
  `ensure_readable()` (the pypdf pre-check).
- `app/services/passwords.py` — `validate_password`, and the two 0600 secret-file writers
  that keep passwords out of argv.

**Services and routers** — `compress` (Ghostscript), `protect` / `unlock` (qpdf),
`ocr` (OCRmyPDF + the Tesseract language list), `images` (pdfimages + Pillow), each with a
thin router in `app/routers/`.

**Docker** — the Dockerfile is now multi-stage: `base` (system tools + prod deps) →
`test` (dev deps + `tests/`) and `runtime` (the default target, the only one that ships).
`docker-compose.yml` gained a `backend-tests` service behind the `test` profile.

## Decisions made in Phase 4

- **Ghostscript 10 exits `0` on a PDF it cannot decrypt**, writing a plausible-looking but
  empty output. Left alone, compressing a locked file would have returned a blank document
  with a 200. So `ensure_readable()` pre-checks every input with pypdf and returns
  `422 password_required` before any native tool runs. It deliberately allows an
  owner-password-only file through (encrypted, but opens with the empty password) because
  every tool here reads one fine — there is a test for each half of that.
- **pypdf pre-read failures are swallowed, not raised.** pypdf is far stricter than qpdf and
  Ghostscript and throws a wide, undocumented spread of exceptions on damaged files.
  Anything other than a clean "yes, encrypted" means we learned nothing, so the real tool
  gets its turn rather than the request being refused.
- **Protect uses `qpdf @argfile`, not `--password-file`.** Debian bookworm ships qpdf 11.3,
  where the encryption passwords are *positional* — `--user-password=` / `--owner-password=`
  only arrived in 11.7. An argument file is the only way to keep them out of `ps` on this
  version. Unlock does use `--password-file=`, which 11.3 has. Verified empirically in the
  container before either was written.
- **A password containing `\r`, `\n` or `\0` is rejected with 400.** The argument file is
  line-delimited, so a newline in a password is argument injection into qpdf. Escaping was
  not worth it — no viewer's password box can produce one.
- **`ToolResult` rather than exceptions for non-zero exits.** Unlock has to tell
  "wrong password" from "broken file", which means reading stderr itself, so `run()` takes
  `check=False` and hands the result back. With `check=True` (everything else) a non-zero
  exit becomes a 500 carrying a sanitised excerpt.
- **The temp directory is freed by a `BackgroundTask`, never a `yield` dependency.** Since
  FastAPI 0.106 the exit half of a `yield` dependency runs *before* the response body is
  sent, which would delete the file mid-stream. This is written at the top of `deps.py` so
  nobody "simplifies" it back.
- **Compress falls back to the original bytes when pdfwrite does not help.** An already-lean
  or vector-heavy PDF regularly comes back larger; returning a worse file for the same wait
  is not a result. `X-Original-Size` / `X-Result-Size` are then equal, and both headers are
  in the CORS `expose_headers` list so the UI can actually read them.
- **`/images/extract` always returns a zip**, even for one image, as the phase doc
  specifies — see the open question below, because the browser-side PDF→JPG mode does not.
- **Extraction drops images under 16 px** (spacers, rules, tracking pixels) and stops at 500
  per file.
- **Absent and empty `password` on `/protect` both give `400 password_missing`.** The field
  is declared optional purely so that FastAPI's 422 validation envelope never appears for
  one of them — the UI should only ever have to read `detail`.
- **`osd` and `equ` are filtered out of `/ocr/languages`**: they are Tesseract's
  script-detection and maths models, not languages. The list is cached behind an
  `asyncio.Lock`; it only changes on redeploy.
- **OCR uses `--skip-text`**, so a born-digital PDF passes through with its text intact
  rather than gaining a second, worse layer. `TMPDIR` is pointed at the request's own
  workspace so OCRmyPDF's scratch files die with the batch.
- **The tmpfs mount has to name uid/gid 1001.** A tmpfs masks whatever ownership the image
  gave the path, so `/tmp/pdfkit` arrived root-owned and every upload failed with
  `PermissionError` even though the Dockerfile chowns it. `docker-compose.yml` now mounts it
  `uid=1001,gid=1001,mode=0700` and the Dockerfile pins the gid so the two cannot drift.
  **Phase 7 must carry this into the Coolify compose too.** `_scratch_root()` also falls back
  to the platform temp dir with a warning rather than 500-ing, so a misconfigured deploy
  degrades instead of breaking.
- **The suite lives in its own build target.** Shipping pytest and the tests in the runtime
  image to satisfy the phase doc's `docker compose run --rm backend pytest` was not worth it;
  the command is `docker compose --profile test run --rm backend-tests` instead.

## Phase 4 verification results

`docker compose --profile test run --rm backend-tests pytest -q` → **53 passed**. Fixtures
are generated at run time (a hand-assembled text PDF, a Pillow/DejaVu image-only PDF, a
gradient photo PDF, and two qpdf-encrypted variants), so no binary test assets are committed.

Three real bugs were found by the first test run and one more by the first curl run; all four
are fixed and each now has a regression test:

1. Ghostscript's silent-success-on-encrypted-input, above.
2. `/protect` with an empty password returned FastAPI's 422 envelope rather than our 400.
3. The 415 message renamed the user's file before quoting it back — "notes.txt.pdf is not a
   PDF file."
4. Zip downloads were named `pdfkit-compressed.zip.zip`, because `sanitise_filename` forces
   `.pdf` and `sanitise_archive_name` then appended `.zip` to the whole thing.

Then, against `docker compose up backend` (the real runtime image, non-root, tmpfs):

- `GET /health` → `{"status":"ok"}`; `GET /ocr/languages` → `[{"code":"eng","name":"English"}]`.
- **Compress** a 318,670-byte photo PDF at `recommended` → 81,615 bytes, `%PDF-`,
  `X-Original-Size: 318670`, `X-Result-Size: 81615`,
  `Content-Disposition: attachment; filename="photo-compressed.pdf"`.
- **Compress no-gain**: `sample-text.pdf` at `extreme` → output **byte-identical** to the
  input, both size headers 3795.
- **Compress two files** → `application/zip`, `pdfkit-compressed.zip`, entries
  `sample-text-compressed.pdf` + `photo-compressed.pdf`.
- **Protect → unlock**: `sample-text.pdf` + password `correct horse` → 4,656-byte encrypted
  PDF; unlocking it with no password → `422 password_required`, with `wrong` →
  `422 wrong_password`, with the right one → `200` and a valid 3,960-byte PDF.
- The committed `sample-protected.pdf` behaves identically (`422` without, `200` with
  `hunter2`).
- **OCR**: `pdftotext` on the input reports 0 non-space characters; after `POST /ocr` it
  reports `INVOICE 1 INVOICE 2`. (Not with `sample-scanned.pdf` — see the open question.)
- **Extract images** from the photo PDF → `photo-images.zip` holding
  `photo-image-001.jpg`, a real 1600×2200 JPEG; `high` (365,752 B) > `normal` (295,003 B).
  A text-only PDF → `422 no_images_found`.
- **Rejections**: `notes.txt` → `415 "notes.txt is not a PDF file."`; a 51 MB file →
  `413 "huge.pdf is over the 50 MB limit."`; `level=maximum` and `languages=eng,klingon` →
  400 with a readable message.
- **No leaks**: after all of the above, `ls -A /tmp/pdfkit` inside the container is empty —
  every request cleaned up after itself.

## Test fixtures

`frontend/test-fixtures/` is committed and shared by phases 2-6:

| File | What it is |
|---|---|
| `sample-text.pdf` | 5 pages, real selectable text, 3.7 KB |
| `sample-scanned.pdf` | 2 pages, a 300 dpi raster of `sample-text.pdf`, zero text items — 274 KB |
| `sample-protected.pdf` | `sample-text.pdf` encrypted AES-256, password `hunter2` |

`node scripts/make-test-fixtures.mjs` now regenerates **all three** in one command. It shells
out to the backend image for the two steps this machine cannot do locally (poppler to
rasterise, qpdf to encrypt), which is no new requirement — the backend only ever runs in
Docker anyway.

**Phase 6 replaced `sample-scanned.pdf`.** The old one drew four black bars, described in its
own generator as "a word-shaped smudge to a person": it had no glyphs, so Tesseract returned
nothing and the OCR row of the matrix could never have passed. It was also 1.4 KB, so
Ghostscript returned it unchanged at every level and Compress could not be measured either.
It is now a real 300 dpi render of the text fixture — genuinely readable to OCR, and with
enough raster data that the three compression levels separate. 300 dpi specifically, because
Compress maps its levels to 72 / 150 / 300 dpi and a 150 dpi source leaves the top two
levels with nothing to downsample.

## Open questions / risks to watch

- The shadcn `Progress` component does not emit `aria-valuenow`, so upload progress is only
  announced through the `aria-live` stage text. Worth revisiting in Phase 6 (a11y).
- `starlette` warns that `httpx` with `TestClient` is deprecated in favour of `httpx2`.
  Still harmless at 53 tests; it is the only warning the suite emits.
- Traefik default request body limit vs. the 50 MB upload cap — still flagged for Phase 7.
- The `X-Original-Size` / `X-Result-Size` headers are only readable cross-origin because they
  are in `expose_headers` in `main.py`. If a reverse proxy strips them in Phase 7, the
  compress UI silently loses its before/after numbers — it degrades to no size line rather
  than to a wrong one, but it is worth checking after the deploy.
- **Resolved in Phase 5 — `sample-scanned.pdf` cannot demonstrate OCR.**
  `make-test-fixtures.mjs` draws stroke-shaped smudges rather than glyphs, so Tesseract
  correctly finds nothing in it. Phase 5 did not change the committed fixture (phases 2-3
  assert against it); it generated a throwaway 600 dpi image-only PDF with real rendered
  lettering in the scratchpad instead, which is also what made the compression levels
  distinguishable. If a committed OCR fixture is ever wanted, `build_scanned_pdf()` in
  `backend/tests/conftest.py` is the shape to copy.
- **Resolved in Phase 5 — `/images/extract` always returns a zip, even for one image**,
  while the browser-side page mode returns a bare JPEG for a single page. Deliberately left
  inconsistent: the page mode's output count is known before the run (one per page, and the
  panel says so), whereas extraction's is not known until poppler has looked. A tool that
  unpredictably hands back either a `.jpg` or a `.zip` is worse than one that always hands
  back a `.zip`, so extraction always zips and the panel says that too.

## Notes for the next session

- **Phase 6 is polish**: responsive sweep, metadata, edge cases and a11y across all 10 tools.
  Everything is functional as of Phase 5, so this is refinement, not wiring.
- **Run both halves while working**: `docker compose up backend` plus `npm run dev`, with
  `NEXT_PUBLIC_API_URL=http://localhost:8000` (already in `frontend/.env.local`). CORS
  allows `localhost:3000` and `127.0.0.1:3000`.
- **Backend commands**, for reference:
  - `docker compose up backend` — the runtime image, port 8000.
  - `docker compose --profile test run --rm backend-tests` — the suite (53 tests).
  - `docker compose --profile test build backend-tests` after changing `app/` or `tests/`.
  - Note the phase doc's `docker compose run --rm backend pytest` does **not** work: the
    runtime image deliberately carries neither pytest nor the tests.
  - `docker cp` cannot read `/tmp/pdfkit` — it is a tmpfs mount. To get a file out of the
    container, `docker compose exec -T backend base64 -w0 //tmp/pdfkit/<file>` and decode it
    on this side (the leading `//` stops Git Bash rewriting the path).
- **When adding a backend endpoint**: service in `app/services/`, thin router in
  `app/routers/`, register it in `app/routers/__init__.py`'s `ROUTERS`. Never call
  `asyncio.create_subprocess_exec` directly — go through `app/services/runner.py`, which owns
  the concurrency limit, the timeout and stderr sanitising. That applies to a blocking
  *library* call too: if it cannot be interrupted, wrap it in a module under `app/tools/` and
  spawn it, as `anydoc_cli.py` does — a thread cannot be killed when the timeout expires.
- **The browser-tool pattern** (`merge|rotate|split`, `pdf-to-jpg|organize|page-numbers`): a
  `<tool>-workspace.tsx` holding whatever state `process` needs and rendering `<ToolShell>`,
  a `<tool>-options.tsx` rendered inside the shell that reads the file list with
  `useToolShell()`, and pure logic in `lib/pdf/<tool>.ts` that the panel and the process
  callback share.
- **The backend-tool pattern** (`compress|protect|ocr`, and PDF→JPG's extract mode): the same
  shape, but `process` is one call to `runBackendTool(context, endpoint, fields, …)` from
  `components/tool/backend-run.ts`, which owns the upload-progress-then-indeterminate
  sequence. Unlock is the one exception — it loops per file through `uploadWithPassword` so
  each file can have its own password.
- **Every tool now has a workspace**, and `WORKSPACES` in `components/tool/tool-page.tsx` is
  a total `Record<ToolId, ComponentType>` — adding a tool to `lib/tools.ts` without a
  workspace is now a type error rather than a silent fallback to a placeholder.
- **Anything a tool's `process` must see has to live outside `ToolShell`**, because the shell
  only passes `process` the file list. Keep it as a plain value plus pure functions and
  derive against `files` in the panel, the canvas, the CTA predicate and the run — Split's
  `planFromState` and Organize's `syncOrganize` are the two worked examples.
- **Error surfacing has two channels now.** Throw an `ApiError` with `recoverable: true` and
  `ToolShell` shows a toast and returns to the file list with everything intact; throw
  anything else and it shows the full-page failure screen. `silent: true` skips the toast
  (used when the user cancels a password prompt). Everything from `lib/api.ts` is already
  classified — see `recoverableStatus`.
- **`eslint` forbids `setState` inside an effect** (`react-hooks/set-state-in-effect`), and
  it is an error, not a warning. Derive with `useMemo` instead — OCR's language filtering is
  the worked example.
- `components/tool/page-thumbnail.tsx` is the non-draggable page preview (Split preview, Page
  numbers preview); `PageGrid` / `PageCard` is the editable one (Organize only).
- **Bash heredocs really do mangle backslashes** in this environment, as the `lib/format.ts`
  note says: a `/\\/g` written into a heredoc arrives as `/\/g`. Write `.ts`/`.mjs` files with
  the editor tools, not `cat > file <<EOF` — including when editing this file, which is how
  this very line was mangled once already.
- **How the tools were verified**, if an output ever needs re-checking: hook
  `URL.createObjectURL` in the page, run the tool, click Download, then read the captured
  blob back as base64 and inspect it in Node with pdf-lib/pdf.js from
  `frontend/node_modules`. That is the only way to assert on the bytes rather than the
  screen. A hook on `XMLHttpRequest.open` / `fetch` is the matching trick for proving that a
  rejected file never left the browser.
- Local machine lacks Ghostscript/qpdf — backend must always be exercised via Docker,
  never `uv run` directly on host (`uv run pytest` is fine; it doesn't touch the binaries).
- Remember the hydration rule: every tool workspace must stay behind
  `next/dynamic` + `{ ssr: false }` (`components/tool/tool-page.tsx` is that boundary).

## What Phase 5 built

All under `frontend/`.

**Backend client**
- `lib/api.ts` — the browser's half of the FastAPI service. `uploadAndProcess(endpoint,
  files, fields, { onProgress, signal, fallbackName })` over `XMLHttpRequest`, returning
  `{ blob, filename, headers }`; `ApiError` (status, backend `code`, `recoverable`,
  `silent`); `assertUploadable` for the 50 MB pre-check; `filenameFromDisposition`;
  `uploadWithPassword` for the ask-and-retry protocol; `getJson` for `/ocr/languages`.
- `lib/file-handoff.ts` — the module-level slot that carries a `File` from one tool to
  another across a client-side navigation.
- `components/tool/backend-run.ts` — `runBackendTool`, the shared "upload % then
  indeterminate" progress pattern, plus `numericHeader`.
- `components/tool/password-dialog.tsx` — `usePasswordPrompt()` returning
  `{ requestPassword, dismissPrompt, passwordDialog }`. `lib/api.ts` owns the retry
  protocol; this owns the UI.

**Tool workspaces** (`frontend/components/tools/<tool>/`)
- `compress/` — three radio cards (Extreme / Recommended / Less) plus a size summary.
- `protect/` — password + repeat with a shared show/hide toggle, inline mismatch error, and
  `protectReady()` as the single CTA gate.
- `unlock/` — the "just press the button" callout and a per-file lock/unlock list.
- `ocr/` — `use-ocr-languages.ts` (fetches `GET /ocr/languages`, falls back to English with
  a toast) and the max-3 language picker with the accuracy callout.
- `pdf-to-jpg/` — "Extract images" is live; the quality labels and footer text now change
  with the mode, since dpi means nothing when extracting stored bitmaps.

**Shell changes**
- `ToolShell` gained `acceptEncrypted`, `adoptFiles` and `overlay`, and now turns a
  recoverable `ApiError` into a toast plus a step back to the file list rather than the
  full-page failure screen.
- `EncryptedNotice` takes `ToolFile[]` and hands the files to Unlock on click.
- `FileGrid` / `FileCard` / `Thumbnail` gained `allowEncrypted` / `locked`, so on Unlock a
  protected file reads as amber "locked" rather than a red failure.
- `tool-page.tsx`'s `WORKSPACES` is now a total `Record<ToolId, ComponentType>`, and
  `components/tool/tool-workspace.tsx` (the placeholder) was **deleted** — every tool has a
  real workspace.

## Decisions made in Phase 5

- **A recoverable failure is a toast, not the error screen.** A wrong password, a busy or
  unreachable server, or a PDF with no images to extract all leave the workspace exactly as
  it was; replacing the screen with a failure page throws that away for nothing. `ApiError`
  carries `recoverable` (everything except a 5xx that is not 503/504) and `silent` (the user
  cancelled), and `ToolShell` branches on them. The full-page error screen is now reserved
  for genuine server faults.
- **Unlock sends one request per file; every other backend tool sends the batch.** The
  backend takes a single `password` per request, so a batch of differently-locked files
  would fail whole at the first one. Per file, each gets its own prompt, its own retry and
  its own inline error; the outputs are zipped client-side with the existing `zipBlobs`.
- **The first unlock attempt deliberately carries no password.** A file locked with only an
  owner password opens with the empty one, so prompting up front would ask for something the
  user does not have. `password_required` means that attempt failed; `wrong_password` means
  the typed one did — the dialog is told which, which is what lets it show an inline error
  instead of a generic toast.
- **The password dialog stays mounted between attempts**, and its resolver lives in a ref
  rather than in state, because it has to be callable from an event handler without going
  through a React updater. The form is keyed on the *filename*: a rejected password is left
  in the field (usually a typo away from right) but pre-selected, while moving to the next
  file starts empty.
- **`ToolShell.acceptEncrypted` exists because `readableFiles` excluded the very files
  Unlock is for.** It also had to drop encrypted files out of the `stillLoading` check —
  they never get a page count, so the CTA would have stayed disabled for good.
- **The encrypted-PDF banner hands the actual `File` over**, through a module-level slot
  that survives a `next/link` navigation and is emptied on read. A full page load loses it,
  which is correct: the `File` objects are gone by then anyway.
- **Compress's saving is a batch total, not per file.** `ToolResult` carries one blob and
  one size pair, and `X-Original-Size` / `X-Result-Size` are sums over the request — so for
  the single-file case (the common one) it is per-file, and for a batch it is the honest
  total. Per-file numbers would mean one request per file and a different result screen.
- **The progress bar goes indeterminate the moment the upload finishes**, rather than
  sitting at 100%. Once the last byte is on the wire there is no honest percentage for
  Ghostscript's or Tesseract's share of the wait.
- **The OCR language list comes from the server, and an empty selection disables the CTA.**
  Which models exist is a property of the backend image, so hardcoding them here would go
  stale on the next Dockerfile change. An earlier version back-filled the first installed
  language when the selection emptied, which made unchecking the only language look like a
  broken checkbox; it now simply disables the CTA and the panel says why.
- **PDF→JPG's quality labels change with the mode.** "≈144 dpi" is meaningful when a page is
  being rendered and meaningless when a stored bitmap is being re-compressed, so extraction
  shows "smaller files" / "less JPEG loss" instead.

## Phase 5 verification results

`npm run lint`, `npx tsc --noEmit` and `npm run build` are clean (12 static routes). The
tools were driven through a real headless Chrome (`browse … --local`) against `npm run dev`
with `docker compose up backend`, and every output blob was captured (by hooking
`URL.createObjectURL`) and read back in Node — so these are assertions about the bytes the
browser actually downloaded, not about the screen.

Fixture: a generated 2-page, 600 dpi, image-only PDF (928 KB) with legible rendered text and
a photo-like block. `sample-text.pdf` is far too lean for Ghostscript to improve on and too
small to tell the compression levels apart. Not committed — it lives in the scratchpad, and
the committed fixtures are still the ones phases 2-4 use.

- **Compress, all three levels** on the same file: 928 KB → 41.9 KB (95%), → 108 KB (88%),
  → 445 KB (52%) — a strict extreme < recommended < less ordering. Each downloaded blob is
  byte-for-byte the size curl gets from the endpoint, and all three open with pdf-lib at
  2 pages / 408×528. The readout comes from `X-Original-Size` / `X-Result-Size`.
- **Compress, two files** → a ZIP of `rich-scan-compressed.pdf` and
  `report-two-compressed.pdf`, with the result screen showing the batch total.
- **Protect**: the CTA is disabled while the fields are empty, still disabled with an inline
  "The two passwords do not match." on mismatch, and enabled once they match. The file the
  *browser* downloaded reports `R = 6` and `stream/string/file encryption method: AESv3`
  under `qpdf --show-encryption`, is refused by `qpdf --check` with "invalid password", and
  passes `qpdf --password=hunter2 --check`.
- **Unlock, round trip** on that same protected file: the card reads amber "4.5 KB · locked"
  and the CTA is enabled, with no encrypted-PDF banner. A wrong password leaves the dialog
  open with "That password did not open the file. Try again.", `aria-invalid="true"`, no
  toast and no error screen; `hunter2` then succeeds.
- **Unlock, two files with different passwords** (`hunter2` and `secondpass`): prompted one
  at a time, each field starting empty with no stale retry error; result "Download 2 unlocked
  PDFs" → a ZIP of two 5-page PDFs with no `/Encrypt` and page 1 text intact.
- **Unlock, cancelled prompt** → straight back to the file list, no toast, no error screen.
- **Encrypted-guard handoff**: a locked file on Merge shows the banner with the CTA disabled;
  clicking "Unlock this file" lands on `/unlock-pdf` with that file already loaded and the
  CTA ready. A full page reload correctly shows an empty dropzone instead.
- **OCR**: the picker is populated from `GET /ocr/languages` (`English / eng`) with English
  checked; unchecking it disables the CTA and shows "Pick at least one language". The
  image-only fixture goes from **0 characters** of extractable text to **463**, reading
  "THE QUARTERLY REPORT Revenue grew by eleven percent across the northern region…".
- **Progress is real, not a timer**: sampling the processing view every 40 ms during the OCR
  run captured "Uploading your file" with a determinate bar, then "Reading the pages — this
  is the slow part" with the indeterminate one. That flip is driven only by `onProgress(100)`.
- **PDF→JPG, extract images**: the "Coming soon" badge is gone and the mode runs; the ZIP
  holds `rich-scan-image-001.jpg` / `-002.jpg`, both valid JPEGs at the stored **3400×4400**
  — i.e. the embedded originals, not a re-render of the page. A text-only PDF gives the toast
  "There are no embedded images in this PDF to extract." with the workspace left intact.
- **Backend unreachable** — both with the container stopped before the request and killed
  mid-OCR — gives "Could not reach the server. Check it is running and try again." as a
  toast, keeps the files, and leaves the CTA usable. No hang, no crash, no error screen.
- **Client-side pre-checks**: a 52 MB `huge.pdf` → "huge.pdf is over the 50 MB limit.";
  `notes.txt` → "notes.txt is not a PDF." Both stay on the dropzone, and a hook on
  `XMLHttpRequest.open` / `fetch` confirms **zero requests left the browser**. The same
  52 MB file is accepted on Merge (a browser tool, uncapped) and only then fails to parse.
- **390 px viewport** on Compress, Protect, Unlock, OCR and PDF→JPG: no horizontal overflow
  and the sidebar stacked under the canvas in every case. The password dialog sits at
  16 px / 374 px in a 390 px viewport.
- **Browser-tool regression** after the shell changes: Merge still produces the 7-page
  document ("Page 1 of 5" … "Page 5 of 5" then the two scanned pages), and Split still
  produces its 5-page output.

## Open notes for Phase 6 (all addressed)

- ~~`503 server_busy` and `504 processing_timed_out` are mapped and take the same
  recoverable-toast path as the errors above, but were not triggered live.~~ Phase 6 drove
  both (plus a 500 and a refused connection) by intercepting the request in the browser.
- ~~Only `eng` is installed in the backend image, so the OCR picker's max-3 cap and its
  language ordering are not exercised by anything but reading the code.~~ 14 languages are
  installed now and the picker was driven in a real browser (see the top of this file), so
  the cap and the ordering are exercised for the first time.
- Compress, Protect and OCR reject an encrypted input at the backend with
  `422 password_required`, but the client-side encrypted guard means one never reaches them;
  that error therefore has no dedicated UI beyond the generic toast.

## What Phase 6 built

All under `frontend/`.

**Metadata and icons**
- `lib/constants.ts` — `SITE_URL` (from `NEXT_PUBLIC_SITE_URL`, localhost fallback so
  `next build` works before a domain exists) and `BRAND_HEX`, the plain-hex form of
  `--brand` for the two places that cannot read a CSS custom property.
- `app/layout.tsx` — `metadataBase`, site-wide `openGraph` / `twitter`, and a `viewport`
  export with a per-theme `themeColor`.
- `lib/tools.ts` — `toolMetadata` now returns `openGraph` and `twitter` alongside the title,
  description and canonical, all still read from the registry.
- `app/icon.svg` (favicon), `app/favicon.ico` (rasterised from it), `app/apple-icon.png`
  (the same mark, squared off) and `app/opengraph-image.tsx` (a generated 1200×630 card).

**Structure**
- The `main` landmark moved out of `ToolShell` and into the two route-group layouts, so it
  wraps every phase of the state machine rather than only the configure screen.
- `FileDropzone`'s heading is the tool name as an `h1`, matching the sidebar's `h1` in the
  configure phase — every page now has exactly one, and it says the same thing either way.

**Mobile**
- The sidebar CTA is `sticky bottom-0` below `lg`, so it stays in reach at the bottom of a
  long options list instead of sitting under it.

## Defects Phase 6 found and fixed

1. **A 500 from the backend took over the screen.** `recoverableStatus` treated 500 and 502
   as unrecoverable, so a Ghostscript crash or a proxy error threw the whole workspace away
   for a full-page failure screen — exactly the case where the file list is still fine and
   the next step is a retry or a gentler setting. Every answer the server gives is now
   recoverable; the failure page is reserved for errors raised on this side, where the state
   really is in doubt.
2. **Enter on a page-card button also started a keyboard drag.** `PageCard` spread dnd-kit's
   `attributes` on the `<li>` and named no activator, and dnd-kit's keyboard sensor only
   skips a keypress when there *is* an activator to compare against — so Space or Enter on
   "Delete page 3" both deleted the page and began dragging it. `PageCard` now has a grip
   button carrying `setActivatorNodeRef` + `attributes` (as `FileCard` already did), with
   the pointer `listeners` left on the `<li>` so dragging anywhere on a card still works.
   It also removes a button nested inside a `role="button"`.
3. **`sample-scanned.pdf` could not have passed the OCR or Compress rows.** See the test
   fixtures section above.

## Phase 6 verification results

Driven headlessly with Playwright against `next build` + the standalone server on :3000
(the backend's CORS allows :3000 only), with the Dockerised backend up. The harness lives in
the session scratchpad, not the repo — adding Playwright as a project dependency is a stack
decision Phase 6 has no mandate for. **Worth considering for Phase 7**, since it catches
regressions in a deploy far faster than clicking through ten tools.

| Area | Result |
|---|---|
| All 11 pages (10 tools + landing) at 390 px and 1440 px | no horizontal scroll, exactly one `h1`, exactly one `main`, zero console errors or warnings |
| Encrypted guard | banner + `/unlock-pdf` link + disabled CTA on all 9 guarded tools; Unlock accepts the file, shows no banner, marks the card "locked" |
| Non-PDF rejection | clear toast on all 10 tools |
| >50 MB rejection | clear toast on the 5 tools that can post; correctly not applied to browser-only tools |
| Merge | dropped order, sorted A–Z, and drag-reordered all produce the expected page order (checked by which pages carry text, not just page counts) |
| Split | custom range 2–4 → 3 pages; fixed every 2 → 3 documents; pages `"1,3-5"` merged → 4 pages, page 2 absent |
| Rotate | right twice → 180° on every page; "Reset all" → 0° and the CTA closes again; per-file rotate turns only that file |
| Organize | delete + rotate + insert blank across two files → 7 pages with one at 90°; sort restores file order |
| Page numbers | from page 2 → page 1 skipped, the rest numbered 1–4; "Start at 100" → 100…104; facing mode mirrors the stamp (x=381 odd, x=32 even) |
| PDF→JPG | normal 840×1190 vs high 1260×1785; extract images → 2 embedded JPEGs |
| Compress | extreme 64 KB < recommended 210 KB < less 274 KB, all three open |
| OCR | scan goes from 0 text items to ~820 characters per page |
| Protect / Unlock | output refuses to open without the password and opens with it; Unlock strips it; a wrong password re-prompts inline instead of failing the run |
| Backend failures | connection refused, 500, 503 and 504 each show a toast and return to the files — never stuck on "Processing…", never a failure page |
| Corrupt PDF | flagged on its own card, removable, and the other files still run; a corrupt-only workspace disables the CTA |
| Accessibility | every grid and panel control tab-reachable, every focus stop paints a ring, Enter on a page action no longer drags, Space on the grip still does |
| Contrast | zero text nodes below WCAG AA on the landing page and three workspaces, in both light and dark, measured against the real composited background |
| `npm run lint && npm run build` | clean |

## Open notes for Phase 7

- `NEXT_PUBLIC_SITE_URL` must be set at **build** time in Coolify, not runtime — it is
  inlined into `metadataBase`, and without it every canonical and OG URL says
  `http://localhost:3000`.
- `NEXT_PUBLIC_API_URL` is the same kind of build-time variable, and the backend's
  `CORS_ORIGINS` has to name the deployed frontend origin or every backend tool fails with
  the "Could not reach the server" toast.
- A clean `next build` is worth insisting on: a stale `.next` from an earlier `next dev` run
  left the HMR client and the devtools bundle being served from a *production* server here,
  which cost some time to rule out. `rm -rf .next` before building in CI/Docker.

## Fix: compression did nothing (post-Phase 6)

**Reported:** every compression level returned a file the same size as the upload.
Reproduced on both PDFs in `PDFKit Samples/` (Folksam insurance terms, 15 MB and 50 MB)
and on a generated 200 dpi scan. It was not a UI bug — Ghostscript genuinely could not
shrink any of them, and `compress_one`'s "no gain, return the original" fallback turned
that into a silent 0%.

Two independent causes, one per kind of document:

1. **Scans.** Ghostscript 9+ defaults to `-dPassThroughJPEGImages=true`, so DCT image data
   was copied through byte for byte and the output was the input plus overhead. On top of
   that, `*ImageDownsampleThreshold` defaults to 1.5, so a 200 dpi scan never got
   downsampled towards a 150 dpi target (200/150 = 1.33). Fixed by turning pass-through
   off, setting all three thresholds to 1.0, and pinning DCTEncode plus an explicit
   `QFactor` per tier via `setdistillerparams` — note `.setpdfwrite` was **removed in
   Ghostscript 10** and `setdistillerparams` is now called bare, and with auto-filtering
   off the quality comes from `/ColorImageDict`, not `/ColorACSImageDict`.

2. **Vector documents.** Both sample files are "Microsoft: Print To PDF" output: no images,
   no fonts, no text layer — every glyph is filled bezier paths, and 99.5% of the file is
   Flate content streams (119 MB decompressed in the 15 MB file). pdfwrite re-interprets
   that geometry and hands back a file **45% bigger**, so no Ghostscript flag could ever
   have helped. What does help is that the driver pads every coordinate to six decimal
   places: `0.750000` is ten bytes for a number that needs four. Stripping the padding is
   arithmetically lossless and takes ~24% off the file before Flate has even run.

New `app/services/streams.py` does that second job: decode each content stream, shorten the
numbers, re-deflate at level 9, then a `qpdf --object-streams=generate` pass over the
structure. `compress.py` now surveys the document (image bytes vs content-stream bytes),
runs only the strategies its shape justifies, and keeps the smallest result.

Things that took a while to get right, and should not be re-litigated:

- The rewriter edits raw bytes, so it must skip anything that only *looks* like a number:
  literal strings (which nest parens and escape them), inline image payloads between
  `ID` and `EI`, names like `/R7.0`, and the mantissa of an exponent. `test_streams.py`
  pins each of these.
- Streams are found by a **safelist** traversal (page `/Contents`, Form XObjects, tiling
  patterns, Type3 `/CharProcs`, annotation `/AP`), never "every stream that is not an
  image" — ICC profiles and embedded fonts are bare Flate streams too, and rewriting one
  corrupts the file.
- `precision` (rounding, as opposed to stripping padding) is worth only ~2% more and is
  *not* lossless, so `less` does not use it. Measured: lossless-only renders
  pixel-identical to the original; rounding to 3 dp moves ~0.2% of pixels, all of them
  antialiasing on glyph edges.
- The rewrite is pure-Python CPU work (~13s for 15 MB, ~43s for 50 MB), so it runs in a
  thread and takes a slot from the same `MAX_CONCURRENT_JOBS` semaphore Ghostscript uses —
  hence `runner.job_slot`, factored out of `runner.run`. It also honours a deadline.
- The callback-free regex path (three `re.sub` calls with literal replacements) is ~40%
  faster than one `re.sub` with a Python callback, which matters at ten million numbers
  per file. Both produce byte-identical output; there is a test asserting the values are
  unchanged.

Measured after the fix (via the running backend, not the test suite):

| File | less | recommended | extreme |
|---|---|---|---|
| Folksam MC (15 MB, vector) | 23.9% | 25.3% | 25.4% |
| Folksam Hem (50 MB, vector) | 23.7% | 25.1% | — |
| Generated 200 dpi scan (6.8 MB) | 48.8% | 71.3% | 90.6% |

All three were 0.0% before. iLovePDF gets ~30% on the vector files, so we are in the same
territory by the same means. An already-lean PDF still reports an honest 0% and gets its
original bytes back; encrypted input still 422s before any tool runs.

`test_returns_the_original_when_there_is_nothing_to_gain` was asserting the old limitation
(byte-identical output for the minimal text fixture, which the rewriter now shrinks 14%).
It is replaced by `test_never_hands_back_a_bigger_file` plus a second-pass test, which pin
the invariant that actually matters. Suite: 77 passed.

## Fix 2: compression barely touched a text-only PDF (post-Phase 6)

**Reported:** `PDFKit Samples/BrainyDocs - company profile.pdf` — a two-page Word
document — compressed by 4%, where iLovePDF got ~97%.

**Cause:** 96.8% of that 4 MB file is a single object: a `/FontFile2` with
`/Length1 7776076`. Word embedded the *entire* Segoe UI Emoji because the document
contains one emoji, and 91.7% of that font program is its `COLR` table (colour
layers for thousands of emoji) plus `CPAL`. The actual outlines, `glyf`, are 1,524
bytes. Ghostscript reports the font as subsetted — `pdffonts` shows the `ABCDEF+`
prefix on its output — and still writes 3.85 MB, because its subsetter does not
understand `COLR` and copies it through whole. `mutool clean -gggg` made the file
*bigger*. No Ghostscript flag can fix this.

New `app/services/fonts.py` subsets embedded TrueType/OpenType programs with
fontTools, driven by a scan of what the document actually draws: **4,073,060 →
43,295 bytes, 98.9%**, rendering pixel for pixel identical. It runs before the
other two passes, since fewer font bytes is a better input for either.

Three things here are load-bearing and must not be "simplified" away:

- **`retain_gids=True`.** A PDF names glyphs by number. A subsetter normally
  renumbers them, and then the content streams point at whatever moved into the
  old slots. The first working version did exactly this and every en-dash in the
  sample document came out blank — while the file stayed valid and `pdftotext`
  still returned the right characters, because extraction reads `/ToUnicode`, not
  the font. `test_the_used_glyphs_keep_their_outlines_and_their_numbers` pins it.
- **Refuse rather than guess.** A content stream that will not parse, a CID font
  that is not Identity-H, a character code that cannot be placed in the font —
  each means that font is left alone. Bare CFF (`/FontFile3 /Type1C`) and Type 1
  are skipped entirely; they are not sfnt containers and are small in practice.
- **The render check.** `_renders_the_same` rasterises up to 8 pages of the input
  and the subsetted output and compares them, and throws the subset away if they
  differ. The failure mode this exists for — a content stream the scan never
  reached looks exactly like a font with no glyphs in use — produces a blank page
  in a valid file, which nothing else notices.

### A corruption bug in Fix 1, found on the way

Compressing this file surfaced `Syntax Error: Unknown operator 'e-06'` in the
output of the *stream rewriter* shipped in 9b66624. The guard that stops rounding
from collapsing a small number to zero fell back to `f"{value:.6g}"`, which emits
**scientific notation** below 1e-5 — and a content stream has no exponent grammar,
so a reader takes `e-06` as an operator and the operand it should have been is
gone. Every `re`/`c`/`cm` after it loses arguments. The file still opens.

This shipped because the one test for that branch picked 0.000123, which is just
above where `%g` switches to exponents. The replacement sweeps magnitudes from
1e-1 to 1e-11 and asserts every emitted token matches the PDF number grammar, and
`_rounder` now refuses to emit anything that is not a plain decimal *and* shorter
than what it replaced — so it cannot create a token, only shorten one.

`_parses_cleanly` was added as the matching end-to-end gate: `pdftotext` walks
every operator, so it catches this whole class. It runs on the rewriter's output
(8–18 ms on an ordinary document, 6.4 s on the 50 MB vector one) and only parses
the *source* as well when the candidate looks bad, so the expensive second pass
happens only on a real failure — and a document that already had content-stream
errors before we touched it does not lose compression over them.

### Measured after both fixes

| File | less | recommended | extreme |
|---|---|---|---|
| BrainyDocs profile (4 MB, Word + emoji) | 98.9% | 98.9% | 98.9% |
| Folksam MC (15 MB, vector) | 23.9% | 25.3% | 25.4% |
| Folksam Hem (50 MB, vector) | 23.7% | 25.1% | — |
| Generated 200 dpi scan (6.8 MB) | 48.8% | 71.3% | 90.6% |

Every delivered file: zero `Syntax Error`s from `pdftotext`, page count preserved,
text extraction identical, and the rendered pages identical (brainy less/recommended
0.0000%, hem 0.0034%, mc 0.0126%). The scan's 20% page difference is the image
downsampling doing its job. Suite: 106 passed.

Both new gates were checked by breaking the code they guard and confirming the
test fails — worth repeating if either is ever touched, since a safety check that
cannot fail is worse than none.
