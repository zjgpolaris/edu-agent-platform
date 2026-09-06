"""Request-local diagnostic timings; never changes release-gate latency semantics."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from contextvars import ContextVar
from functools import wraps
from time import perf_counter

_current: ContextVar[dict | None] = ContextVar("autotutor_timings", default=None)
# Inherit the server's configured INFO handler (plain root logging defaults to WARNING).
_logger = logging.getLogger("uvicorn.error.autotutor_timing")


def dimension(name: str, value: object) -> None:
    record = _current.get()
    if record is None:
        return
    if name in {"verification_run_id", "transition_id"}:
        record[name + "_sha256"] = hashlib.sha256(str(value).encode()).hexdigest() if value else None
    elif name in {"selected_executor", "transition_kind", "deployed_commit", "config_version", "cache_state"}:
        record[name] = str(value) if re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", str(value)) else None


def timed_call(phase: str, function, *args, **kwargs):
    started = perf_counter()
    try:
        return function(*args, **kwargs)
    finally:
        record = _current.get()
        if record is not None:
            phases = record["phases_ms"]
            phases[phase] = round(phases.get(phase, 0.0) + (perf_counter() - started) * 1000, 3)


def transition_timing(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        record = {"event": "autotutor_transition_timing", "version": 1,
                  "boundary": function.__name__, "phases_ms": {}, "status": "failed"}
        token = _current.set(record)
        started = perf_counter()
        try:
            result = function(*args, **kwargs)
            record["status"] = "replayed" if isinstance(result, dict) and result.get("idempotent_replay") else "returned"
            return result
        finally:
            record["total_ms"] = round((perf_counter() - started) * 1000, 3)
            _current.reset(token)
            # Logging failures must never change a business result or exception.
            try:
                _logger.info(json.dumps(record, sort_keys=True))
            except Exception:
                pass
    return wrapped


def phase_timing(phase: str):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            return timed_call(phase, function, *args, **kwargs)
        return wrapped
    return decorate


def execution_components(outcome) -> None:
    record = _current.get()
    if record is not None and outcome is not None:
        record["execution_components_ms"] = {
            name: getattr(outcome.diagnostics, name)
            for name in ("provider_latency_ms", "executor_latency_ms", "comparator_latency_ms")
        }
