# Phase 10 (part 3) — Daytona offload: wire Word, Markdown, then Compress

## Goal

Extend the offload path built in Phase 2 to the remaining three operations —
`word.to_word`, `markdown.to_markdown`, `compress.compress` — so all four operations named
in the original design (`docs/phases` plan, and `C:\Users\Zeeshan\.claude\plans\i-would-like-to-replicated-storm.md`)
can run remotely. No new orchestration machinery: `offload.maybe_offload()`,
`SandboxPool`, `_DaytonaPool`, and `Publisher.batch()` all already exist from Phase 2. This
phase is three small, mechanical edits plus their tests.

## Prerequisites

Phase 2 done and verified — `offload.py`, `_DaytonaPool`, and `ocr.ocr`'s offload head are
live behind `DAYTONA_ENABLED` (default `false`). Read
`docs/phases/phase-10-daytona-sandbox-offloading-phase2.md` for the orchestrator's shape
before touching this phase; nothing here changes it.

## Context — why Word/Markdown before Compress, reversing the plan's literal ordering

The original plan's phase list said "compress (the real prize), then word, then
markdown." Phase 0's real measurement (`STATUS.md`, "Phase 10 part 0") overturned that
ordering:

| operation | sandbox (4 vCPU) | local (VPS) | speedup |
|---|---|---|---|
| Ghostscript compress | 0.32 s | 0.57 s | 1.75× |
| `ocrmypdf --jobs 1` (per-core) | 1.83 s | 4.78 s | **2.62×** |
| `ocrmypdf --jobs 4` vs local `--jobs 2` (realistic) | 1.07 s | 3.93 s | **3.67×** |

Compress's 1.75× is below the plan's own "≥2×" bar, and the whole operation ran in
0.3–0.6 s on the test fixture — mostly process startup, not real evidence either way. OCR
(already wired, Phase 2) clears the bar with margin. Word and Markdown both route their OCR
sub-step through the same `ocr_to_path` (`ocr.py:220`) that OCR itself uses when
`ocr_mode` calls for it, and `pdf2docx`'s own layout rebuild is real per-page CPU work — so
they inherit OCR's favorable economics whenever OCR fires, and are at worst "compress-like"
otherwise. STATUS.md's own conclusion: **"Order by compute-per-byte... OCR first, then
PDF→Word / PDF→Markdown, Compress last."** This phase follows that: Word and Markdown
first (either order between the two is fine, they're independent), Compress last.

**Compress stays in the offload set** — the plan already anticipated this exact outcome
("still worth shipping for the throttle protection, but the default thresholds and UX copy
change"): a batch of 10+ large files still frees real VPS CPU time by moving ~20
subprocesses per file off the box, even if a single file isn't dramatically faster
per-file. Its win is VPS-CPU protection more than raw speed — worth knowing when tuning
`DAYTONA_MIN_FILES` for it specifically once Phase 5's production data comes in, though
this phase does not add a per-operation override of that knob speculatively; the existing
global `DAYTONA_MIN_FILES`/`DAYTONA_MIN_BYTES` gate all four operations identically, as
designed.

## 1. `backend/app/services/word.py` — the three-line head

`to_word` (`word.py:157`) already returns `list[OutputFile]` directly, so this is the
cleanest possible case — identical shape to `ocr.ocr`'s head from Phase 2:

```python
async def to_word(batch: UploadBatch, ocr_mode: str, languages: list[str]) -> list[OutputFile]:
    if (offloaded := await offload.maybe_offload(
        "word", batch, {"ocr_mode": ocr_mode, "languages": languages}
    )) is not None:
        return offloaded
    workspace = batch.workspace("out")
    ...  # unchanged
```

`remote_job.py`'s `_run_word` dispatch (`remote_job.py:186`) already exists from Phase 1
and already calls `word_service.to_word_one` with these exact two options — nothing on the
sandbox side needs to change.

## 2. `backend/app/services/markdown.py` — the three-line head

Same shape, `to_markdown` (`markdown.py:268`):

```python
async def to_markdown(batch: UploadBatch, ocr_mode: str, languages: list[str]) -> list[OutputFile]:
    if (offloaded := await offload.maybe_offload(
        "markdown", batch, {"ocr_mode": ocr_mode, "languages": languages}
    )) is not None:
        return offloaded
    workspace = batch.workspace("out")
    ...  # unchanged
```

`remote_job.py`'s `_run_markdown` (`remote_job.py:198`) already exists from Phase 1.

## 3. `backend/app/services/compress.py` — the head, plus rebuilding `CompressionResult`

`compress` (`compress.py:564`) doesn't return `list[OutputFile]` — it returns a
`CompressionResult` carrying `original_size`/`result_size`/per-file `FileStat`, computed
from `upload.size` (known locally, before any processing) and `output.path.stat().st_size`
(known only once a file exists on disk — locally or downloaded). `maybe_offload` still
returns the same `list[OutputFile] | None` as every other operation — its own contract
doesn't need to know anything about `CompressionResult` — so `compress`'s head does the
same re-derivation the local path already does, just from a downloaded `outputs` list
instead of a locally-produced one:

```python
async def compress(batch: UploadBatch, level: str) -> CompressionResult:
    if (outputs := await offload.maybe_offload("compress", batch, {"level": level})) is not None:
        return CompressionResult(
            outputs=outputs,
            original_size=sum(upload.size for upload in batch.files),
            result_size=sum(output.path.stat().st_size for output in outputs),
            files=[
                FileStat(
                    name=upload.original_name,
                    original_size=upload.size,
                    result_size=output.path.stat().st_size,
                )
                for upload, output in zip(batch.files, outputs, strict=True)
            ],
        )
    workspace = batch.workspace("out")
    ...  # unchanged
```

This is exactly the local path's own construction (`compress.py:575-587`), copied rather
than factored into a shared helper — the two versions read from different sources
(`batch.files` vs `outputs` that happen to already be downloaded), and forcing them through
one helper would need a parameter just to express that difference. Duplication of four
lines is cheaper than that abstraction.

`remote_job.py`'s `_run_compress` (`remote_job.py:161`) already exists from Phase 1 and
already reaches for `compress_service._Cursor` — nothing on the sandbox side changes here
either. This operation is also the one that most exercises the reason the seam sits at
`compress_one` and not `runner.run`: ~20 subprocesses per file plus
`asyncio.to_thread(streams.survey/rebuild)`/`fonts.subset` all run **inside the sandbox**
now, which is the actual point of offloading Compress at all — Phase 1 already sized
`runner._slots` inside the shim to the sandbox's own vCPU count for exactly this file's
sake, so this phase collects on infrastructure Phase 1 already paid for.

## 4. Config: widen `DAYTONA_OPERATIONS`'s default

Phase 2 defaulted `DAYTONA_OPERATIONS` to `"ocr"` specifically because naming an operation
with no offload head yet would be a silent no-op. Now that all four heads exist, widen the
default in `backend/app/config.py` and `.env.example`:

```python
DAYTONA_OPERATIONS = _parse_origins(os.getenv("DAYTONA_OPERATIONS", "ocr,word,markdown,compress"))
```

Order in the CSV is cosmetic (membership is all `maybe_offload` checks) — written in
compute-per-byte order here to match this phase's own reasoning, not because the code
cares.

## Explicitly out of scope for this phase

- Sharding into more than one sandbox per request (Phase 4) — each of these three
  operations still runs its whole batch through one sandbox, exactly like OCR does today.
- Orphan sweep, `snapshot.yml` CI automation, weekly warm cron, flipping
  `DAYTONA_ENABLED=true` in the real Coolify environment (Phase 5).
- Any new config knob beyond widening `DAYTONA_OPERATIONS`'s default — no per-operation
  `DAYTONA_MIN_FILES` override, even though the Context section above flags Compress as
  the operation most likely to eventually want one. Add it only once Phase 5's production
  data says the shared knob is actually wrong for Compress specifically, not speculatively.

## Testing

Extend `backend/tests/test_offload.py` (from Phase 2) rather than starting a new file —
the `FakeSandboxPool` and decision-matrix machinery are operation-agnostic already:

- Round-trip through the fake pool for `word` and `markdown`, each with `ocr_mode="off"`
  and with an OCR-requiring mode, confirming both the offloaded and local paths produce a
  `.docx` / `.md` with the same shape of result (dispatch correctness here is already
  covered by Phase 1's `tests/test_remote_job.py::test_word_dispatches_to_to_word_one` /
  `test_markdown_dispatches_to_to_markdown_one` — this phase's tests are about the
  `offload.py` head and the caller-side plumbing, not re-proving the shim's own dispatch).
- `compress`: assert the offloaded path's returned `CompressionResult` has correct
  `original_size`/`result_size`/per-file `FileStat` — this is the one operation where the
  three-line head does real work beyond "return the list," so it is the one that most
  needs a dedicated assertion here, not just a smoke pass-through.
- Decision-matrix tests from Phase 2 (`DAYTONA_ENABLED`, `DAYTONA_OPERATIONS`,
  `DAYTONA_MIN_FILES`/`_BYTES`) re-run parametrized across all four operations now, not
  just `ocr` — confirming the gate genuinely applies per-operation and nothing about
  Phase 2's implementation silently special-cased OCR.
- Fallback and error-parity tests (a locked PDF through `compress`/`word`/`markdown`,
  each returning 422 `password_required` identically local vs. offloaded) — reusing the
  same pattern Phase 2 already established for OCR.

## Verification

- `docker compose run --rm backend-tests` green with `DAYTONA_ENABLED` unset — the local
  path for all four operations is unchanged, same as Phase 2's proof for OCR alone.
- Manual matrix with `DAYTONA_ENABLED=true` against the real snapshot: Word and Markdown
  each on `sample-text.pdf` and `sample-scanned.pdf` (covering both the no-OCR and
  OCR-required paths), Compress on a 10-file batch — verify output bytes match the local
  path, the SSE bar rises monotonically to 100 for every operation, download names are
  unchanged, and Compress's done-screen per-file size breakdown (Phase 8's feature) shows
  correct numbers sourced from the re-derived `CompressionResult`.
- Error parity for all three: a locked PDF returns 422 `password_required` identically on
  both paths.
- Re-run the Hostinger-CPU observation from Phase 2's verification, this time during a
  10-file Compress batch specifically — this is the operation with the weakest per-file
  speed evidence, so confirming the VPS itself stays flat during it is the more important
  signal than a per-file timing number for this one.
