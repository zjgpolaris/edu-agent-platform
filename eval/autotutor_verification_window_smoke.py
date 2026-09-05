"""Combined Canary windows retain control; rollback windows exclude old Graph traffic."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.autotutor_verification_window import control_window_start, resolve_window


def main() -> None:
    baseline = "2026-09-05T04:54:05Z"
    traffic_start = "2026-09-05T10:55:57Z"
    traffic_end = "2026-09-05T11:45:00Z"
    common = dict(generate=True, requested_start=baseline, traffic_start=traffic_start, traffic_end=traffic_end)
    assert resolve_window(action="canary_snapshot", **common) == (
        "2026-09-05T04:54:05+00:00", "2026-09-05T11:45:00+00:00")
    for action in ("control_snapshot", "rollback_verify"):
        assert resolve_window(action=action, **common)[0] == "2026-09-05T10:55:57+00:00"
    assert resolve_window(action="preflight", generate=False) == ("", "")
    assert resolve_window(action="canary_snapshot", generate=False,
        requested_start=baseline, requested_end=traffic_end) == resolve_window(action="canary_snapshot", **common)
    for invalid in ("", "not-a-date", "2026-09-05T04:54:05", "2026-08-01T00:00:00Z", "2026-10-01T00:00:00Z"):
        try:
            control_window_start(invalid, now=datetime(2026, 9, 5, 12, tzinfo=timezone.utc))
            raise AssertionError("invalid baseline window accepted")
        except ValueError:
            pass
    for start in ("", traffic_end, "2026-08-01T00:00:00Z"):
        try:
            resolve_window(action="canary_snapshot", **{**common, "requested_start": start})
            raise AssertionError("invalid combined window accepted")
        except ValueError:
            pass
    print("autotutor_verification_window_smoke=PASS")


if __name__ == "__main__":
    main()
