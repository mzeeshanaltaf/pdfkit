"""The progress registry, the SSE stream, and the ContextVar that joins them."""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app import config
from app.services import progress
from app.services.responses import OutputFile

from .conftest import upload


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _empty_registry():
    progress.registry.clear()
    yield
    progress.registry.clear()


@pytest.fixture
def stub_protect(monkeypatch):
    """Protect, minus qpdf.

    These tests are about the plumbing the endpoint runs *around* the tool, so
    standing in for the tool is what lets them run on a developer machine
    instead of only inside the image.
    """
    import shutil

    from app.services import protect as protect_service

    async def fake(upload, workspace, secrets, password, index):
        destination = workspace / f"{upload.path.stem}-protected.pdf"
        shutil.copyfile(upload.path, destination)
        return OutputFile(path=destination, download_name="protected.pdf")

    monkeypatch.setattr(protect_service, "protect_one", fake)
    return fake


JOB = "0" * 32


def test_the_producer_can_arrive_first() -> None:
    channel = progress.registry.claim(JOB)
    assert channel is not None

    publisher = progress.Publisher(channel)
    publisher.file(1, 2, "one.pdf", "Compressing")

    assert progress.registry.subscribe(JOB) is channel
    assert channel.snapshot.file_name == "one.pdf"
    assert channel.snapshot.percent == 0.0


def test_the_subscriber_can_arrive_first() -> None:
    """The normal case: the browser opens the stream, then posts the files."""
    pending = progress.registry.subscribe(JOB)
    assert pending is not None
    assert not pending.claimed

    # Same channel, so the frames the producer publishes reach the subscriber
    # that was already waiting on it.
    assert progress.registry.claim(JOB) is pending
    assert pending.claimed
    assert pending.expires_at is None


def test_a_claimed_job_id_cannot_be_claimed_twice() -> None:
    assert progress.registry.claim(JOB) is not None
    assert progress.registry.claim(JOB) is None


def test_a_late_subscriber_gets_the_terminal_snapshot() -> None:
    """A Protect job routinely finishes before its stream is even open."""
    channel = progress.registry.claim(JOB)
    assert channel is not None
    progress.Publisher(channel).finish(progress.DONE)
    progress.registry.release(JOB)

    late = progress.registry.subscribe(JOB)
    assert late is not None
    assert late.snapshot.terminal
    assert late.snapshot.reason == progress.DONE


def test_a_pending_channel_expires(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROGRESS_PENDING_TTL_SECONDS", 0)
    progress.registry.subscribe(JOB)
    # The sweep runs on every touch, so the next call is what collects it.
    assert progress.registry.count() == 0


def test_a_finished_channel_expires(monkeypatch) -> None:
    monkeypatch.setattr(config, "PROGRESS_TERMINAL_TTL_SECONDS", 0)
    channel = progress.registry.claim(JOB)
    assert channel is not None
    progress.Publisher(channel).finish()
    assert progress.registry.count() == 0


def test_the_cap_refuses_rather_than_failing_a_request(monkeypatch) -> None:
    """Over the cap a job runs without progress; it never fails to run."""
    monkeypatch.setattr(config, "MAX_TRACKED_JOBS", 2)
    assert progress.registry.claim("a" * 32) is not None
    assert progress.registry.claim("b" * 32) is not None
    assert progress.registry.claim("c" * 32) is None


def test_percent_is_batch_wide_and_never_goes_backwards() -> None:
    channel = progress.registry.claim(JOB)
    assert channel is not None
    publisher = progress.Publisher(channel)

    publisher.file(1, 4, "one.pdf")
    publisher.percent(50)
    assert channel.snapshot.percent == 12.5  # half of the first of four

    publisher.file(2, 4, "two.pdf")
    assert channel.snapshot.percent == 25.0

    publisher.percent(50)
    assert channel.snapshot.percent == 37.5

    # A weighted cursor can legitimately estimate lower once a step turns out
    # to be skippable; the bar holds rather than jumping back, which is what
    # reads as broken.
    publisher.percent(10)
    assert channel.snapshot.percent == 37.5


def test_the_null_publisher_swallows_everything() -> None:
    progress.NULL.file(1, 1, "x.pdf")
    progress.NULL.step("anything", 50)
    progress.NULL.percent(90)
    progress.NULL.finish(progress.ERROR)
    assert progress.registry.count() == 0


# --- through the real app ----------------------------------------------------


def test_the_publisher_reaches_the_service_layer(
    client: TestClient, text_pdf: bytes, monkeypatch
) -> None:
    """The ContextVar survives dependency -> endpoint -> service -> to_thread.

    What this actually proves is that FastAPI solves an ``async def``
    dependency in the same task as the endpoint, and that ``to_thread`` copies
    the context — the two assumptions that let the publisher travel this way
    instead of through seven endpoint signatures.
    """
    seen: list[str] = []

    from app.services import protect as protect_service

    async def fake(upload, workspace, secrets, password, index):
        def inside() -> None:
            seen.append(type(progress.current()).__name__)

        # A thread, because compress does its heavy work in one.
        await asyncio.to_thread(inside)
        destination = workspace / "out.pdf"
        destination.write_bytes(upload.path.read_bytes())
        return OutputFile(path=destination, download_name="protected.pdf")

    monkeypatch.setattr(protect_service, "protect_one", fake)

    response = client.post(
        "/protect",
        files=[upload("one.pdf", text_pdf)],
        data={"password": "hunter2"},
        headers={"X-Job-Id": JOB},
    )
    assert response.status_code == 200
    assert seen == ["Publisher"]


def test_the_registry_empties_after_a_run(
    client: TestClient, text_pdf: bytes, monkeypatch, stub_protect
) -> None:
    """A registry leak in a container that runs for weeks is otherwise invisible."""
    monkeypatch.setattr(config, "PROGRESS_TERMINAL_TTL_SECONDS", 0)
    for index in range(5):
        client.post(
            "/protect",
            files=[upload("one.pdf", text_pdf)],
            data={"password": "hunter2"},
            headers={"X-Job-Id": f"{index:032x}"},
        )
    assert progress.registry.count() == 0


def test_a_bad_job_id_is_rejected(client: TestClient) -> None:
    assert client.get("/progress/not-a-job-id").status_code == 400


def test_a_missing_job_id_header_just_means_no_progress(
    client: TestClient, text_pdf: bytes, stub_protect
) -> None:
    client.post("/protect", files=[upload("one.pdf", text_pdf)], data={"password": "x"})
    assert progress.registry.count() == 0


def test_the_stream_reports_a_finished_job(client: TestClient, text_pdf: bytes) -> None:
    channel = progress.registry.claim(JOB)
    assert channel is not None
    publisher = progress.Publisher(channel)
    publisher.file(1, 1, "one.pdf", "Encrypting")
    publisher.finish(progress.DONE)

    with client.stream("GET", f"/progress/{JOB}") as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        body = "".join(response.iter_text())

    events = [line for line in body.splitlines() if line.startswith("event:")]
    assert events == ["event: hello", "event: state", "event: end"]

    state = json.loads(
        next(line for line in body.splitlines() if line.startswith("data:") and "file" in line)[5:]
    )
    assert state["file"] == {"index": 1, "total": 1, "name": "one.pdf"}
    assert state["percent"] == 100.0


def test_an_unknown_job_id_ends_the_stream_rather_than_hanging(
    client: TestClient, monkeypatch
) -> None:
    """Past the cap there is no channel to make, so say so and close."""
    monkeypatch.setattr(config, "MAX_TRACKED_JOBS", 0)
    with client.stream("GET", f"/progress/{JOB}") as response:
        body = "".join(response.iter_text())
    assert '"reason":"gone"' in body
