"""Phase 10's offload verification matrix, run against a real Daytona account.

The unit tests are offline by design — they inject a fake pool, so they can
prove the orchestration is right but never that Daytona behaves as assumed.
This is the other half: the real API, the real `pdfkit-toolchain` snapshot, and
the real `offload` module with nothing stubbed.

    docker compose run --rm -e DAYTONA_API_KEY=... \\
        -v /path/to/backend/scripts:/harness backend-tests \\
        python /harness/verify_offload.py matrix --pages 6
    ... verify_offload.py timings --pages 50
    ... verify_offload.py sharding --files 10

`matrix` is the phase plan's manual checklist, automated: output parity against
the local path, error parity on an encrypted PDF for all four operations, a
wrong snapshot name falling back, a real cancellation leaving nothing behind,
Word and Markdown on both a born-digital document and a scan, and Compress on a
ten-file batch checked on the per-file size breakdown its done screen shows.
`timings` answers the different question of *where an offloaded batch's wall
clock goes*, by wrapping the real pool and timing each phase — so the transfer
half, which depends entirely on where the caller sits, can be read apart from
the compute half, which does not. `--operation` picks which head it measures,
so Phase 3's "does the VPS stay flat during a Compress batch?" is
`timings --operation compress --files 10 --remote-only`.
`sharding` is Phase 4's own pair of questions, and the only mode that
deliberately runs the same batch twice: is provisioning N sandboxes at once
really the cost of provisioning one (the premise the whole design rests on,
measured in Phase 0 on a residential link and never re-checked from the VPS),
and does a batch actually finish sooner split across them?

**Run `timings` from the VPS, not a workstation, before believing its verdict.**
Phase 0 measured the VPS-to-Daytona link at ~60 MB/s and a residential link at
~1.4 MB/s — a 40x difference that swamps everything else in the breakdown. A
dev machine will also usually out-compute a 4 vCPU sandbox, which the throttled
2 vCPU VPS will not.

Kept in the repo rather than thrown away, unlike Phase 0's spike: Phase 3 added
the other three offload heads, Phase 4 sharded a batch across several
sandboxes, and Phase 5 flips the feature on — every one of them wants to re-run
exactly this.
"""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

# Importable both from a checkout (scripts/ beside app/) and from inside the
# test image, where this file is bind-mounted somewhere else entirely and the
# package lives at the working directory instead.
for candidate in (Path(__file__).resolve().parents[1], Path.cwd()):
    if (candidate / "app" / "config.py").is_file():
        sys.path.insert(0, str(candidate))
        break
else:
    raise SystemExit("cannot find the app package; run this from backend/ or in the image")

from fastapi import HTTPException  # noqa: E402

from app import config  # noqa: E402
from app.deps import SavedUpload, UploadBatch  # noqa: E402
from app.services import errors, offload, progress  # noqa: E402
from app.services import compress as compress_service  # noqa: E402
from app.services import markdown as markdown_service  # noqa: E402
from app.services import ocr as ocr_service  # noqa: E402
from app.services import word as word_service  # noqa: E402

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((PASS if ok else FAIL, name))
    print(f"  [{PASS if ok else FAIL}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def fixtures():
    """The test suite's own generators, so this measures the same documents."""
    from tests.conftest import build_scanned_pdf, build_text_pdf, encrypt_pdf

    return build_scanned_pdf, build_text_pdf, encrypt_pdf


def batch_of(root: Path, sources: dict[str, bytes]) -> UploadBatch:
    batch = UploadBatch(directory=root)
    inputs = batch.workspace("in")
    for index, (name, data) in enumerate(sources.items()):
        path = inputs / f"{index:02d}-{name}"
        path.write_bytes(data)
        batch.files.append(SavedUpload(path=path, original_name=name, size=len(data)))
    return batch


class Frames(progress.NullPublisher):
    """Every percentage the SSE endpoint would have sent, in order.

    ``details`` carries the text beside the bar as well, because a sharded
    batch can be perfectly monotonic and still read as incoherent if the file
    name jumps between shards — which is the one thing about `FanIn` only a
    human can judge.
    """

    def __init__(self) -> None:
        super().__init__()
        self.percents: list[float | None] = []
        self.details: list[tuple[int, str, str]] = []

    def _emit(self, phase: str) -> None:
        self.percents.append(self._percent)
        self.details.append((self._index, self._name, self._step))

    def finish(self, reason: str = progress.DONE) -> None:
        self.percents.append(100.0 if reason == progress.DONE else self._percent)


async def sandboxes_alive() -> set[str]:
    from daytona import AsyncDaytona, DaytonaConfig, ListSandboxesQuery

    client = AsyncDaytona(
        DaytonaConfig(
            api_key=config.DAYTONA_API_KEY,
            api_url=config.DAYTONA_API_URL,
            target=config.DAYTONA_TARGET or None,
        )
    )
    try:
        return {sandbox.id async for sandbox in client.list(ListSandboxesQuery(limit=100))}
    finally:
        await client.close()


def words(data: bytes) -> list[str]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return " ".join(page.extract_text() or "" for page in reader.pages).split()


# --- the four operations -----------------------------------------------------
#
# Phase 3 gave `word`, `markdown` and `compress` the same three-line head `ocr`
# got in Phase 2, so everything below that used to say "ocr" now says "whichever
# of the four". One table, because the only thing that differs between them is
# which driver to call and what a readable output looks like.


async def drive(operation: str, batch: UploadBatch) -> list:
    """Run one batch through the real driver, and hand back its output files.

    Compress returns a `CompressionResult` rather than a list; its `.outputs`
    is the comparable part, and `compress_numbers` below checks the rest.
    """
    if operation == "ocr":
        return await ocr_service.ocr(batch, ["eng"])
    if operation == "word":
        return await word_service.to_word(batch, "auto", ["eng"])
    if operation == "markdown":
        return await markdown_service.to_markdown(batch, "auto", ["eng"])
    if operation == "compress":
        return (await compress_service.compress(batch, "recommended")).outputs
    raise SystemExit(f"unknown operation {operation!r}")


def readable(operation: str, output) -> str:
    """What a user would actually see in the file, for comparing two runs.

    Not the bytes: OCRmyPDF stamps a creation time and a document id into every
    PDF it writes, and Ghostscript is no more reproducible, so byte equality is
    the wrong assertion on three of the four. What must match is the content.
    """
    if operation == "markdown":
        return output.path.read_text(encoding="utf-8")
    if operation == "word":
        from tests.test_convert import docx_text

        return docx_text(output.path.read_bytes())
    return " ".join(words(output.path.read_bytes()))


#: Set by ``--corpus-dir``: real documents to measure instead of generated
#: ones. A module global rather than a parameter because every mode reaches
#: ``corpus`` through a different call chain, and threading an override
#: through all of them would be more code than the feature is worth.
CORPUS_DIR: Path | None = None


def corpus(operation: str, pages: int, files: int) -> dict[str, bytes]:
    """`files` documents of the kind that makes this operation do real work.

    A scan for the three that OCR (Word and Markdown are driven with
    ``ocr="auto"`` here precisely because that is the sub-step they inherit
    OCR's economics from), and a photo page for Compress, which is the input
    Ghostscript genuinely shrinks.

    **Unless ``--corpus-dir`` names real documents**, in which case those are
    used verbatim. That option exists because Phase 4 measured Compress on one
    synthetic photo page per file and found it a wall-clock loss — a finding
    about that corpus, not about the operation, since a real Compress input is
    a 5-50 MB multi-page scan where Ghostscript's share of the time is far
    larger. Deciding whether `compress` belongs in `DAYTONA_OPERATIONS` needs
    the documents users actually upload, not the ones that iterate fastest.
    """
    if CORPUS_DIR is not None:
        return real_corpus(files)
    build_scanned_pdf, _, _ = fixtures()
    if operation == "compress":
        from tests.conftest import build_photo_pdf

        source = build_photo_pdf()
    else:
        source = build_scanned_pdf(pages)
    return {f"{index:02d}.pdf": source for index in range(files)}


def real_corpus(files: int) -> dict[str, bytes]:
    """`files` documents from ``--corpus-dir``, cycled if there are too few.

    Sorted by name so two runs measure the same batch in the same order, and
    anything over MAX_UPLOAD_BYTES is dropped rather than measured: the app
    would refuse it at the door, so timing it would describe a request that
    cannot happen.
    """
    assert CORPUS_DIR is not None
    available = sorted(
        path
        for path in CORPUS_DIR.glob("*.pdf")
        if path.stat().st_size <= config.MAX_UPLOAD_BYTES
    )
    if not available:
        raise SystemExit(f"{CORPUS_DIR} holds no PDF under {config.MAX_UPLOAD_MB} MB")
    sources: dict[str, bytes] = {}
    for index in range(files):
        source = available[index % len(available)]
        sources[f"{index:02d}-{source.name}"] = source.read_bytes()
    return sources


# --- the matrix --------------------------------------------------------------


async def parity(root: Path, pages: int) -> None:
    """The same document down both paths, compared on what a user can see."""
    print("\n1. output parity, remote vs local")
    build_scanned_pdf, _, _ = fixtures()
    scan = build_scanned_pdf(pages)

    config.DAYTONA_ENABLED = False
    local = await ocr_service.ocr(batch_of(root / "local", {"scan.pdf": scan}), ["eng"])
    local_bytes = local[0].path.read_bytes()

    config.DAYTONA_ENABLED = True
    frames = Frames()
    progress.bind(frames, None)
    remote = await ocr_service.ocr(batch_of(root / "remote", {"scan.pdf": scan}), ["eng"])
    remote_bytes = remote[0].path.read_bytes()
    progress.bind(progress.NULL, None)

    record(
        "the download name is unchanged",
        local[0].download_name == remote[0].download_name == "scan-ocr.pdf",
        repr(remote[0].download_name),
    )
    # Not byte-identical, and cannot be: OCRmyPDF stamps a creation time and a
    # document id into every output. Same size to within a byte or two, and the
    # same extracted text, is the real assertion.
    record(
        "the output is the same document",
        remote_bytes.startswith(b"%PDF-") and abs(len(remote_bytes) - len(local_bytes)) <= 64,
        f"local {len(local_bytes):,} B, remote {len(remote_bytes):,} B",
    )
    record(
        "the same text layer came back",
        words(local_bytes) == words(remote_bytes) and words(remote_bytes),
        f"{len(words(remote_bytes))} words, identical on both sides",
    )
    moved = [percent for percent in frames.percents if percent is not None]
    record(
        "the bar rises monotonically and reaches 100",
        bool(moved) and moved == sorted(moved) and moved[-1] == 100.0,
        f"{len(moved)} frames, {moved[0]} → {moved[-1]}",
    )


async def error_parity(root: Path) -> None:
    """An encrypted PDF is the user's problem either way, and identically so.

    All four operations, because a document failure must never be retried
    locally — it would fail identically there, having also burned the round
    trip — and that is a property of the orchestrator, not of OCR.
    """
    print("\n2. error parity on an encrypted PDF, all four operations")
    _, build_text_pdf, encrypt_pdf = fixtures()
    (root / "enc").mkdir(parents=True, exist_ok=True)
    locked = encrypt_pdf(build_text_pdf(), "hunter2", root / "enc")

    for operation in ("ocr", "word", "markdown", "compress"):
        seen: dict[bool, str] = {}
        for enabled in (False, True):
            config.DAYTONA_ENABLED = enabled
            try:
                await drive(
                    operation,
                    batch_of(root / f"err-{operation}-{enabled}", {"l.pdf": locked}),
                )
                seen[enabled] = "no error at all"
            except HTTPException as error:
                seen[enabled] = f"{error.status_code} {error.detail}"

        record(
            f"{operation}: identical 422 with offloading off and on",
            seen[False] == seen[True] == f"422 {errors.PASSWORD_REQUIRED}",
            f"off: {seen[False]}, on: {seen[True]}",
        )


async def wrong_snapshot(root: Path) -> None:
    """Infrastructure that is simply missing must be invisible to the user."""
    print("\n3. a deliberately wrong DAYTONA_SNAPSHOT falls back to local")
    build_scanned_pdf, _, _ = fixtures()
    config.DAYTONA_ENABLED = True
    previous, config.DAYTONA_SNAPSHOT = config.DAYTONA_SNAPSHOT, "pdfkit-does-not-exist"
    try:
        outputs = await ocr_service.ocr(
            batch_of(root / "wrong", {"scan.pdf": build_scanned_pdf(1)}), ["eng"]
        )
        record(
            "a correct file still came back, from the local loop",
            len(outputs) == 1 and outputs[0].path.read_bytes().startswith(b"%PDF-"),
            f"{outputs[0].download_name}, {outputs[0].path.stat().st_size:,} B",
        )
    except Exception as error:  # noqa: BLE001 — a raise here is the failure
        record("a correct file still came back", False, f"{type(error).__name__}: {error}")
    finally:
        config.DAYTONA_SNAPSHOT = previous


async def cancellation(root: Path, pages: int) -> None:
    """A client that hangs up gets 499, and its sandbox does not survive it."""
    print("\n4. cancelling a real remote run")
    build_scanned_pdf, _, _ = fixtures()
    config.DAYTONA_ENABLED = True
    offload.WATCHDOG_SECONDS = 1.0

    hung_up = False

    async def client_gone() -> bool:
        return hung_up

    class HangUpOnFirstFrame(progress.NullPublisher):
        """Hang up the moment the sandbox says it has started work.

        This used to be `sleep(6)`, and that made the section lie: the same
        6-page batch took ~10 s when it was written and now finishes in under
        six, so the "client" was hanging up after it already had its file and
        the check failed with "no error" — reading exactly like a cancellation
        regression. The first progress frame is the earliest moment at which
        there is definitely something left to cancel, and it does not move when
        the feature gets faster.
        """

        def _emit(self, phase: str) -> None:
            nonlocal hung_up
            hung_up = True

    progress.bind(HangUpOnFirstFrame(), client_gone)

    outcome = "no error"
    started = time.perf_counter()
    try:
        await offload.maybe_offload(
            "ocr", batch_of(root / "cancel", {"scan.pdf": build_scanned_pdf(pages)}), {"languages": ["eng"]}
        )
    except HTTPException as error:
        outcome = f"{error.status_code} {error.detail}"
    elapsed = time.perf_counter() - started
    progress.bind(progress.NULL, None)
    if outcome == "no error":
        outcome = f"no error — the batch finished in {elapsed:.1f}s"

    record("the client is told 499 cancelled", outcome == f"499 {progress.CANCELLED}", outcome)

    # `sandbox.delete()` defaults to wait=False, so the delete is queued rather
    # than finished when dispose() returns. The criterion is "gone within
    # seconds", which is what a human refreshing the dashboard would check.
    alive, waited = await sandboxes_alive(), 0.0
    while alive and waited < 30:
        await asyncio.sleep(2)
        waited += 2
        alive = await sandboxes_alive()
    record(
        "no sandbox is left running",
        not alive,
        f"gone after {waited:.0f}s" if not alive else f"still alive: {sorted(alive)}",
    )


async def other_heads(root: Path, pages: int) -> None:
    """Word and Markdown, each on a born-digital file and on a scan.

    Two documents per operation because the two go down different roads: the
    born-digital one is the cheap path, and the scan is the one that routes
    through `ocr_to_path` and so inherits OCR's measured 2.62x. Both have to
    come back saying the same thing they say locally.
    """
    print("\n5. Word and Markdown, remote vs local")
    build_scanned_pdf, build_text_pdf, _ = fixtures()

    for operation in ("word", "markdown"):
        extension = "docx" if operation == "word" else "md"
        for label, source in (
            ("text", build_text_pdf(pages)),
            ("scan", build_scanned_pdf(pages)),
        ):
            where = f"{operation} on a {label} document"
            config.DAYTONA_ENABLED = False
            local = await drive(
                operation, batch_of(root / f"{operation}-{label}-l", {"a.pdf": source})
            )

            config.DAYTONA_ENABLED = True
            frames = Frames()
            progress.bind(frames, None)
            remote = await drive(
                operation, batch_of(root / f"{operation}-{label}-r", {"a.pdf": source})
            )
            progress.bind(progress.NULL, None)

            record(
                f"{where}: the download name is unchanged",
                local[0].download_name == remote[0].download_name == f"a.{extension}",
                repr(remote[0].download_name),
            )
            local_text, remote_text = readable(operation, local[0]), readable(
                operation, remote[0]
            )
            record(
                f"{where}: the same content came back",
                bool(remote_text) and remote_text == local_text,
                f"{len(remote_text):,} characters, identical on both sides",
            )
            moved = [percent for percent in frames.percents if percent is not None]
            record(
                f"{where}: the bar rises monotonically to 100",
                bool(moved) and moved == sorted(moved) and moved[-1] == 100.0,
                f"{len(moved)} frames, {moved[0]} → {moved[-1]}",
            )


async def compress_numbers(root: Path, files: int) -> None:
    """Compress on a real batch, checked on the numbers its done screen shows.

    The one head that does more than return the list: `maybe_offload` hands
    back `list[OutputFile]` like it does everywhere else, so the per-file size
    breakdown Phase 8 added is re-derived from the downloaded files. Wrong
    there and the user sees plausible-looking nonsense rather than an error —
    which is why this asserts the numbers rather than "a file came back".
    """
    print(f"\n6. Compress on a {files}-file batch")
    sources = corpus("compress", 1, files)

    config.DAYTONA_ENABLED = False
    local = await compress_service.compress(batch_of(root / "cmp-local", sources), "recommended")

    config.DAYTONA_ENABLED = True
    frames = Frames()
    progress.bind(frames, None)
    remote = await compress_service.compress(batch_of(root / "cmp-remote", sources), "recommended")
    progress.bind(progress.NULL, None)

    record(
        "every file came back, with unchanged download names",
        [output.download_name for output in remote.outputs]
        == [output.download_name for output in local.outputs]
        and len(remote.outputs) == files,
        f"{len(remote.outputs)} files, e.g. {remote.outputs[0].download_name}",
    )
    record(
        "the per-file breakdown names the same files at the same original sizes",
        [(stat.name, stat.original_size) for stat in remote.files]
        == [(stat.name, stat.original_size) for stat in local.files],
        f"{len(remote.files)} rows",
    )
    record(
        "each row's result size is the file that actually arrived",
        [stat.result_size for stat in remote.files]
        == [output.path.stat().st_size for output in remote.outputs]
        and all(stat.result_size > 0 for stat in remote.files),
        f"{remote.result_size:,} B from {remote.original_size:,} B",
    )
    # Ghostscript is not reproducible to the byte, so the two runs are compared
    # on the ratio they report rather than on equality.
    local_ratio = local.result_size / local.original_size
    remote_ratio = remote.result_size / remote.original_size
    record(
        "the batch shrank by the same amount either way",
        abs(local_ratio - remote_ratio) < 0.02,
        f"local {local_ratio:.1%}, remote {remote_ratio:.1%} of the original",
    )
    moved = [percent for percent in frames.percents if percent is not None]
    record(
        "the bar rises monotonically to 100 across the whole batch",
        bool(moved) and moved == sorted(moved) and moved[-1] == 100.0,
        f"{len(moved)} frames, {moved[0]} → {moved[-1]}",
    )

async def run_matrix(root: Path, pages: int, files: int) -> int:
    await parity(root, pages)
    await error_parity(root)
    await wrong_snapshot(root)
    await cancellation(root, pages)
    await other_heads(root, pages)
    await compress_numbers(root, files)

    failed = [name for status, name in results if status == FAIL]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    for name in failed:
        print(f"  FAIL  {name}")
    return 1 if failed else 0


# --- sharding, part 4 --------------------------------------------------------


async def parallel_create(count: int) -> None:
    """Is creating `count` sandboxes at once really the cost of creating one?

    The entire economic basis for sharding. Phase 0 measured 2-in-parallel at
    the same 1.43 s as one — but on a residential link, in a different session,
    and its VPS spike only ever timed a *single* create (0.79 s). If this
    prints anything near `count`x, sharding still works and still parallelises
    the compute; it just costs more up front than the design assumed, and
    `DAYTONA_MAX_SANDBOXES` wants tuning with that in mind.
    """
    print(f"\n1. provisioning: one sandbox, then {count} at once")
    pool = offload.pool_factory()
    # A throwaway create first. The first one in a process also pays for the
    # client, its TLS handshake and the snapshot lookup, and charging all of
    # that to the single-sandbox number flatters the comparison: the first run
    # of this measured 3.46 s alone against 1.13 s for two in parallel, which
    # is not a thing that can be true.
    await pool.dispose(await pool.provision())

    started = time.perf_counter()
    alone_id = await pool.provision()
    alone = time.perf_counter() - started
    await pool.dispose(alone_id)

    pool = offload.pool_factory()
    started = time.perf_counter()
    ids = await asyncio.gather(*(pool.provision() for _ in range(count)))
    together = time.perf_counter() - started
    await asyncio.gather(*(pool.dispose(sandbox_id) for sandbox_id in ids))

    ratio = together / max(alone, 1e-6)
    print(f"  1 sandbox:  {alone:5.2f}s")
    print(f"  {count} sandboxes: {together:5.2f}s   ({ratio:.2f}x the cost of one)")
    record(
        f"{count} sandboxes cost roughly one, not {count}",
        ratio <= 1.5,
        f"{ratio:.2f}x — record this number in STATUS.md either way",
    )


class Alive:
    """How many sandboxes existed at once while a batch was running.

    Polled rather than counted from inside `offload`, because the question is
    what the Daytona dashboard would have shown — the same thing a human is
    asked to look at in this phase's manual check.
    """

    #: Seconds between samples. A batch shorter than a few of these cannot be
    #: sampled at all, which `sharded_batch` says out loud rather than calling
    #: an unobserved run a failure.
    INTERVAL = 1.0

    def __init__(self) -> None:
        self.peak = 0
        self._task: asyncio.Task | None = None

    async def _poll(self) -> None:
        while True:
            self.peak = max(self.peak, len(await sandboxes_alive()))
            await asyncio.sleep(self.INTERVAL)

    def __enter__(self) -> Alive:
        self._task = asyncio.create_task(self._poll())
        return self

    def __exit__(self, *_: object) -> None:
        if self._task is not None:
            self._task.cancel()


async def one_run(root: Path, operation: str, sources: dict[str, bytes], shards: int):
    """The batch, through exactly `shards` sandboxes. Returns (seconds, peak, frames)."""
    config.DAYTONA_MAX_SANDBOXES = shards
    offload.reset()  # the semaphore is sized on first use, so drop the old one
    frames = Frames()
    progress.bind(frames, None)
    with Alive() as alive:
        started = time.perf_counter()
        outputs = await drive(operation, batch_of(root, sources))
        seconds = time.perf_counter() - started
    progress.bind(progress.NULL, None)
    if len(outputs) != len(sources):
        record(f"{shards}-sandbox run produced every file", False, f"{len(outputs)} files")
    if alive.peak == 0 and seconds > 3 * Alive.INTERVAL:
        # Long enough to have been sampled, and nothing was ever alive: this
        # batch fell back to the VPS, and every number taken from it is a
        # local one wearing a remote label. Worth saying loudly — a silent
        # fallback is exactly what this feature does when it cannot run, and
        # it is the reason the first live run of this looked like a 1.15x win.
        record(
            f"the {shards}-sandbox run actually went to Daytona",
            False,
            "no sandbox was ever alive — it fell back to the local path",
        )
    return seconds, alive.peak, frames


async def drain(limit: float = 60.0) -> int:
    """Wait for the account to empty, so a count of live sandboxes means something.

    `sandbox.delete()` is queued rather than finished when it returns, so a
    sandbox from the previous section can still be listed while the next one
    is counting them.
    """
    waited = 0.0
    while waited < limit:
        if not await sandboxes_alive():
            return 0
        await asyncio.sleep(2)
        waited += 2
    return len(await sandboxes_alive())


async def sharded_batch(root: Path, pages: int, files: int, operation: str, shards: int) -> None:
    """The payoff: the same batch through one sandbox, then through `shards`."""
    print(f"\n2. a {files}-file {operation} batch, one sandbox vs {shards}")
    left = await drain()
    if left:
        print(f"  ({left} sandbox(es) from earlier are still being deleted)")
    sources = corpus(operation, pages, files)
    config.DAYTONA_ENABLED = True

    single_seconds, single_peak, _ = await one_run(root / "shard-one", operation, sources, 1)
    print(f"  1 sandbox:  {single_seconds:6.1f}s  (peak {single_peak} alive)")
    sharded_seconds, peak, frames = await one_run(root / "shard-n", operation, sources, shards)
    print(f"  {shards} sandboxes: {sharded_seconds:6.1f}s  (peak {peak} alive)")

    if sharded_seconds < 3 * Alive.INTERVAL:
        print(
            f"  (only {sharded_seconds:.1f}s long — too short to sample how many "
            f"sandboxes were alive; peak seen was {peak})"
        )
    else:
        record(
            f"{shards} sandboxes really ran at once",
            peak >= shards,
            f"peak {peak} alive during the batch",
        )
    record(
        "the sharded batch finished sooner",
        sharded_seconds < single_seconds,
        f"{single_seconds / max(sharded_seconds, 1e-6):.2f}x faster",
    )

    moved = [percent for percent in frames.percents if percent is not None]
    record("the bar never went backwards", moved == sorted(moved), f"{len(moved)} frames")
    record("the bar reached 100", bool(moved) and moved[-1] == 100.0, f"ended at {moved[-1] if moved else None}")

    # Nothing here can judge whether the detail line *reads* as coherent, so
    # print it and let whoever is running this look. A name changing every few
    # frames is right; one alternating between two unrelated files is not.
    print("\n  the text beside the bar, deduplicated:")
    last = None
    for index, name, step in frames.details:
        if (index, name, step) != last:
            print(f"    file {index}  {name:<24}{step}")
            last = (index, name, step)

    alive, waited = await sandboxes_alive(), 0.0
    while alive and waited < 30:
        await asyncio.sleep(2)
        waited += 2
        alive = await sandboxes_alive()
    record(
        "every shard's sandbox is gone afterwards",
        not alive,
        f"gone after {waited:.0f}s" if not alive else f"still alive: {sorted(alive)}",
    )


async def run_sharding(root: Path, pages: int, files: int, operation: str) -> int:
    shards = max(2, config.DAYTONA_MAX_SANDBOXES)
    await parallel_create(shards)
    await sharded_batch(root, pages, files, operation, shards)

    failed = [name for status, name in results if status == FAIL]
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    for name in failed:
        print(f"  FAIL  {name}")
    return 1 if failed else 0


# --- the breakdown -----------------------------------------------------------

spent: dict[str, float] = defaultdict(float)
moved_bytes: dict[str, int] = defaultdict(int)


class Timed:
    """The real pool, with a stopwatch on every call."""

    def __init__(self, inner: offload.SandboxPool) -> None:
        self._inner = inner

    async def provision(self) -> str:
        return await self._clock("provision", self._inner.provision())

    async def put(self, sandbox_id: str, path: str, data: bytes) -> None:
        moved_bytes["up"] += len(data)
        return await self._clock("upload", self._inner.put(sandbox_id, path, data))

    async def get(self, sandbox_id: str, path: str) -> bytes:
        data = await self._clock("download", self._inner.get(sandbox_id, path))
        moved_bytes["down"] += len(data)
        return data

    async def run(self, sandbox_id: str, command: str, **kwargs) -> int:
        label = "exec (shim)" if "remote_job" in command else "exec (unpack)"
        return await self._clock(label, self._inner.run(sandbox_id, command, **kwargs))

    async def dispose(self, sandbox_id: str) -> None:
        return await self._clock("dispose", self._inner.dispose(sandbox_id))

    @staticmethod
    async def _clock(label: str, awaitable):
        started = time.perf_counter()
        try:
            return await awaitable
        finally:
            spent[label] += time.perf_counter() - started


async def run_timings(
    root: Path,
    pages: int,
    remote_only: bool = False,
    operation: str = "ocr",
    files: int = 1,
) -> int:
    print(f"building the {operation} corpus ({files} file(s))…", flush=True)
    sources = corpus(operation, pages, files)
    total = sum(len(data) for data in sources.values())
    for name, data in sources.items():
        print(f"    {name:<52}{len(data):>12,} B", flush=True)
    print(
        f"  {total:,} bytes; --jobs {config.MAX_CONCURRENT_JOBS} locally, "
        f"{config.DAYTONA_SANDBOX_CPU} in the sandbox\n",
        flush=True,
    )

    local_seconds = 0.0
    if not remote_only:
        config.DAYTONA_ENABLED = False
        started = time.perf_counter()
        local = await drive(operation, batch_of(root / "t-local", sources))
        local_seconds = time.perf_counter() - started
        produced = sum(output.path.stat().st_size for output in local)
        print(f"local:  {local_seconds:6.1f}s -> {produced:,} B", flush=True)

    config.DAYTONA_ENABLED = True
    real = offload.pool_factory
    offload.pool_factory = lambda: Timed(real())
    # Wall-clock markers, not just a duration: an external CPU sampler has to be
    # able to say which of its samples belong to the remote phase and which are
    # this process building a fixture. Without them the VPS's own idleness —
    # the entire point of the feature — cannot be attributed to anything.
    print(f"REMOTE-START {time.time():.3f}", flush=True)
    started = time.perf_counter()
    remote = await drive(operation, batch_of(root / "t-remote", sources))
    remote_seconds = time.perf_counter() - started
    print(f"REMOTE-END {time.time():.3f}", flush=True)
    produced = sum(output.path.stat().st_size for output in remote)
    print(f"remote: {remote_seconds:6.1f}s -> {produced:,} B\n", flush=True)

    shards = min(files, max(1, config.DAYTONA_MAX_SANDBOXES))
    print("where the remote wall clock went:")
    if shards > 1:
        # The stopwatch sums each call's own duration, and since Phase 4 the
        # shards' calls overlap — so the percentages add up to more than 100
        # and "(unaccounted)" goes negative. Measured -3.78 s on a two-shard
        # 10-file Compress batch, which reads like a bug and is not one. Run
        # with DAYTONA_MAX_SANDBOXES=1 for a breakdown that sums.
        print(
            f"  (across {shards} shards, so these overlap: they sum to more than"
            " the wall clock. Use DAYTONA_MAX_SANDBOXES=1 for a clean split.)"
        )
    for label, seconds in sorted(spent.items(), key=lambda item: -item[1]):
        print(f"  {label:<16}{seconds:6.2f}s  ({seconds / remote_seconds * 100:4.1f}%)")
    print(f"  {'(unaccounted)':<16}{remote_seconds - sum(spent.values()):6.2f}s")
    print(f"\n  {moved_bytes['up']:,} B up, {moved_bytes['down']:,} B down")

    transfer = spent["upload"] + spent["download"]
    compute = spent["exec (shim)"]
    print(f"\n  transfer:        {transfer:5.1f}s   <- the number that depends on where you ran this")
    print(f"  other overhead:  {remote_seconds - transfer - compute:5.1f}s")
    print(f"  sandbox compute: {compute:5.1f}s")
    if local_seconds:
        print(f"  local compute:   {local_seconds:5.1f}s")
        if compute:
            print(f"  compute speedup: {local_seconds / compute:5.2f}x")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("matrix", "timings", "sharding"))
    parser.add_argument("--pages", type=int, default=6)
    parser.add_argument(
        "--remote-only",
        action="store_true",
        help="skip the local baseline, so an external CPU sampler measures only the offload",
    )
    parser.add_argument(
        "--operation",
        choices=("ocr", "word", "markdown", "compress"),
        default="ocr",
        help="which offload head `timings` measures (the matrix always covers all four)",
    )
    parser.add_argument(
        "--files",
        type=int,
        default=1,
        help="batch size; the matrix uses it for its Compress batch, `timings` for its corpus",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help=(
            "measure real PDFs from this directory instead of generated ones "
            "(cycled if it holds fewer than --files; anything over the upload "
            "limit is skipped)"
        ),
    )
    args = parser.parse_args()

    if args.corpus_dir is not None:
        if not args.corpus_dir.is_dir():
            raise SystemExit(f"{args.corpus_dir} is not a directory")
        global CORPUS_DIR
        CORPUS_DIR = args.corpus_dir

    if not os.getenv("DAYTONA_API_KEY"):
        raise SystemExit("DAYTONA_API_KEY is not set")
    config.DAYTONA_API_KEY = os.environ["DAYTONA_API_KEY"]
    # This script is the thing under test, not the gate in front of it.
    config.DAYTONA_MIN_FILES = 1
    config.DAYTONA_MIN_BYTES = 0

    root = Path(config.WORK_DIR) / "verify-offload"
    root.mkdir(parents=True, exist_ok=True)
    print(f"snapshot={config.DAYTONA_SNAPSHOT} target={config.DAYTONA_TARGET}")
    if CORPUS_DIR is not None:
        print(f"corpus={CORPUS_DIR} (real documents, not generated)")

    if args.mode == "matrix":
        return asyncio.run(run_matrix(root, args.pages, max(args.files, 10)))
    if args.mode == "sharding":
        return asyncio.run(
            run_sharding(root, args.pages, max(args.files, 10), args.operation)
        )
    return asyncio.run(
        run_timings(root, args.pages, args.remote_only, args.operation, args.files)
    )


if __name__ == "__main__":
    raise SystemExit(main())
