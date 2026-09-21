"""Build the `pdfkit-toolchain` Daytona snapshot from this repo's Dockerfile.

    DAYTONA_API_KEY=... uv run --with daytona python scripts/build_snapshot.py

Offloading cannot work without this. Daytona's stock snapshots carry no
Ghostscript, no Tesseract and no OCRmyPDF, so `app/tools/remote_job.py` cannot
run on one at all — the snapshot *is* the toolchain, and `app/` is uploaded on
top of it per job.

**The snapshot is the `toolchain` stage of `backend/Dockerfile`**, flattened.
`buildInfo` takes a single Dockerfile, not a target, so this script slices the
`base` stage out of the real file and appends the `toolchain` stage's own
lines — which means the apt package list and the locked dependency install can
never drift from what the backend image itself is built with. `pyproject.toml`
and `uv.lock` ride along as the build context, since `base` copies them.

**The name is the content.** `--print-name` computes
`pdfkit-toolchain-<12 hex>` from the three files that decide what ends up
inside the image (`Dockerfile`, `pyproject.toml`, `uv.lock`), so two runs
against unchanged inputs produce the same name and the second is a no-op under
`--skip-existing`. `.github/workflows/snapshot.yml` drives exactly that, on
those three paths. The name is computed here rather than in the workflow's
shell so there is one definition of it: a human rebuilding by hand and CI
rebuilding on a push cannot disagree about what to call the result.

Nothing updates `DAYTONA_SNAPSHOT` automatically, and that is deliberate. A
dependency bump that has not been snapshotted yet should fail to create a
sandbox and fall back to the VPS - which Phase 2's fallback rule already
treats as an ordinary failure - rather than silently run a toolchain that no
longer matches the lockfile because a name pointing at "latest" moved under a
running deploy.

Re-running a build is a no-op unless `--rebuild` is passed, because a snapshot
name cannot be reused while a snapshot of that name exists.

Daytona deactivates a snapshot after roughly two weeks unused. `--warm` is the
cheapest thing that counts as use: one sandbox created and immediately
deleted. The workflow runs it weekly. At runtime `_DaytonaPool.provision` also
wakes a sleeping snapshot and retries once, so a missed cron costs a round
trip rather than an outage.

Two API constraints found the hard way in Phase 0, both handled below:

* a top-level `entrypoint` may not accompany `buildInfo` ("Cannot specify an
  entrypoint when using a build info entry"), so `ENTRYPOINT ["sleep",
  "infinity"]` goes into the Dockerfile content;
* `cpu`/`memory`/`disk` may not be sent on `POST /sandbox` when creating from a
  snapshot ("Cannot specify Sandbox resources when using a snapshot"), so the
  sandbox's resources are fixed *here*, at build time, from
  `DAYTONA_SANDBOX_CPU` and friends.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from app import config  # noqa: E402  — after the sys.path fix above

DOCKERFILE = PACKAGE_ROOT / "Dockerfile"

#: Files `base` copies. Uploaded as the build context, unchanged.
CONTEXT_FILES = ("pyproject.toml", "uv.lock")

#: What a stage header looks like, whatever its casing.
_STAGE = re.compile(r"^FROM\s+(?P<image>\S+)(?:\s+AS\s+(?P<name>\S+))?\s*$", re.I)

#: Everything whose content changes what ends up inside the snapshot, and so
#: everything the name is computed from. `Dockerfile` for the apt packages and
#: the build itself, the other two for the locked dependency set. Application
#: code is deliberately absent: `app/` is uploaded per job, which is the whole
#: reason a snapshot only goes stale when the *toolchain* moves.
HASHED_FILES = ("Dockerfile", "pyproject.toml", "uv.lock")

#: Names are `pdfkit-toolchain-<hash>`; this is the part before it.
NAME_PREFIX = "pdfkit-toolchain"

#: Enough hex to never collide in a repo's lifetime, short enough to read in a
#: Coolify env var. Matches the plan's `cut -c1-12`.
NAME_HASH_LENGTH = 12


def content_hash() -> str:
    """A stable digest of the three files that decide the image's contents.

    Each file's name goes into the digest alongside its bytes, so swapping two
    files' contents is not the same input. Newlines are normalised because a
    checkout on Windows and one in a Linux CI runner hold the same file with
    different line endings, and they must not build differently-named
    snapshots from identical content.
    """
    digest = hashlib.sha256()
    for name in HASHED_FILES:
        path = PACKAGE_ROOT / name
        if not path.is_file():
            raise SystemExit(f"{name} is missing; it is part of the snapshot's name")
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:NAME_HASH_LENGTH]


def hashed_name() -> str:
    """The name this repo's current toolchain should be snapshotted under."""
    return f"{NAME_PREFIX}-{content_hash()}"


def _client_config(DaytonaConfig):  # noqa: N803 — the class, imported lazily
    """The same credentials and region `app.services.offload` uses."""
    return DaytonaConfig(
        api_key=config.DAYTONA_API_KEY,
        api_url=config.DAYTONA_API_URL,
        target=config.DAYTONA_TARGET or None,
    )


def stage_body(dockerfile: str, name: str) -> tuple[str, list[str]]:
    """The `FROM` image of one stage, and every line inside it."""
    image: str | None = None
    lines: list[str] = []
    for line in dockerfile.splitlines():
        header = _STAGE.match(line.strip())
        if header:
            if image is not None:
                break
            if (header.group("name") or "").lower() == name.lower():
                image = header.group("image")
            continue
        if image is not None:
            lines.append(line)
    if image is None:
        raise SystemExit(f"{DOCKERFILE} has no stage named {name!r}")
    return image, lines


def flatten() -> tuple[str, list[str]]:
    """The `toolchain` stage as one context-free base image plus commands.

    `toolchain` is `FROM base`, so its real content is base's lines followed by
    its own — which is exactly what a single-stage build of it would run.
    """
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    image, base = stage_body(dockerfile, "base")
    _, toolchain = stage_body(dockerfile, "toolchain")
    commands = [line for line in base + toolchain if line.strip()]
    return image, commands


async def exists(client, name: str) -> bool:
    """Whether a snapshot of this name is already on the account.

    "Not there" arrives as an exception rather than a None, so anything that
    is not a successful get is read as absent - the build that follows is the
    thing that will report a real API problem properly.
    """
    try:
        await client.snapshot.get(name)
    except Exception:  # noqa: BLE001 - see the docstring
        return False
    return True


async def warm(name: str) -> None:
    """Create and immediately delete one sandbox, so the snapshot stays active.

    Daytona deactivates a snapshot after ~2 weeks unused. This is the cheapest
    thing that counts as use - no upload, no command, no work - and is what
    the workflow's weekly cron runs.
    """
    from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams, DaytonaConfig

    client = AsyncDaytona(_client_config(DaytonaConfig))
    sandbox = None
    try:
        sandbox = await client.create(
            CreateSandboxFromSnapshotParams(
                snapshot=name,
                ephemeral=True,
                auto_stop_interval=config.DAYTONA_AUTO_STOP_MINUTES,
                ttl_minutes=config.DAYTONA_TTL_MINUTES,
                # The same label the app's own sandboxes carry, so a warm run
                # interrupted by a cancelled CI job is swept up by the next
                # backend startup exactly like any other orphan.
                labels={"app": "pdfkit", "job": "warm"},
            )
        )
        print(f"{name} is warm (sandbox {sandbox.id})")
    finally:
        if sandbox is not None:
            await sandbox.delete()
            print("sandbox deleted")
        await client.close()


async def build(name: str, rebuild: bool, skip_existing: bool = False) -> None:
    from daytona import (
        AsyncDaytona,
        CreateSnapshotParams,
        DaytonaConfig,
        Image,
        Resources,
    )

    image_name, commands = flatten()
    print(f"toolchain stage: FROM {image_name}, {len(commands)} commands")

    image = Image.base(image_name).dockerfile_commands(commands, context_dir=PACKAGE_ROOT)
    for required in CONTEXT_FILES:
        if not (PACKAGE_ROOT / required).is_file():
            raise SystemExit(f"{required} is missing; the build context needs it")

    client = AsyncDaytona(_client_config(DaytonaConfig))
    try:
        if skip_existing and not rebuild and await exists(client, name):
            # The idempotent path, and the one a re-run on unchanged inputs
            # takes: the name is the content, so a snapshot already carrying
            # it was built from exactly these three files.
            print(f"{name} already exists; nothing to build")
            return

        if rebuild:
            print(f"deleting the existing {name} snapshot")
            try:
                await client.snapshot.delete(await client.snapshot.get(name))
            except Exception as error:  # noqa: BLE001 — "not there" is the happy case
                print(f"  nothing to delete ({type(error).__name__}: {error})")

        print(
            f"building {name}: {config.DAYTONA_SANDBOX_CPU} vCPU, "
            f"{config.DAYTONA_SANDBOX_MEMORY_GB} GB, "
            f"{config.DAYTONA_SANDBOX_DISK_GB} GB disk"
        )
        await client.snapshot.create(
            CreateSnapshotParams(
                name=name,
                image=image,
                resources=Resources(
                    cpu=config.DAYTONA_SANDBOX_CPU,
                    memory=config.DAYTONA_SANDBOX_MEMORY_GB,
                    disk=config.DAYTONA_SANDBOX_DISK_GB,
                ),
                # No `entrypoint=` here — it is in the Dockerfile content, and
                # passing both is rejected outright.
            ),
            on_logs=print,
        )
        print(f"\n{name} is built. Confirm it before wiring anything to it:")
        print("  python scripts/build_snapshot.py --verify")
    finally:
        await client.close()


async def verify(name: str) -> None:
    """Prove the snapshot can actually do the work, on a throwaway sandbox."""
    from daytona import AsyncDaytona, CreateSandboxFromSnapshotParams, DaytonaConfig

    client = AsyncDaytona(_client_config(DaytonaConfig))
    sandbox = None
    try:
        sandbox = await client.create(
            CreateSandboxFromSnapshotParams(
                snapshot=name,
                ephemeral=True,
                auto_stop_interval=config.DAYTONA_AUTO_STOP_MINUTES,
                ttl_minutes=config.DAYTONA_TTL_MINUTES,
                labels={"app": "pdfkit", "job": "verify"},
            )
        )
        print(f"sandbox {sandbox.id} is up")
        for command in (
            "gs --version",
            "qpdf --version",
            "tesseract --list-langs",
            "ocrmypdf --version",
            "/opt/venv/bin/python -c 'import ocrmypdf, pypdf, fitz; print(1)'",
            # The measurement that decides how a sandbox must be told its size.
            "nproc; cat /sys/fs/cgroup/cpu.max",
        ):
            result = await sandbox.process.exec(command)
            head = (result.result or "").strip().splitlines()
            print(f"  $ {command}\n    exit {result.exit_code}: {head[:3]}")
    finally:
        if sandbox is not None:
            await sandbox.delete()
            print("sandbox deleted")
        await client.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default=config.DAYTONA_SNAPSHOT)
    parser.add_argument(
        "--rebuild",
        action="store_true",
        help="delete the snapshot of this name first (a name cannot be reused)",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="skip the build; just create a throwaway sandbox and check the tools",
    )
    parser.add_argument(
        "--warm",
        action="store_true",
        help="create and delete one sandbox, so the snapshot stays active",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="do nothing if a snapshot of this name is already there",
    )
    parser.add_argument(
        "--print-name",
        dest="print_name",
        action="store_true",
        help="print pdfkit-toolchain-<content hash> and exit, touching no API",
    )
    parser.add_argument(
        "--print",
        dest="show",
        action="store_true",
        help="print the flattened Dockerfile and exit, touching no API",
    )
    args = parser.parse_args()

    if args.print_name:
        print(hashed_name())
        return 0

    if args.show:
        image, commands = flatten()
        print(f"FROM {image}")
        print("\n".join(commands))
        return 0

    if not config.DAYTONA_API_KEY:
        raise SystemExit("DAYTONA_API_KEY is not set")

    if args.verify:
        asyncio.run(verify(args.name))
    elif args.warm:
        asyncio.run(warm(args.name))
    else:
        asyncio.run(build(args.name, args.rebuild, args.skip_existing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
