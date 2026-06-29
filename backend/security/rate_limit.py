from __future__ import annotations

import os
import time
from collections import defaultdict, deque

from fastapi import HTTPException

_TRUE_VALUES = {"1", "true", "yes", "on"}
_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def rate_limit_enabled() -> bool:
    enabled = os.getenv("EDU_AGENT_RATE_LIMIT_ENABLED", "false").strip().lower() in _TRUE_VALUES
    if not enabled:
        import logging
        logging.getLogger(__name__).warning("EDU_AGENT_RATE_LIMIT_ENABLED is not set — rate limiting is DISABLED")
    return enabled


def check_rate_limit(key: str, *, limit: int, window_seconds: int) -> None:
    if not rate_limit_enabled():
        return
    now = time.monotonic()
    bucket = _BUCKETS[key]
    while bucket and now - bucket[0] > window_seconds:
        bucket.popleft()
    if len(bucket) >= limit:
        raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试。")
    bucket.append(now)
