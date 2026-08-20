from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from agent_runtime.recovery import recover_stale_runs

logger = logging.getLogger(__name__)
_TRUE_VALUES = {"1", "true", "yes", "on"}


def recovery_worker_enabled() -> bool:
    return os.getenv("EDU_AGENT_RUNTIME_V2_RECOVERY_ENABLED", "false").strip().lower() in _TRUE_VALUES


def _bounded_seconds(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def recover_once(*, stale_seconds: int | None = None) -> dict[str, int]:
    stale = stale_seconds or _bounded_seconds(
        "EDU_AGENT_RUNTIME_V2_RECOVERY_STALE_SECONDS",
        600,
        minimum=60,
        maximum=86_400,
    )
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale)).isoformat()
    return recover_stale_runs(updated_before=cutoff)


async def recovery_worker_loop(
    stop: asyncio.Event,
    *,
    poll_seconds: float | None = None,
    stale_seconds: int | None = None,
) -> None:
    interval = poll_seconds or float(_bounded_seconds(
        "EDU_AGENT_RUNTIME_V2_RECOVERY_POLL_SECONDS",
        30,
        minimum=5,
        maximum=3600,
    ))
    while not stop.is_set():
        try:
            await asyncio.to_thread(recover_once, stale_seconds=stale_seconds)
        except Exception:
            logger.exception("agent_runtime_recovery_failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass
