"""Live progress for the jobs that take long enough to need it.

A backend tool posts every file in one request, so the browser sees one upload
percentage and then nothing at all for however long the server takes. This
module is the channel that fills that silence: services publish where they are,
``app.routers.progress`` streams it back over SSE, and the two are joined by a
job id the client generates and sends as ``X-Job-Id``.

**Latest-value snapshot, not a queue.** Progress is state, not a log. A queue
would either back-pressure the producer — and the producer here is a subprocess
read pump that must never block — or need drop logic of its own. Overwriting a
snapshot and setting an ``asyncio.Event`` coalesces for free, is O(1) per
publish, and losing intermediate frames is exactly right for a progress bar:
the subscriber only ever wants the newest one.

**Progress must never be able to fail a request.** Everything here degrades to
:data:`NULL`, a publisher that does nothing: no ``X-Job-Id`` header, a job id
that has already been used, the registry at its cap. A service never checks for
``None`` and never branches on whether anyone is listening.

The publisher reaches the service layer through a :class:`~contextvars.ContextVar`
rather than seven new endpoint parameters. That is safe here for three specific
reasons, each of which would be worth re-checking if the stack changed: FastAPI
awaits an ``async def`` dependency in the *same* asyncio task as the endpoint,
``CORSMiddleware`` is pure-ASGI (``BaseHTTPMiddleware`` would hop tasks), and
``asyncio.to_thread`` copies the context into the worker.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass, replace

from fastapi import HTTPException

from app import config
from app.services import placement

logger = logging.getLogger(__name__)

QUEUED = "queued"
RUNNING = "running"

# Reasons a stream ends. "gone" is a job the registry never heard about, which
# a subscriber that arrives after the terminal TTL cannot tell from one that
# never existed — and does not need to.
DONE = "done"
ERROR = "error"
TIMEOUT = "timeout"
GONE = "gone"

#: The ``detail`` of the 499 a cancelled batch raises. Never reaches a client.
CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Everything a progress bar needs, in one frame.

    Whole state rather than a delta, deliberately: a subscriber that connects
    late, or that missed frames because the producer outran it, still renders
    correctly from the first frame it receives.

    ``percent`` is progress across the **whole batch**, not within the current
    file, so the bar climbs monotonically through a five-file run instead of
    snapping back to zero four times. Which file that is belongs in the detail
    line, which is what ``file_index`` / ``file_total`` / ``file_name`` are for.
    """

    phase: str = QUEUED
    file_index: int = 0
    file_total: int = 0
    file_name: str = ""
    step: str = ""
    percent: float | None = None
    terminal: bool = False
    reason: str = ""
    #: `placement.SERVER` or `placement.SANDBOX` — where this request is running
    #: *right now*, not where it started. A fallback mid-batch flips this on the
    #: very next frame, so the bar corrects itself instead of lying.
    placement: str = placement.SERVER

    def as_event(self) -> dict[str, object]:
        return {
            "phase": self.phase,
            "file": {
                "index": self.file_index,
                "total": self.file_total,
                "name": self.file_name,
            },
            "step": self.step,
            "percent": self.percent,
            "placement": self.placement,
        }


class Channel:
    """One job's latest snapshot, plus the event subscribers wait on."""

    __slots__ = ("job_id", "snapshot", "_event", "claimed", "expires_at")

    def __init__(self, job_id: str, *, claimed: bool) -> None:
        self.job_id = job_id
        self.snapshot = Snapshot()
        self._event = asyncio.Event()
        # True once a request has claimed this id as its producer. An unclaimed
        # channel is a subscriber that got here first, and expires on its own.
        self.claimed = claimed
        self.expires_at = (
            None if claimed else time.monotonic() + config.PROGRESS_PENDING_TTL_SECONDS
        )

    def publish(self, snapshot: Snapshot) -> None:
        self.snapshot = snapshot
        if snapshot.terminal:
            self.expires_at = time.monotonic() + config.PROGRESS_TERMINAL_TTL_SECONDS
        self._event.set()

    def arm(self) -> None:
        """Re-arm before reading :attr:`snapshot`, never after.

        Clearing the event after the read would drop a publish that landed
        in between, and the subscriber would then sit on a stale frame until
        the next keep-alive — a visible stall on an otherwise live bar.
        """
        self._event.clear()

    async def wait(self, timeout: float) -> bool:
        """Block until the next publish. False if the timeout came first."""
        try:
            async with asyncio.timeout(timeout):
                await self._event.wait()
        except TimeoutError:
            return False
        return True

    @property
    def expired(self) -> bool:
        # >=, not >: a zero TTL (which the tests use) has to mean "gone now",
        # and the monotonic clock can read the same value twice in a row.
        return self.expires_at is not None and time.monotonic() >= self.expires_at


class Registry:
    """Every live job's channel, capped and swept.

    This is the one structure in the service that outlives a request, so it is
    the one that can leak. Two guards, both cheap: a hard cap on the number of
    channels, and an expiry sweep on every touch — no background task to
    supervise, and nothing to leak if the loop is torn down.
    """

    def __init__(self) -> None:
        self._channels: dict[str, Channel] = {}

    def _sweep(self) -> None:
        for job_id in [key for key, ch in self._channels.items() if ch.expired]:
            del self._channels[job_id]

    def claim(self, job_id: str) -> Channel | None:
        """The producer side: take ownership of ``job_id``, or None if we cannot.

        None means the caller runs without progress — the id is already in use
        by another request, or the registry is full. Neither is worth failing a
        request over.
        """
        self._sweep()
        existing = self._channels.get(job_id)
        if existing is not None:
            if existing.claimed:
                logger.info("job id %s is already in use; running without progress", job_id)
                return None
            existing.claimed = True
            existing.expires_at = None
            return existing
        if len(self._channels) >= config.MAX_TRACKED_JOBS:
            logger.warning(
                "progress registry is full (%d jobs); running without progress",
                len(self._channels),
            )
            return None
        channel = Channel(job_id, claimed=True)
        self._channels[job_id] = channel
        return channel

    def subscribe(self, job_id: str) -> Channel | None:
        """The consumer side: the job's channel, creating a pending one if needed.

        A subscriber routinely arrives before the POST it is watching — the
        browser opens the stream first precisely so it cannot miss the start —
        so an unknown id creates a short-lived pending channel rather than 404ing.
        """
        self._sweep()
        existing = self._channels.get(job_id)
        if existing is not None:
            return existing
        if len(self._channels) >= config.MAX_TRACKED_JOBS:
            return None
        channel = Channel(job_id, claimed=False)
        self._channels[job_id] = channel
        return channel

    def release(self, job_id: str) -> None:
        """Let a finished job's channel expire on the terminal TTL, not instantly.

        A job frequently finishes before its stream is even open — Protect on a
        small file beats the browser to it — and the late subscriber has to find
        the terminal snapshot waiting for it.
        """
        channel = self._channels.get(job_id)
        if channel is None:
            return
        if not channel.snapshot.terminal:
            channel.publish(replace(channel.snapshot, terminal=True, reason=DONE))
        self._sweep()

    def count(self) -> int:
        self._sweep()
        return len(self._channels)

    def clear(self) -> None:
        """Tests only."""
        self._channels.clear()


registry = Registry()


class Publisher:
    """What a service holds. Never raises, never blocks, never awaits.

    Intra-file percentages come in 0-100 for the *current file* and are folded
    into a batch-wide percentage here, so a service only ever has to know how
    far through its own file it is.
    """

    __slots__ = ("_channel", "_index", "_total", "_name", "_step", "_percent")

    def __init__(self, channel: Channel) -> None:
        self._channel = channel
        self._index = 0
        self._total = 0
        self._name = ""
        self._step = ""
        self._percent: float | None = None

    def _emit(self, phase: str) -> None:
        self._channel.publish(
            Snapshot(
                phase=phase,
                file_index=self._index,
                file_total=self._total,
                file_name=self._name,
                step=self._step,
                percent=self._percent,
                placement=placement.current(),
            )
        )

    def _overall(self, within_file: float | None) -> float | None:
        if self._total <= 0 or self._index <= 0:
            return None
        done = self._index - 1
        fraction = 0.0 if within_file is None else max(0.0, min(100.0, within_file)) / 100
        return round((done + fraction) / self._total * 100, 1)

    # --- phase, published by the runner's job slot ---------------------------

    def queued(self) -> None:
        self._emit(QUEUED)

    def running(self) -> None:
        self._emit(RUNNING)

    # --- what the services publish -------------------------------------------

    def file(self, index: int, total: int, name: str, step: str = "") -> None:
        """Starting file ``index`` of ``total``. 1-based, like the UI shows it."""
        self._index = index
        self._total = total
        self._name = name
        self._step = step
        self._percent = self._overall(0)
        self._emit(RUNNING)

    def step(self, label: str, within_file: float | None = None) -> None:
        """A named sub-step, optionally with a 0-100 position inside this file."""
        self._step = label
        if within_file is not None:
            self._percent = self._monotonic(self._overall(within_file))
        self._emit(RUNNING)

    def percent(self, within_file: float) -> None:
        """Move the bar without changing the step text."""
        self._percent = self._monotonic(self._overall(within_file))
        self._emit(RUNNING)

    def batch(
        self, *, done: float, total: int, index: int, name: str, step: str
    ) -> None:
        """Set an already-computed batch fraction directly, bypassing ``_overall``.

        For progress that was folded somewhere else — inside a sandbox, by a
        :mod:`app.tools.remote_job` that ran the same services against the same
        files and published through the same :class:`Publisher` code. Its frames
        already carry a whole-batch percentage; pushing that back through
        ``file``/``step``/``percent`` would fold it a second time against this
        process's own ``_index``/``_total`` and produce a number that is simply
        wrong.

        ``done`` and ``total`` are in whole files — ``done=2.4`` of ``total=5``
        is 48%. ``index``, ``name`` and ``step`` only drive the detail line, and
        do not have to be in lockstep with that arithmetic: that is what lets
        one relayed shard and a fold across several share this one method.

        Still monotonic, for the same reason every other mover is.
        """
        self._index = index
        self._total = total
        self._name = name
        self._step = step
        if total > 0:
            self._percent = self._monotonic(round(done / total * 100, 1))
        self._emit(RUNNING)

    def _monotonic(self, candidate: float | None) -> float | None:
        # A bar that goes backwards reads as broken, and the weighted cursors in
        # `compress` can legitimately produce a lower estimate once a step turns
        # out to be skippable. Clamping here is cheaper than every caller
        # getting the arithmetic right.
        if candidate is None:
            return self._percent
        if self._percent is None:
            return candidate
        return max(self._percent, candidate)

    def finish(self, reason: str = DONE) -> None:
        self._channel.publish(
            Snapshot(
                phase=RUNNING,
                file_index=self._index,
                file_total=self._total,
                file_name=self._name,
                step=self._step,
                percent=100.0 if reason == DONE else self._percent,
                placement=placement.current(),
                terminal=True,
                reason=reason,
            )
        )


class NullPublisher(Publisher):
    """The no-op every code path falls back to.

    Same shape and the same bookkeeping as the real one — only the publish is
    dropped. Overriding the single method that touches a channel is what keeps
    this from drifting out of step as :class:`Publisher` grows.
    """

    __slots__ = ()

    def __init__(self) -> None:  # noqa: D107 — there is no channel to hold
        self._channel = None  # type: ignore[assignment]
        self._index = 0
        self._total = 0
        self._name = ""
        self._step = ""
        self._percent = None

    def _emit(self, phase: str) -> None:
        return

    def finish(self, reason: str = DONE) -> None:
        return


NULL = NullPublisher()

#: Set by the ``job_publisher`` dependency, read by every service.
_publisher: ContextVar[Publisher] = ContextVar("pdfkit_progress", default=NULL)

#: Awaited between files so a cancelled request stops the batch. See
#: :func:`client_gone`.
DisconnectProbe = Callable[[], Awaitable[bool]]
_disconnect: ContextVar[DisconnectProbe | None] = ContextVar(
    "pdfkit_disconnect", default=None
)


def current() -> Publisher:
    """The publisher for the request in flight, or the no-op one."""
    return _publisher.get()


def bind(publisher: Publisher, disconnect: DisconnectProbe | None = None) -> None:
    _publisher.set(publisher)
    _disconnect.set(disconnect)


async def client_gone() -> bool:
    """True when the browser has hung up and the rest of the batch is wasted work.

    Aborting the upload XHR does not stop a batched POST on its own — the
    request body arrived long ago. This is the cooperative half: the per-file
    service loops ask between files and stop. One file is the right
    granularity; killing a subprocess mid-write is not worth the complexity.
    """
    probe = _disconnect.get()
    if probe is None:
        return False
    try:
        return await probe()
    except Exception:  # noqa: BLE001 — a disconnect check must never fail a job
        logger.exception("disconnect check raised")
        return False


async def stop_if_cancelled() -> None:
    """Abandon the batch if the client has gone. Call between files, not within.

    499 is nginx's "client closed request": there is nobody left to read the
    status, and it keeps a cancelled run out of the 5xx logs, where it would
    look like a fault.
    """
    if await client_gone():
        logger.info("client disconnected; abandoning the rest of the batch")
        raise HTTPException(status_code=499, detail=CANCELLED)
