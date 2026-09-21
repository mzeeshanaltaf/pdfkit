# Phase 10 (part 5) — Daytona offload: orphan sweep, CI snapshot builds, go-live

## Goal

Close the last gaps between "works when I run it by hand" and "safe to leave on in
production": clean up sandboxes a crashed process never got to delete, stop hand-building
`pdfkit-toolchain` every time a dependency changes, document the feature, and — the actual
point of the whole four-phase build — flip `DAYTONA_ENABLED=true` on the real VPS and watch
it hold under real traffic.

## Prerequisites

Phases 2–4 done: all four operations (`ocr`, `word`, `markdown`, `compress`) offload
through `maybe_offload()`, sharding across `DAYTONA_MAX_SANDBOXES` works, and
`backend/tests/test_offload.py` is green offline. `DAYTONA_ENABLED` is still `false` in the
real Coolify environment going into this phase — that is what this phase changes, last,
after everything else here is in place.

## Context

Three things stand between the current state and "safe to run unattended":

1. **Nothing sweeps orphaned sandboxes.** Every phase so far relies on `try/finally` +
   `ephemeral=True` + `auto_stop_interval` + `ttl_minutes` (Phase 2 §4) to guarantee
   teardown — real guarantees, but not a substitute for a sanity check on startup, since a
   Coolify redeploy `SIGKILL`ing uvicorn mid-batch skips every `finally` in the process.
2. **`pdfkit-toolchain` is currently a hand-built, unversioned snapshot** (Phase 2 §1) —
   built once by a person running a `POST /snapshots` call locally. A `uv.lock` bump six
   weeks from now silently runs stale tools in every sandbox until someone remembers to
   rebuild it by hand, and there's no way to tell from the running system that it's stale.
3. **The feature has no docs and is still off.** `.env.example`, `docker-compose.yml`, and
   `backend/README.md` need the full `DAYTONA_*` surface documented for whoever operates
   this next, and someone has to actually flip the switch and watch it.

## 1. Orphan sweep on startup

On backend startup (`app/main.py`'s existing startup path), if `config.DAYTONA_ENABLED`:
list sandboxes carrying the label `{"app": "pdfkit"}` (set by `_DaytonaPool.provision()`
since Phase 2) and best-effort delete any that exist — a fresh process starting up should
never find a sandbox alive that belongs to it, since nothing is running yet to own one.

**Guard this specifically**, because Phase 2 §0 flagged it as unverified: the SDK version
pinned back in Phase 2 might still hit the historically-broken `list()` (the previously-
pinned `0.113.1` called a removed `/sandbox/paginated` endpoint and raised). Confirm
`list()` works on the pinned version — this should already have been checked once in
Phase 2 §0's verification step; re-confirm here since time has passed and the pin may have
moved. If it still doesn't work on any available version: **skip the startup sweep
entirely and rely on layers 2–3 alone** (`ephemeral` + `auto_stop_interval` + `ttl_minutes`
already guarantee no sandbox outlives `DAYTONA_TTL_MINUTES`, worst case). Log loudly either
way — an operator watching the Daytona dashboard should be able to tell from the startup
log whether the sweep ran or was skipped, not have to guess.

Make the sweep **best-effort**: catch and log any error from the list-or-delete calls,
never let it block startup, since a working app that skipped a cleanup sweep is strictly
better than an app that won't start because Daytona's API had a bad moment.

## 2. CI-built, content-hashed `pdfkit-toolchain`

New `.github/workflows/snapshot.yml`:

- Triggers: `workflow_dispatch` (manual) and `paths: ["backend/Dockerfile",
  "backend/pyproject.toml", "backend/uv.lock"]` (automatic on the files that actually
  change what's inside the image).
- Builds `--platform=linux/amd64 --target toolchain` (the stage Phase 2 §1 added to
  `backend/Dockerfile` — no further Dockerfile changes needed here).
- Tags with a 12-hex digest of those three files' contents (`sha256sum backend/Dockerfile
  backend/pyproject.toml backend/uv.lock | sha256sum | cut -c1-12`, or equivalent), so two
  runs against unchanged inputs produce the same tag idempotently.
- Pushes via `POST /snapshots` with `buildInfo.dockerfileContent`, named
  `pdfkit-toolchain-<hash>` — reusing exactly the API shape and both constraints Phase 0
  and Phase 2 §1 already worked out by hand (`ENTRYPOINT` inside the Dockerfile content,
  not a request field; no `cpu`/`memory`/`disk` on sandbox create from this snapshot).
- After a successful push, the workflow's own output (or a short manual step) is: update
  `DAYTONA_SNAPSHOT` in the real Coolify environment to the new `pdfkit-toolchain-<hash>`
  name. **Deliberately not automatic** — a dependency bump that hasn't been snapshotted yet
  should fail to create a sandbox and fall back to local (Phase 2's fallback rule already
  covers "bad snapshot name" as a normal failure mode), not silently run a skewed toolchain
  because a name pointed at "latest" moved out from under a running deploy.

**Keep the snapshot warm**: Daytona deactivates a snapshot after ~2 weeks unused. A second
job in the same workflow, on a weekly `schedule:` cron, creates and deletes one tiny
sandbox from the current `pdfkit-toolchain-<hash>` — enough activity to keep it active
without the cost of a real workload. At runtime, if a sandbox create fails with a
"snapshot inactive"-shaped error, `_DaytonaPool.provision()` should call whatever
reactivation call the pinned SDK exposes and retry **once**, then fall back to local if
that also fails — this is a small addition to Phase 2's `_DaytonaPool.provision()`, not a
new module.

## 3. Docs

- `.env.example`: every `DAYTONA_*` var from Phase 2 §2, under
  `# --- Daytona offload (optional; unset = everything runs on the VPS) ---`, each with a
  one-line comment (not a restatement of this phase doc — just enough for someone setting
  up a fresh environment to know what a sane value looks like).
- `docker-compose.yml`: same vars in `backend.environment`, `${VAR:-default}` form,
  matching every other optional knob already there.
- `backend/README.md`: a short section — what the feature does, the four operations it
  covers, how to build/rebuild the snapshot (pointer to `snapshot.yml`, not a duplicate of
  its logic), and where to look first if it's suspected of misbehaving (`/health`, the
  Daytona dashboard, `DAYTONA_FALLBACK_LOCAL=false` for isolating whether a given failure
  is Daytona-side, per Phase 2's note on that flag).
- `STATUS.md`: close out Phase 10 the way every other phase's session has — what shipped,
  what was decided, what's left, per `CLAUDE.md`'s working-across-sessions convention.

**Optional, small**: add a `sandboxes: <count>` field to `/health`'s response
(`app/main.py:96`) if `_DaytonaPool` can report currently-open sandboxes cheaply (e.g. a
process-local counter incremented on `provision()` and decremented on `dispose()`) —
useful during the go-live watch in §4, not required for the feature to work. Skip it if it
would need a real Daytona API round-trip on every `/health` hit; a local counter racing
slightly behind reality is fine for this, an extra network call on the liveness endpoint is
not.

## 4. Go live

1. In the real Coolify environment: set `DAYTONA_API_KEY`, confirm `DAYTONA_SNAPSHOT`
   points at the current CI-built name, leave every other `DAYTONA_*` var at its default,
   and set `DAYTONA_ENABLED=true`. Redeploy.
2. Watch `/health` (`jobs`, and `sandboxes` if §3's optional field was added) and Hostinger
   CPU (the same monitoring that caught the original throttle incidents) through a period
   of real user traffic touching all four offloadable operations — not just a synthetic
   batch, since Phase 0/2/3/4's numbers all came from generated fixtures at a scale chosen
   for fast iteration, not necessarily the sizes real users actually upload.
3. If anything looks wrong: `DAYTONA_ENABLED=false` is a one-var rollback with no code
   change, exactly as the original design intended — that is the entire reason this
   feature was built as a flag rather than a rewrite. Use it without hesitation; there is
   no cost to falling back to the path that has been correct and battle-tested since Phase
   0 of this project.
4. Once stable, consider narrowing `DAYTONA_MIN_FILES`/`DAYTONA_MIN_BYTES` based on real
   observed batch sizes — Phase 2 already noted `DAYTONA_MIN_BYTES`'s 5 MiB default is
   "arbitrary rather than economically derived" now that transfer is noise at 60 MB/s;
   this is the phase where real production data finally makes that number correctable
   instead of guessed.

## Explicitly out of scope for this phase

- Any new operation beyond the four already wired (Protect/Unlock/Images stay local per
  the original design's own reasoning — sub-second `qpdf` calls where a round trip would
  dominate; nothing in Phases 0–4 changes that).
- A warm pool of pre-provisioned sandboxes — Phase 0 already measured this as not worth it
  (0.79 s cold vs. an estimated ~0.5 s saved, against continuous disk billing and quota
  occupied). Nothing in Phases 2–4 changes that calculus.
- A partial-shard-success result contract (flagged as explicitly deferred in Phase 4 §3).

## Testing

- `snapshot.yml` itself: a `workflow_dispatch` dry run against a scratch/test Daytona
  project (not the production account) if one is available, confirming the hash-tag
  computation is stable across two runs with unchanged inputs.
- Orphan sweep: start the backend with `DAYTONA_ENABLED=true` while a sandbox carrying the
  `{"app": "pdfkit"}` label already exists (created by hand, simulating a crash-orphaned
  one) → confirm it's gone after startup, and that a normal startup with zero pre-existing
  sandboxes doesn't error or slow down meaningfully.
- Reactivation retry: this is hard to test live without waiting two weeks for a real
  snapshot to deactivate — a unit test against `_DaytonaPool.provision()` with a fake pool
  that raises a "snapshot inactive"-shaped error once, then succeeds, confirming exactly
  one retry and not a retry loop, is sufficient; leave the real reactivation call itself
  to the live smoke test's judgment rather than manufacturing a live deactivated snapshot.

## Verification

- `docker compose run --rm backend-tests` green, as always, with `DAYTONA_ENABLED` unset.
- `snapshot.yml` runs green on a manual `workflow_dispatch` and produces a real, working
  `pdfkit-toolchain-<hash>` snapshot — confirm with a throwaway sandbox create + `ocrmypdf
  --version`/`gs --version`, the same spot-check Phase 2 §1 did by hand for the original
  hand-built snapshot.
- Kill `-9` the backend process mid-offloaded-batch (simulating the Coolify-redeploy case
  the `finally`-based teardown can't catch) → confirm the orphaned sandbox is gone either
  from the next startup's sweep or, absent that, within `DAYTONA_TTL_MINUTES` — both are
  acceptable outcomes per this phase's design, but confirm at least one actually happens.
- The full manual matrix from Phases 2–4 (OCR/Word/Markdown/Compress, single-sandbox and
  sharded, cancellation, fallback, error parity) re-run once more against the **CI-built**
  snapshot specifically — everything before this phase was verified against the
  hand-built one from Phase 2 §1, and this is the first point where the automated
  pipeline's own output is what's actually running.
- The go-live itself: `DAYTONA_ENABLED=true` in production, a real multi-day observation
  window with Hostinger CPU staying flat during offloadable jobs and zero sandboxes
  visible on the Daytona dashboard outside of active jobs — the concrete, observable
  version of "the throttle incidents that started this project don't happen again."
