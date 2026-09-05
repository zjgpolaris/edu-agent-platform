"""Resolve exact evidence windows without dropping an earlier control baseline."""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timedelta, timezone


def timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ValueError("verification_window_timestamp_invalid") from None


def control_window_start(value: str, *, now: datetime | None = None) -> str:
    if not value:
        raise ValueError("verification_control_window_start_required")
    start = timestamp(value)
    end = now or datetime.now(timezone.utc)
    if not timedelta(0) < end - start <= timedelta(days=7):
        raise ValueError("verification_control_window_out_of_range")
    return start.isoformat()


def resolve_window(*, action: str, generate: bool, requested_start: str = "",
                   requested_end: str = "", traffic_start: str = "", traffic_end: str = "") -> tuple[str, str]:
    if action == "preflight":
        if not requested_start and not requested_end:
            return "", ""
        start, end = timestamp(requested_start), timestamp(requested_end)
    elif generate:
        traffic_from, end = timestamp(traffic_start), timestamp(traffic_end)
        start = timestamp(requested_start) if action == "canary_snapshot" else traffic_from
        if start > traffic_from or traffic_from >= end:
            raise ValueError("verification_window_excludes_traffic")
    else:
        start, end = timestamp(requested_start), timestamp(requested_end)
    if not timedelta(0) < end - start <= timedelta(days=7):
        raise ValueError("verification_window_out_of_range")
    return start.isoformat(), end.isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate-inputs", action="store_true")
    args = parser.parse_args()
    action = os.environ["VERIFY_ACTION"]
    generate = os.environ.get("GENERATE_TRAFFIC") == "true"
    requested_start = os.environ.get("REQUESTED_START", "")
    requested_end = os.environ.get("REQUESTED_END", "")
    if args.validate_inputs:
        if action == "canary_snapshot" and generate:
            control_window_start(requested_start)
        elif not generate or action == "preflight":
            resolve_window(action=action, generate=False, requested_start=requested_start,
                           requested_end=requested_end)
        return
    start, end = resolve_window(
        action=action, generate=generate, requested_start=requested_start, requested_end=requested_end,
        traffic_start=os.environ.get("TRAFFIC_STARTED_AT", ""),
        traffic_end=os.environ.get("TRAFFIC_FINISHED_AT", ""),
    )
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"start={start}\nend={end}\n")


if __name__ == "__main__":
    main()
