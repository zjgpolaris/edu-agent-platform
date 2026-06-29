"""Smoke test for agent runtime visualization (trace store)."""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from trace_store import TraceEvent, TraceStore, create_trace_id, emit_trace_event, get_trace_store, trace_context


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def trace_event_serialization() -> None:
    event = TraceEvent(
        trace_id="t1", agent_name="learning_assistant", step_name="intent",
        event_type="intent", status="success", latency_ms=45,
        metadata={"intent": "history_search"},
    )
    d = event.to_dict()
    assert d["trace_id"] == "t1"
    assert d["latency_ms"] == 45
    assert d["metadata"]["intent"] == "history_search"


def trace_store_add_and_get() -> None:
    store = TraceStore(ttl_seconds=3600)
    tid = create_trace_id()
    for step in ("receive_query", "intent_detection"):
        store.add_event(TraceEvent(
            trace_id=tid, agent_name="la", step_name=step,
            event_type="step", status="success",
        ))
    events = store.get_trace(tid)
    assert len(events) == 2
    assert events[0]["step_name"] == "receive_query"


def trace_context_sets_and_clears() -> None:
    from trace_store import current_trace_id
    tid = "ctx_test_001"
    with trace_context(tid):
        assert current_trace_id() == tid
    assert current_trace_id() is None


def emit_trace_event_recorded() -> None:
    store = get_trace_store()
    tid = create_trace_id()
    with trace_context(tid):
        emit_trace_event(
            agent_name="la", step_name="test_step",
            event_type="test", status="success",
            latency_ms=100, metadata={"k": "v"},
        )
    events = store.get_trace(tid)
    assert len(events) == 1
    assert events[0]["step_name"] == "test_step"


def trace_cleanup_removes_expired() -> None:
    store = TraceStore(ttl_seconds=1)
    tid = create_trace_id()
    store.add_event(TraceEvent(
        trace_id=tid, agent_name="t", step_name="s",
        event_type="e", status="success",
    ))
    assert len(store.get_trace(tid)) == 1
    time.sleep(1.1)
    removed = store.cleanup_old()
    assert removed >= 1
    assert len(store.get_trace(tid)) == 0


def main() -> None:
    cases = [
        ("trace_event_serialization", trace_event_serialization),
        ("trace_store_add_and_get", trace_store_add_and_get),
        ("trace_context_sets_and_clears", trace_context_sets_and_clears),
        ("emit_trace_event_recorded", emit_trace_event_recorded),
        ("trace_cleanup_removes_expired", trace_cleanup_removes_expired),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"trace_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
