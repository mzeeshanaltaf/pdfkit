"""GET /progress/{job_id} — server-sent events for one job.

Hand-rolled SSE over a ``StreamingResponse``: the wire format is four lines and
a blank one, which is not worth a dependency.

The client generates the job id, opens this stream, *then* posts its files with
the same id in ``X-Job-Id``. Opening first is what makes it impossible to miss
the start of a fast job; the registry's pending and terminal TTLs cover the two
orderings that result.

This route is authenticated like every other protected one, which is only
possible because the browser reads it with ``fetch`` rather than
``EventSource`` — ``EventSource`` cannot send an ``Authorization`` header.
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app import config
from app.services import progress, ratelimit

router = APIRouter(tags=["progress"])

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")

# Live streams, so one caller cannot pin every connection the server has. Both
# counters are per-process, like everything else here (see
# ``app.services.ratelimit`` on why that is sound).
_open_per_ip: dict[str, int] = {}


def open_streams() -> int:
    return sum(_open_per_ip.values())


def _frame(event: str, data: object) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode()


KEEP_ALIVE = b": keep-alive\n\n"


async def _events(job_id: str, address: str) -> AsyncIterator[bytes]:
    try:
        yield _frame("hello", {"job": job_id})

        channel = progress.registry.subscribe(job_id)
        if channel is None:
            yield _frame("end", {"reason": progress.GONE})
            return

        # The pristine snapshot carries no information — sending it would tell
        # the client "progress is live" before anything has actually started,
        # and suppress its own fallback to the indeterminate bar.
        last = progress.Snapshot()
        while True:
            channel.arm()
            snapshot = channel.snapshot
            if snapshot != last:
                last = snapshot
                yield _frame("state", snapshot.as_event())
                if snapshot.terminal:
                    yield _frame("end", {"reason": snapshot.reason or progress.DONE})
                    return
                continue
            if not await channel.wait(config.PROGRESS_KEEPALIVE_SECONDS):
                # Traefik closes an idle connection; a comment is not a frame
                # to any SSE parser, so it costs the client nothing.
                yield KEEP_ALIVE
    finally:
        remaining = _open_per_ip.get(address, 1) - 1
        if remaining > 0:
            _open_per_ip[address] = remaining
        else:
            _open_per_ip.pop(address, None)


@router.get("/progress/{job_id}")
async def progress_endpoint(job_id: str, request: Request) -> StreamingResponse:
    if not _JOB_ID.match(job_id):
        raise HTTPException(status_code=400, detail="bad_job_id")

    address = ratelimit.client_ip(request)
    if (
        open_streams() >= config.MAX_STREAMS
        or _open_per_ip.get(address, 0) >= config.MAX_STREAMS_PER_IP
    ):
        raise HTTPException(
            status_code=429, detail=ratelimit.RATE_LIMITED, headers={"Retry-After": "5"}
        )
    # Counted here rather than inside the generator so two opens racing on the
    # same loop iteration cannot both pass the check; the generator's `finally`
    # is what gives it back, and Starlette always runs the generator for a
    # response it has returned.
    _open_per_ip[address] = _open_per_ip.get(address, 0) + 1

    return StreamingResponse(
        _events(job_id, address),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-store",
            # Nginx and some Traefik setups buffer a response body by default,
            # which would hold every frame until the job ended.
            "X-Accel-Buffering": "no",
        },
    )
