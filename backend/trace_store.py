"""Trace store for agent runtime visualization."""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import defaultdict
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4
from deployment import deployed_commit, runtime_config_version

logger = logging.getLogger(__name__)

# Use the same trace_id context variable as tracing.py
_current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)


@dataclass
class TraceEvent:
    """Agent trace event for runtime visualization."""
    trace_id: str
    agent_name: str
    step_name: str
    event_type: str  # "start", "intent", "retrieval", "tool_start", "tool_result", "llm", "memory", "end", "error"
    status: str  # "success", "pending", "error"
    latency_ms: Optional[int] = None
    metadata: Optional[dict[str, Any]] = None
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_sse(self) -> str:
        """Convert to SSE event format."""
        data = self.to_dict()
        return f"event: trace\ndata: {json.dumps(data)}\n\n"


class TraceStore:
    """In-memory trace store for agent runtime visualization."""

    def __init__(self, ttl_seconds: int = 3600):
        self._traces: dict[str, list[dict]] = defaultdict(list)
        self._timestamps: dict[str, float] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = ttl_seconds

    def add_event(self, event: TraceEvent) -> None:
        """Add a trace event."""
        with self._lock:
            self._traces[event.trace_id].append(event.to_dict())
            self._timestamps[event.trace_id] = time.time()

    def get_trace(self, trace_id: str) -> list[dict]:
        """Get all events for a trace."""
        with self._lock:
            return self._traces.get(trace_id, [])

    def list_recent_traces(self, limit: int = 20, *, data_scope: str | None = None) -> list[dict]:
        """Return recent traces with their in-memory events."""
        with self._lock:
            ordered = sorted(self._timestamps.items(), key=lambda item: item[1], reverse=True)
            if data_scope:
                normalized_scope = _normalize_data_scope(data_scope)
                ordered = [
                    item for item in ordered
                    if any(
                        _normalize_data_scope((event.get("metadata") or {}).get("data_scope")) == normalized_scope
                        for event in self._traces.get(item[0], [])
                    )
                ]
            ordered = ordered[: max(1, int(limit))]
            return [
                {
                    "trace_id": trace_id,
                    "latest_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                    "events": list(self._traces.get(trace_id, [])),
                }
                for trace_id, timestamp in ordered
            ]

    def cleanup_old(self) -> int:
        """Clean up expired traces. Returns number of traces removed."""
        now = time.time()
        with self._lock:
            expired = [tid for tid, ts in self._timestamps.items() if now - ts > self._ttl_seconds]
            for tid in expired:
                del self._traces[tid]
                del self._timestamps[tid]
            return len(expired)


# Global trace store instance
_trace_store = TraceStore()


def _normalize_data_scope(value: str | None) -> str:
    normalized = (value or "runtime").strip().lower()
    if normalized == "demo_seed":
        normalized = "demo"
    return normalized if normalized in {"runtime", "eval", "demo"} else "runtime"


def get_trace_store() -> TraceStore:
    """Get the global trace store instance."""
    return _trace_store


def current_trace_id() -> str | None:
    """Get the current trace ID from context."""
    return _current_trace_id.get()


def set_trace_id(trace_id: str) -> None:
    """Set the trace ID in context."""
    _current_trace_id.set(trace_id)


def create_trace_id() -> str:
    """Create a new trace ID."""
    return f"trace_{uuid4().hex[:12]}"


def emit_trace_event(
    agent_name: str,
    step_name: str,
    event_type: str,
    status: str = "success",
    latency_ms: Optional[int] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Emit a trace event to the store."""
    trace_id = current_trace_id()
    if not trace_id:
        logger.warning("emit_trace_event called without trace_id")
        return

    safe_metadata = dict(metadata or {})
    safe_metadata.setdefault("data_scope", _normalize_data_scope(os.getenv("EDU_AGENT_DATA_SCOPE", "runtime")))
    if deployed_commit():
        safe_metadata.setdefault("deployed_commit", deployed_commit())
    if runtime_config_version():
        safe_metadata.setdefault("runtime_config_version", runtime_config_version())
    eval_run_id = os.getenv("EDU_AGENT_EVAL_RUN_ID")
    if eval_run_id:
        safe_metadata.setdefault("eval_run_id", eval_run_id[:96])
    event = TraceEvent(
        trace_id=trace_id,
        agent_name=agent_name,
        step_name=step_name,
        event_type=event_type,
        status=status,
        latency_ms=latency_ms,
        metadata=safe_metadata,
    )
    _trace_store.add_event(event)


@contextmanager
def trace_context(trace_id: str):
    """Context manager for setting trace ID."""
    token = _current_trace_id.set(trace_id)
    try:
        yield trace_id
    finally:
        _current_trace_id.reset(token)
