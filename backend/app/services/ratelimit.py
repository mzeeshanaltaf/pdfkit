"""Per-IP sliding windows, in process memory.

No Redis, on purpose. The real ceiling on this service is already
``MAX_CONCURRENT_JOBS`` — two — so a limiter exists to stop a script burning
those two slots all day, not to arbitrate a cluster. Losing the counters on
restart is fine; the worst case is one extra burst.

**This is per-process state, and so is ``runner._slots``.** Both are correct
only because ``backend/Dockerfile`` runs uvicorn with ``--workers 1``. Two
workers would silently double every ceiling in this file and the job semaphore
with it. That is the single constraint to remember before scaling this service
out; the fix would be Redis here and a real queue there.

**Getting the client address right matters more than the limits do.** Traefik
reaches this container from a Docker bridge address, and uvicorn's default
``forwarded-allow-ips`` is ``127.0.0.1`` — so without
``FORWARDED_ALLOW_IPS`` set (see ``docker-compose.yml``), ``request.client.host``
is *Traefik* for every visitor on the site and everyone shares one bucket. We
deliberately do not parse ``X-Forwarded-For`` here: uvicorn's ProxyHeaders
middleware already walks it right-to-left and returns the rightmost address
that is not a trusted proxy, which is the correct algorithm and the one that
cannot be spoofed by prepending entries. All this module does is read what
uvicorn worked out.

Everything reads ``config`` attributes at call time so tests can monkeypatch
them — see the note in ``app.services.auth``.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict, deque

from fastapi import HTTPException, Request

from app import config

logger = logging.getLogger(__name__)

RATE_LIMITED = "rate_limited"

# One deque of hit timestamps per (bucket, client), LRU-ordered so a flood of
# unique addresses evicts itself rather than growing without bound.
_windows: OrderedDict[tuple[str, str], deque[float]] = OrderedDict()


def reset() -> None:
    """Drop every window. Tests only — the suite arrives from one address."""
    _windows.clear()


def tracked() -> int:
    return len(_windows)


def client_ip(request: Request) -> str:
    """The caller's address as uvicorn resolved it, or a stable stand-in."""
    client = request.client
    return client.host if client and client.host else "unknown"


def check(bucket: str, identity: str, limit: int, window: int) -> float | None:
    """Record a hit. Returns seconds to wait when over the limit, else None."""
    now = time.monotonic()
    key = (bucket, identity)
    hits = _windows.get(key)
    if hits is None:
        hits = deque()
        _windows[key] = hits
    _windows.move_to_end(key)

    cutoff = now - window
    while hits and hits[0] <= cutoff:
        hits.popleft()

    if len(hits) >= limit:
        # The oldest hit in the window is the one that has to age out.
        return max(1.0, round(hits[0] + window - now, 3))

    hits.append(now)

    while len(_windows) > config.RATE_LIMIT_MAX_CLIENTS:
        _windows.popitem(last=False)
    return None


def enforce(request: Request, bucket: str, *windows: tuple[int, int]) -> None:
    """Apply every window to this request, or raise 429 with ``Retry-After``."""
    identity = client_ip(request)
    for limit, seconds in windows:
        retry_after = check(f"{bucket}:{seconds}", identity, limit, seconds)
        if retry_after is None:
            continue
        logger.info("rate limited %s on %s (%d/%ds)", identity, bucket, limit, seconds)
        raise HTTPException(
            status_code=429,
            detail=RATE_LIMITED,
            headers={"Retry-After": str(int(retry_after) + 1)},
        )
