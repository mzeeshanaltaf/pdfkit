#!/usr/bin/env python3
"""Phase 10 part 0 - Daytona offload measurement spike. THROWAWAY.

Not imported by the app, not wired into anything, and no later phase depends on
it existing. It answers one question: **what is upload/download throughput from
the Hostinger VPS to Daytona?** - plus, secondarily, whether a 4 vCPU sandbox
actually beats a VPS core on the same Ghostscript/OCRmyPDF work.

Run it from inside a container built from the backend image, on the VPS:

    docker run --rm -e DAYTONA_API_KEY -e DAYTONA_API_URL \
        -v /root/pdfkit-spike:/spike --entrypoint python <backend-image> \
        /spike/spike_offload.py

Deliberately **stdlib-only** as far as Daytona is concerned: it talks to the
REST API over ``urllib`` rather than the ``daytona`` SDK, so it runs unmodified
in the production runtime image with nothing installed into it. The only
non-stdlib import is Pillow, which that image already carries, and it is used
for one thing - building the scanned-PDF fixture the way
``backend/tests/conftest.py::build_scanned_pdf`` does.

Everything it creates is deleted on the way out (``--keep`` opts out).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

MB = 1024 * 1024

DEFAULT_API_URL = "https://app.daytona.io/api"
# The SDK derives this per sandbox; the API also hands it out explicitly via
# GET /sandbox/{id}/toolbox-proxy-url. This is only the fallback shape.
TOOLBOX_FALLBACK = "https://proxy.app.daytona.io/toolbox/{sandbox_id}"

# A stand-in for the eventual `pdfkit-toolchain`: the same toolchain the backend
# image installs (Ghostscript, qpdf, Tesseract, OCRmyPDF), minus the 13 extra
# language packs, so it lands in the same ballpark. Built once via
# POST /snapshots and reused; the point of measuring against a *named snapshot*
# rather than an ad-hoc image pull is that Daytona pre-stages the former at
# build time, which is what makes create->ready independent of image size.
SNAPSHOT_DOCKERFILE = (
    "FROM python:3.12-slim-bookworm\n"
    "RUN apt-get update && apt-get install -y --no-install-recommends "
    "ghostscript qpdf tesseract-ocr tesseract-ocr-eng poppler-utils "
    "fonts-dejavu-core && rm -rf /var/lib/apt/lists/*\n"
    "RUN pip install --no-cache-dir ocrmypdf pypdf pillow\n"
    'ENTRYPOINT ["sleep", "infinity"]\n'
)

SANDBOX_LABEL = {"pdfkit-spike": "phase-10-part-0"}


# --- tiny stdlib HTTP client -------------------------------------------------


class ApiError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: bytes) -> None:
        detail = body[:600].decode(errors="replace")
        super().__init__(f"{method} {url} -> {status}: {detail}")
        self.status = status


def _request(
    method: str,
    url: str,
    token: str,
    *,
    json_body: object | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 120.0,
) -> tuple[int, bytes]:
    data = raw_body
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif content_type:
        headers["Content-Type"] = content_type
    # Identity encoding on purpose: a gzipped transfer would measure the
    # compressor, not the link, and real payloads are already-compressed PDFs.
    headers["Accept-Encoding"] = "identity"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        raise ApiError(method, url, error.code, error.read()) from None


def _json(method: str, url: str, token: str, **kwargs) -> object:
    _, body = _request(method, url, token, **kwargs)
    return json.loads(body) if body else None


# --- Daytona ----------------------------------------------------------------


@dataclass
class Daytona:
    token: str
    base: str = DEFAULT_API_URL
    _toolbox: dict = field(default_factory=dict, repr=False)

    # -- snapshots
    def snapshot(self, name: str) -> dict | None:
        url = f"{self.base}/snapshots/{urllib.parse.quote(name)}"
        try:
            return _json("GET", url, self.token)
        except ApiError as error:
            if error.status in (400, 404):
                return None
            raise

    def create_snapshot(self, name: str, cpu: int, memory: int, disk: int) -> dict:
        return _json(
            "POST",
            f"{self.base}/snapshots",
            self.token,
            json_body={
                "name": name,
                # No top-level "entrypoint" alongside buildInfo - the API rejects
                # that pairing ("Cannot specify an entrypoint when using a build
                # info entry"); it goes in the Dockerfile instead.
                "buildInfo": {"dockerfileContent": SNAPSHOT_DOCKERFILE},
                "cpu": cpu,
                "memory": memory,
                "disk": disk,
            },
            timeout=180,
        )

    def wait_snapshot(self, name: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        last = ""
        while time.monotonic() < deadline:
            snapshot = self.snapshot(name) or {}
            state = snapshot.get("state", "?")
            if state != last:
                print(f"    snapshot {name}: {state}", flush=True)
                last = state
            if state == "active":
                return snapshot
            if state in ("error", "build_failed"):
                raise RuntimeError(f"snapshot {name} failed: {snapshot.get('errorReason')}")
            time.sleep(5)
        raise TimeoutError(f"snapshot {name} not active after {timeout:.0f}s (last state {last})")

    # -- sandboxes
    def create_sandbox(self, snapshot: str, target: str | None) -> dict:
        # No cpu/memory/disk here: the API rejects them alongside a snapshot
        # ("Cannot specify Sandbox resources when using a snapshot") - the
        # snapshot's own resources are what the sandbox gets, which is why
        # create_snapshot() carries them instead.
        body: dict = {
            "snapshot": snapshot,
            "labels": SANDBOX_LABEL,
            # Per-job create+delete is the design: nothing here should outlive
            # the spike even if it crashes between create and delete.
            "autoStopInterval": 5,
            "autoDeleteInterval": 0,
            "ttlMinutes": 30,
        }
        if target:
            body["target"] = target
        return _json("POST", f"{self.base}/sandbox", self.token, json_body=body, timeout=180)

    def sandbox(self, sandbox_id: str) -> dict:
        return _json("GET", f"{self.base}/sandbox/{sandbox_id}", self.token)

    def wait_started(self, sandbox_id: str, timeout: float) -> float:
        """Poll until the sandbox reports ``started``; return seconds waited."""
        started = time.perf_counter()
        deadline = started + timeout
        while time.perf_counter() < deadline:
            state = (self.sandbox(sandbox_id) or {}).get("state")
            if state == "started":
                return time.perf_counter() - started
            if state in ("error", "build_failed", "destroyed"):
                raise RuntimeError(f"sandbox {sandbox_id} reached {state}")
            time.sleep(0.15)
        raise TimeoutError(f"sandbox {sandbox_id} not started after {timeout:.0f}s")

    def delete_sandbox(self, sandbox_id: str) -> None:
        url = f"{self.base}/sandbox/{sandbox_id}?force=true"
        _request("DELETE", url, self.token, timeout=120)

    def list_spike_sandboxes(self) -> list:
        labels = urllib.parse.quote(json.dumps(SANDBOX_LABEL))
        payload = _json("GET", f"{self.base}/sandbox?labels={labels}&limit=100", self.token)
        if isinstance(payload, dict):
            return payload.get("items", [])
        return payload or []

    # -- toolbox
    def toolbox(self, sandbox_id: str) -> str:
        if sandbox_id not in self._toolbox:
            url = None
            try:
                payload = _json(
                    "GET", f"{self.base}/sandbox/{sandbox_id}/toolbox-proxy-url", self.token
                )
                if isinstance(payload, dict):
                    url = payload.get("url") or payload.get("toolboxProxyUrl")
                elif isinstance(payload, str):
                    url = payload
            except ApiError:
                url = None
            url = (url or TOOLBOX_FALLBACK.format(sandbox_id=sandbox_id)).rstrip("/")
            # The API hands back the region's proxy root (".../toolbox"), not a
            # per-sandbox URL; every toolbox route is scoped by sandbox id.
            if not url.endswith(sandbox_id):
                url = f"{url}/{sandbox_id}"
            self._toolbox[sandbox_id] = url
        return self._toolbox[sandbox_id]

    def upload(self, sandbox_id: str, path: str, data: bytes) -> None:
        url = f"{self.toolbox(sandbox_id)}/files/upload-v2?path={urllib.parse.quote(path)}"
        _request(
            "POST",
            url,
            self.token,
            raw_body=data,
            content_type="application/octet-stream",
            timeout=900,
        )

    def download(self, sandbox_id: str, path: str) -> bytes:
        url = f"{self.toolbox(sandbox_id)}/files/download?path={urllib.parse.quote(path)}"
        _, body = _request("GET", url, self.token, timeout=900)
        return body

    def exec(
        self, sandbox_id: str, command: str, *, cwd: str | None = None, timeout: int = 900
    ) -> tuple[int, str]:
        body: dict = {"command": command, "timeout": timeout}
        if cwd:
            body["cwd"] = cwd
        payload = _json(
            "POST",
            f"{self.toolbox(sandbox_id)}/process/execute",
            self.token,
            json_body=body,
            timeout=timeout + 60,
        )
        if not isinstance(payload, dict):
            return 0, str(payload)
        code = payload.get("exitCode", payload.get("exit_code", payload.get("code", 0)))
        out = payload.get("result", payload.get("stdout", payload.get("output", "")))
        return int(code or 0), str(out or "")


# --- measurement bookkeeping -------------------------------------------------


@dataclass
class Samples:
    label: str
    seconds: list = field(default_factory=list)
    nbytes: int = 0

    def add(self, seconds: float) -> None:
        self.seconds.append(seconds)

    @property
    def stats(self) -> tuple[float, float, float]:
        return min(self.seconds), statistics.median(self.seconds), max(self.seconds)

    def rates(self) -> tuple[float, float, float]:
        """MB/s at the slowest, median and fastest sample (note the flip)."""
        low, mid, high = self.stats
        scale = self.nbytes / MB
        return scale / high, scale / mid, scale / low


def row(cells: list, widths: list) -> str:
    return "  ".join(cell.ljust(width) for cell, width in zip(cells, widths)).rstrip()


def timed(fn, *args, **kwargs) -> tuple[float, object]:
    start = time.perf_counter()
    result = fn(*args, **kwargs)
    return time.perf_counter() - start, result


# --- fixtures ----------------------------------------------------------------


def build_scanned_pdf(pages: int, text: str = "SCANNED") -> bytes:
    """Mirrors ``tests/conftest.py::build_scanned_pdf`` - an image-only PDF.

    Copied rather than imported: the spike has to run in the runtime image,
    which ships no tests, and a throwaway must not grow an import path into the
    app package.
    """
    from PIL import Image, ImageDraw, ImageFont

    dejavu = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = ImageFont.truetype(str(dejavu), 110) if dejavu.exists() else ImageFont.load_default()
    frames = []
    for number in range(pages):
        canvas = Image.new("RGB", (1240, 1754), "white")
        ImageDraw.Draw(canvas).text((120, 300), f"{text} {number + 1}", fill="black", font=font)
        frames.append(canvas)
    buffer = io.BytesIO()
    frames[0].save(buffer, "PDF", resolution=150.0, save_all=True, append_images=frames[1:])
    return buffer.getvalue()


def app_tarball(app_dir: Path) -> bytes:
    """tar.gz of ``backend/app/`` in memory - the real per-request overhead."""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.add(
            app_dir,
            arcname="app",
            filter=lambda info: None if "__pycache__" in info.name else info,
        )
    return buffer.getvalue()


# --- the operations under test, as identical argv on both sides --------------


def gs_command(source: str, destination: str) -> str:
    # The load-bearing subset of app/services/compress.py::_ghostscript - the
    # flags that decide how much CPU the run costs.
    return (
        "gs -sDEVICE=pdfwrite -dCompatibilityLevel=1.7 -dPDFSETTINGS=/ebook "
        "-dNOPAUSE -dBATCH -dSAFER -dPassThroughJPEGImages=false "
        "-dColorImageDownsampleThreshold=1.0 -dGrayImageDownsampleThreshold=1.0 "
        "-dMonoImageDownsampleThreshold=1.0 -dDetectDuplicateImages=true "
        "-dDownsampleColorImages=true -dColorImageDownsampleType=/Bicubic "
        "-dColorImageResolution=150 -dDownsampleGrayImages=true "
        "-dGrayImageDownsampleType=/Bicubic -dGrayImageResolution=150 "
        f"-sOutputFile={destination} {source}"
    )


def ocr_command(source: str, destination: str, jobs: int) -> str:
    # app/services/ocr.py's argv minus --plugin (progress is not what is timed).
    return f"ocrmypdf -l eng --skip-text --optimize 1 --quiet --jobs {jobs} {source} {destination}"


def run_local(command: str, env: dict | None = None) -> tuple[float, int, str]:
    start = time.perf_counter()
    done = subprocess.run(
        command,
        shell=True,
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
    )
    return time.perf_counter() - start, done.returncode, (done.stdout + done.stderr)[-2000:]


# --- sections ----------------------------------------------------------------


def section(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}", flush=True)


def measure_provisioning(api: Daytona, args) -> tuple:
    """Create ``--provision-repeats`` sandboxes; keep the last one for the work."""
    section(f"1. create -> ready, from named snapshot {args.snapshot!r} (x{args.provision_repeats})")
    create = Samples("create->ready")
    delete = Samples("delete")
    keep = ""
    for attempt in range(args.provision_repeats):
        start = time.perf_counter()
        sandbox = api.create_sandbox(args.snapshot, args.target)
        sandbox_id = sandbox["id"]
        if sandbox.get("state") != "started":
            api.wait_started(sandbox_id, args.provision_timeout)
        elapsed = time.perf_counter() - start
        create.add(elapsed)
        print(f"    #{attempt + 1} {sandbox_id[:8]} ready in {elapsed:6.2f}s", flush=True)
        if attempt == args.provision_repeats - 1:
            keep = sandbox_id
        else:
            taken, _ = timed(api.delete_sandbox, sandbox_id)
            delete.add(taken)
    return create, delete, keep


def measure_transfers(api: Daytona, sandbox_id: str, args) -> list:
    section(f"2. round-trip transfer, {args.sizes} MB payloads (x{args.repeats})")
    results = []
    for megabytes in args.sizes:
        nbytes = megabytes * MB
        # Incompressible on purpose: a zero-filled payload measures gzip, and
        # the real payloads are PDFs whose bulk is already-compressed streams.
        payload = os.urandom(nbytes)
        up = Samples(f"upload {megabytes} MB")
        down = Samples(f"download {megabytes} MB")
        up.nbytes = down.nbytes = nbytes
        remote = f"/tmp/spike-{megabytes}.bin"
        for attempt in range(args.repeats):
            taken, _ = timed(api.upload, sandbox_id, remote, payload)
            up.add(taken)
            taken, blob = timed(api.download, sandbox_id, remote)
            down.add(taken)
            if len(blob) != nbytes:
                raise RuntimeError(f"download returned {len(blob)} bytes, expected {nbytes}")
            print(
                f"    {megabytes:3d} MB #{attempt + 1}  "
                f"up {up.seconds[-1]:6.2f}s ({nbytes / MB / up.seconds[-1]:6.2f} MB/s)  "
                f"down {down.seconds[-1]:6.2f}s ({nbytes / MB / down.seconds[-1]:6.2f} MB/s)",
                flush=True,
            )
        api.exec(sandbox_id, f"rm -f {remote}", timeout=30)
        results.append((megabytes, up, down))
    return results


def measure_tarball(api: Daytona, sandbox_id: str, args) -> Samples | None:
    app_dir = Path(args.app_dir)
    if not app_dir.is_dir():
        section("3. app tarball upload + extract")
        print(f"    skipped: {app_dir} is not a directory", flush=True)
        return None
    blob = app_tarball(app_dir)
    section(f"3. app tarball upload + extract ({len(blob) / 1024:.0f} KB gz, x{args.repeats})")
    samples = Samples("app tarball round trip")
    samples.nbytes = len(blob)
    for attempt in range(args.repeats):
        start = time.perf_counter()
        api.upload(sandbox_id, "/tmp/app.tar.gz", blob)
        code, out = api.exec(
            sandbox_id,
            "rm -rf /work/app && mkdir -p /work/app && tar xzf /tmp/app.tar.gz -C /work/app",
            timeout=120,
        )
        elapsed = time.perf_counter() - start
        if code != 0:
            raise RuntimeError(f"extract failed ({code}): {out[:400]}")
        samples.add(elapsed)
        print(f"    #{attempt + 1} upload+extract {elapsed:6.2f}s", flush=True)
    return samples


def measure_exec(api: Daytona, sandbox_id: str, args) -> list:
    section(f"4. compress / OCR - {args.cpu} vCPU sandbox vs this container (x{args.exec_repeats})")
    _, info = api.exec(sandbox_id, "nproc && free -m | head -2", timeout=60)
    print("    sandbox cpu/mem:\n      " + info.strip().replace("\n", "\n      "), flush=True)
    local_cpus = os.cpu_count() or 1
    print(f"    local (this container) nproc: {local_cpus}", flush=True)

    fixture = build_scanned_pdf(args.pages)
    print(f"    fixture: {args.pages}-page scanned PDF, {len(fixture) / 1024:.0f} KB", flush=True)
    api.upload(sandbox_id, "/tmp/in.pdf", fixture)

    scratch = Path(tempfile.mkdtemp(prefix="spike-", dir=os.environ.get("WORK_DIR") or None))
    local_in = scratch / "in.pdf"
    local_in.write_bytes(fixture)

    # Same argv on both sides. The --jobs 1 row is the honest per-core
    # comparison the kill criterion asks for; the --jobs N row is what the
    # feature would actually buy.
    plans = [
        (
            "compress",
            gs_command("/tmp/in.pdf", "/tmp/out-gs.pdf"),
            gs_command(str(local_in), str(scratch / "out-gs.pdf")),
        ),
        (
            "ocr --jobs 1",
            ocr_command("/tmp/in.pdf", "/tmp/out-ocr1.pdf", 1),
            ocr_command(str(local_in), str(scratch / "out-ocr1.pdf"), 1),
        ),
        (
            f"ocr --jobs {args.cpu}",
            ocr_command("/tmp/in.pdf", f"/tmp/out-ocr{args.cpu}.pdf", args.cpu),
            ocr_command(str(local_in), str(scratch / f"out-ocr{args.cpu}.pdf"), min(args.cpu, local_cpus)),
        ),
    ]

    findings = []
    try:
        for label, remote_cmd, local_cmd in plans:
            remote = Samples(f"sandbox {label}")
            local = Samples(f"local {label}")
            for attempt in range(args.exec_repeats):
                start = time.perf_counter()
                code, out = api.exec(sandbox_id, remote_cmd, timeout=args.exec_timeout)
                elapsed = time.perf_counter() - start
                if code != 0:
                    raise RuntimeError(f"sandbox {label} failed ({code}): {out[-600:]}")
                remote.add(elapsed)

                taken, code, out = run_local(local_cmd, env={"TMPDIR": str(scratch)})
                if code != 0:
                    raise RuntimeError(f"local {label} failed ({code}): {out[-600:]}")
                local.add(taken)
                print(
                    f"    {label:<14} #{attempt + 1}  sandbox {elapsed:6.2f}s   "
                    f"local {taken:6.2f}s   ratio {taken / elapsed:4.2f}x",
                    flush=True,
                )
            findings.append({"label": label, "remote": remote, "local": local})
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return findings


# --- reporting ---------------------------------------------------------------


def verdict(median_mbs: float) -> str:
    if median_mbs < 5:
        return "KILL as designed - 50 MB costs 10s+ per direction; reshape to small files only."
    if median_mbs <= 20:
        return "VIABLE, gated - DAYTONA_MIN_BYTES and per-operation gating are load-bearing. OCR first."
    return "TRANSFER IS NOISE - offload freely; let DAYTONA_MIN_FILES be the gate, not byte count."


def report(create: Samples, delete: Samples, transfers, tarball, execs) -> None:
    section("SUMMARY")
    widths = [22, 9, 9, 9, 11, 11, 11]
    print(row(["measurement", "min s", "med s", "max s", "min MB/s", "med MB/s", "max MB/s"], widths))
    print(row(["-" * w for w in widths], widths))

    for samples in (create, delete):
        if samples.seconds:
            low, mid, high = samples.stats
            print(row([samples.label, f"{low:.2f}", f"{mid:.2f}", f"{high:.2f}", "", "", ""], widths))

    medians = []
    for _, up, down in transfers:
        for samples in (up, down):
            low, mid, high = samples.stats
            r_low, r_mid, r_high = samples.rates()
            medians.append(r_mid)
            print(
                row(
                    [samples.label, f"{low:.2f}", f"{mid:.2f}", f"{high:.2f}",
                     f"{r_low:.2f}", f"{r_mid:.2f}", f"{r_high:.2f}"],
                    widths,
                )
            )

    if tarball is not None:
        low, mid, high = tarball.stats
        print(row([tarball.label, f"{low:.2f}", f"{mid:.2f}", f"{high:.2f}", "", "", ""], widths))

    if execs:
        print()
        exec_widths = [18, 12, 12, 10]
        print(row(["operation", "sandbox s", "local s", "speedup"], exec_widths))
        print(row(["-" * w for w in exec_widths], exec_widths))
        for finding in execs:
            _, remote_mid, _ = finding["remote"].stats
            _, local_mid, _ = finding["local"].stats
            print(
                row(
                    [finding["label"], f"{remote_mid:.2f}", f"{local_mid:.2f}",
                     f"{local_mid / remote_mid:.2f}x"],
                    exec_widths,
                )
            )

    if medians:
        overall = statistics.median(medians)
        print(f"\nmedian throughput across all payload sizes and directions: {overall:.2f} MB/s")
        print(f"verdict: {verdict(overall)}")

    if execs:
        worst = min(f["local"].stats[1] / f["remote"].stats[1] for f in execs)
        tail = (
            "supports 'offload = faster'."
            if worst >= 2
            else "below 2x: offload protects the VPS but is not, on its own, a speed win."
        )
        print(f"slowest sandbox-vs-local ratio: {worst:.2f}x - {tail}")


# --- entrypoint --------------------------------------------------------------


def parse_args(argv: list) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--sizes", default="5,25,50", type=lambda v: [int(x) for x in v.split(",") if x]
    )
    parser.add_argument("--repeats", type=int, default=5, help="transfer samples per size")
    parser.add_argument("--provision-repeats", type=int, default=3)
    parser.add_argument(
        "--exec-repeats",
        type=int,
        default=2,
        help="kept low on purpose: this is the only section that burns VPS CPU",
    )
    parser.add_argument("--pages", type=int, default=8, help="pages in the scanned fixture")
    parser.add_argument(
        "--snapshot", default=os.environ.get("DAYTONA_SNAPSHOT", "pdfkit-spike-toolchain")
    )
    parser.add_argument("--cpu", type=int, default=4)
    parser.add_argument("--memory", type=int, default=4)
    parser.add_argument("--disk", type=int, default=10)
    parser.add_argument("--target", default=os.environ.get("DAYTONA_TARGET") or None)
    parser.add_argument("--app-dir", default="/app/app")
    parser.add_argument("--provision-timeout", type=float, default=150)
    parser.add_argument("--snapshot-timeout", type=float, default=1800)
    parser.add_argument("--exec-timeout", type=int, default=900)
    parser.add_argument("--skip-exec", action="store_true")
    parser.add_argument("--keep", action="store_true", help="leave the last sandbox running")
    parser.add_argument(
        "--cleanup", action="store_true", help="delete leftover spike sandboxes and exit"
    )
    return parser.parse_args(argv)


def main(argv: list) -> int:
    args = parse_args(argv)
    token = os.environ.get("DAYTONA_API_KEY", "").strip()
    if not token:
        print("DAYTONA_API_KEY is not set", file=sys.stderr)
        return 2
    base = os.environ.get("DAYTONA_API_URL", DEFAULT_API_URL).rstrip("/")
    api = Daytona(token=token, base=base)

    if args.cleanup:
        for sandbox in api.list_spike_sandboxes():
            print(f"deleting {sandbox['id']} ({sandbox.get('state')})", flush=True)
            api.delete_sandbox(sandbox["id"])
        return 0

    print(f"api            : {api.base}")
    print(f"this container : {os.cpu_count()} cpus, python {sys.version.split()[0]}")

    section(f"0. snapshot {args.snapshot!r}")
    existing = api.snapshot(args.snapshot)
    if existing is None:
        print("    not found - building (one-time, the cost CI would pay)", flush=True)
        api.create_snapshot(args.snapshot, args.cpu, args.memory, args.disk)
        build_seconds, existing = timed(api.wait_snapshot, args.snapshot, args.snapshot_timeout)
        print(f"    built in {build_seconds:.1f}s", flush=True)
    else:
        state = existing.get("state")
        if state != "active":
            existing = api.wait_snapshot(args.snapshot, args.snapshot_timeout)
        size = existing.get("size")
        suffix = f", {size:.2f} GB" if size else ""
        print(f"    reusing existing snapshot (state={state}{suffix})", flush=True)

    # Sandbox resources come from the snapshot, not from the create call, so
    # these are what --jobs N and the "4 vCPU sandbox" claim actually refer to.
    args.cpu = existing.get("cpu") or args.cpu
    args.memory = existing.get("mem") or args.memory
    args.disk = existing.get("disk") or args.disk
    print(
        f"    sandboxes from it: cpu={args.cpu} memory={args.memory}GiB disk={args.disk}GiB "
        f"target={args.target or 'default'}",
        flush=True,
    )

    sandbox_id = ""
    try:
        create, delete, sandbox_id = measure_provisioning(api, args)
        transfers = measure_transfers(api, sandbox_id, args)
        tarball = measure_tarball(api, sandbox_id, args)
        execs = [] if args.skip_exec else measure_exec(api, sandbox_id, args)
        report(create, delete, transfers, tarball, execs)
    finally:
        if sandbox_id and not args.keep:
            try:
                taken, _ = timed(api.delete_sandbox, sandbox_id)
                print(f"\ndeleted {sandbox_id[:8]} in {taken:.2f}s", flush=True)
            except Exception as error:  # teardown must not mask the real failure
                print(f"\nWARNING: could not delete {sandbox_id}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
