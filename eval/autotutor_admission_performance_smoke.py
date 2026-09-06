"""Deterministic slow-query, single-flight and invalidation regressions."""
from __future__ import annotations

import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "eval"))
from autotutor_canary_admission_smoke import _settings, _context
from agents import autotutor_canary_admission as admission


def evaluate(**kwargs):
    return admission.evaluate_autotutor_canary_admission(settings=_settings(**kwargs), context=_context())


def main():
    schema = {"schema_ready": True, "alembic_version": "017"}
    health = {"ok": True, "status": "ok"}
    ticks = [0.0]
    def slow_schema():
        ticks[0] += 12
        return schema
    admission.clear_autotutor_canary_admission_cache()
    with patch.object(admission.time, "monotonic", side_effect=lambda: ticks[0]), \
         patch("agent_runtime.readiness.runtime_schema_readiness", side_effect=slow_schema) as reads, \
         patch("agent_runtime.rollout_observations.observation_write_health", return_value=health):
        first = evaluate()
        assert evaluate() is first and reads.call_count == 1
        ticks[0] = 22
        assert evaluate() is not first and reads.call_count == 2
        assert not evaluate(EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH="true").admitted
        assert reads.call_count == 2
        evaluate(EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION="changed")
        assert reads.call_count == 3

    # Both successful and failed leaders release all same-key waiters.
    for fail in (False, True):
        admission.clear_autotutor_canary_admission_cache()
        entered, release, waiting = threading.Event(), threading.Event(), threading.Event()
        wait_count = [0]
        lock = threading.Lock()
        original_timed = admission.timed_call
        def timed(phase, function, *args, **kwargs):
            if phase == "admission_wait":
                with lock:
                    wait_count[0] += 1
                    if wait_count[0] == 3:
                        waiting.set()
            return original_timed(phase, function, *args, **kwargs)
        def blocked_schema():
            entered.set()
            assert release.wait(3)
            if fail:
                raise RuntimeError("private database error")
            return schema
        with patch("agent_runtime.readiness.runtime_schema_readiness", side_effect=blocked_schema) as reads, \
             patch("agent_runtime.rollout_observations.observation_write_health", return_value=health), \
             patch.object(admission, "timed_call", side_effect=timed), ThreadPoolExecutor(max_workers=4) as pool:
            leader = pool.submit(evaluate)
            try:
                assert entered.wait(2)
                followers = [pool.submit(evaluate) for _ in range(3)]
                assert waiting.wait(2)
            finally:
                release.set()
            results = [leader.result(2)] + [future.result(2) for future in followers]
            assert reads.call_count == 1
            assert all(result is results[0] for result in results)
            assert all(result.admitted is (not fail) for result in results)

    admission.clear_autotutor_canary_admission_cache()
    entered, release = threading.Event(), threading.Event()
    def blocked():
        entered.set()
        assert release.wait(3)
        return schema
    with patch("agent_runtime.readiness.runtime_schema_readiness", side_effect=blocked) as reads, \
         patch("agent_runtime.rollout_observations.observation_write_health", return_value=health), \
         patch.object(admission, "_REFRESH_WAIT_SECONDS", 0.01), ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(evaluate)
        try:
            assert entered.wait(2)
            timeout = evaluate()
            assert not timeout.admitted and timeout.reason_codes == ("admission_refresh_timeout",)
            admission.clear_autotutor_canary_admission_cache()
        finally:
            release.set()
        assert leader.result(2).reason_codes == ("admission_refresh_invalidated",)
        assert evaluate().admitted and reads.call_count == 2
    admission.clear_autotutor_canary_admission_cache()
    print("autotutor_admission_performance_smoke=PASS")


if __name__ == "__main__":
    main()
