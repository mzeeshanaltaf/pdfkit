"""Fire-and-forget sandbox telemetry, posted to the Next app's stats Postgres.

The backend has no database of its own; the stats Postgres belongs to the Next
app, reached over the internal Docker network exactly as the browser already
reaches ``/api/stats/event`` for tool runs. Modelled on ``progress.py``'s
contract: **this must never be able to fail a conversion.** Disabled entirely
whenever either ``STATS_INGEST_URL`` or ``STATS_INGEST_SECRET`` is unset, and
every failure past that point is caught and logged, never raised.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app import config

logger = logging.getLogger(__name__)

#: Short: a slow stats endpoint must never hold a sandbox's teardown open.
_TIMEOUT_SECONDS = 5.0


def record(
    *,
    sandbox_id: str,
    operation: str,
    outcome: str,
    shard_index: int,
    shard_total: int,
    file_count: int,
    alive_seconds: float,
    bytes_up: int,
    bytes_down: int,
) -> None:
    """Fire one shard's lifecycle record as a detached task.

    Never awaited by the caller — ``offload._run_shard`` calls this from its
    own ``finally`` and must not have a slow or unreachable stats endpoint add
    to the time a client waits for its file.
    """
    if not config.STATS_INGEST_URL or not config.STATS_INGEST_SECRET:
        return
    payload = {
        "sandboxId": sandbox_id,
        "operation": operation,
        "outcome": outcome,
        "shardIndex": shard_index,
        "shardTotal": shard_total,
        "fileCount": file_count,
        "aliveSeconds": alive_seconds,
        # The snapshot's fixed resources, not a live reading — Daytona rejects
        # per-sandbox cpu/memory/disk when creating from a snapshot, so every
        # sandbox this app creates carries exactly these three values.
        "cpu": config.DAYTONA_SANDBOX_CPU,
        "memoryGb": config.DAYTONA_SANDBOX_MEMORY_GB,
        "diskGb": config.DAYTONA_SANDBOX_DISK_GB,
        "bytesUp": bytes_up,
        "bytesDown": bytes_down,
    }
    task = asyncio.create_task(_post(payload))
    # A detached task's exception would otherwise only ever surface as an
    # "exception was never retrieved" log line once it is garbage collected.
    # `_post` already catches everything it can reach; this is the backstop
    # for a bug in this module itself.
    task.add_done_callback(_log_if_failed)


async def _post(payload: dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT_SECONDS) as client:
            await client.post(
                config.STATS_INGEST_URL,
                json=payload,
                headers={"X-Stats-Secret": config.STATS_INGEST_SECRET},
            )
    except Exception:  # noqa: BLE001 — telemetry must never surface as a job failure
        logger.warning("could not post sandbox telemetry", exc_info=True)


def _log_if_failed(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.warning("sandbox telemetry task raised: %s", error)
