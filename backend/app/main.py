"""FastAPI entrypoint: CORS, logging and the tool routers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.config import APP_NAME, CORS_ORIGINS
from app.deps import (
    coarse_rate_limit,
    job_publisher,
    job_rate_limit,
    progress_rate_limit,
    require_token,
)
from app.routers import OPEN_ROUTERS, PROCESSING_ROUTERS, STREAM_ROUTERS
from app.routers.progress import open_streams
from app.services import auth, offload, progress, ratelimit

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Sweep sandboxes a previous process never got to delete.

    Nothing is running yet, so anything alive on the account under our label
    is an orphan — the case `try/finally` cannot cover, because a Coolify
    redeploy `SIGKILL`s uvicorn. `sweep_orphans` is best-effort and never
    raises: a failed sweep is a log line, not a refusal to start, and the
    ephemeral/auto-stop/TTL trio still bounds a leak to DAYTONA_TTL_MINUTES.

    A no-op in the default posture, since DAYTONA_ENABLED is false.
    """
    if config.DAYTONA_ENABLED:
        await offload.sweep_orphans()
    yield


app = FastAPI(title=f"{APP_NAME} API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    # Covers X-Job-Id and Authorization, which is also what turns the upload
    # POST into a non-simple request: it now costs one preflight, cached for
    # the browser's default 600 s.
    allow_headers=["*"],
    # A cross-origin fetch() can only read headers listed here, and the UI needs
    # the download name and the before/after sizes.
    expose_headers=[
        "Content-Disposition",
        "X-Original-Size",
        "X-Result-Size",
        "X-File-Stats",
        "X-Processed-On",
    ],
)

# Order is deliberate. The coarse limit bounds an unauthenticated flood before
# anything expensive happens; the token check is cheap and keeps unauthenticated
# callers out of the job limiter's memory entirely; then the real job limit;
# then the publisher, which should only be set up for a request that will run.
for router in PROCESSING_ROUTERS:
    app.include_router(
        router,
        dependencies=[
            Depends(coarse_rate_limit),
            Depends(require_token),
            Depends(job_rate_limit),
            Depends(job_publisher),
        ],
    )

for router in STREAM_ROUTERS:
    app.include_router(
        router,
        dependencies=[
            Depends(coarse_rate_limit),
            Depends(require_token),
            Depends(progress_rate_limit),
        ],
    )

for router in OPEN_ROUTERS:
    app.include_router(router)

if not auth.enabled():
    # One missing Coolify variable would otherwise leave the API open with
    # nothing to notice it by. /health says the same thing, on demand.
    logger.warning(
        "API_TOKEN_SECRET is not set: this API is accepting unauthenticated requests"
    )


@app.get("/health")
async def health(request: Request) -> dict[str, object]:
    """Liveness plus the three numbers that are otherwise invisible.

    ``client`` is the address the rate limiter is keying on. If every visitor
    shows the same Docker bridge address, uvicorn is not trusting the proxy
    headers and the whole site is sharing one bucket — see
    ``FORWARDED_ALLOW_IPS`` in ``docker-compose.yml``. This is the fastest way
    to catch that, and it reports only what the caller already knows about
    itself.
    """
    return {
        "status": "ok",
        "auth": "on" if auth.enabled() else "off",
        "jobs": progress.registry.count(),
        "streams": open_streams(),
        "clients": ratelimit.tracked(),
        "client": ratelimit.client_ip(request),
        # Sandboxes this process is currently using. A local counter, never a
        # Daytona round trip — see `offload.open_sandboxes`. Flat at 0 while
        # offloading is off, and the fastest way to watch the feature during
        # a rollout without opening the Daytona dashboard.
        "sandboxes": offload.open_sandboxes(),
    }
