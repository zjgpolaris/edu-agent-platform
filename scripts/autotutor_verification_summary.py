"""Render only allowlisted, scalar traffic-receipt fields into the job summary."""
import json
import re
import sys
from pathlib import Path


def traffic_summary(receipt: dict) -> str:
    fields = (
        "phase", "status", "stage", "expected_commit", "config_version", "error_code",
        "target_transitions", "successful_responses", "transition_request_attempts",
        "server_confirmed_committed", "request_outcome_unknown", "complete",
        "started_at", "finished_at", "control_window_start", "safety_window_end", "next_action",
    )
    lines = ["\n### Controlled traffic receipt\n", "| Field | Value |", "|---|---|"]
    for field in fields:
        value = receipt.get(field)
        rendered = "unknown" if value is None else str(value)
        if not re.fullmatch(r"[A-Za-z0-9_.:+-]{1,160}", rendered):
            rendered = "redacted"
        lines.append(f"| {field} | `{rendered}` |")
    lines.append("\nSuccessful HTTP responses are not proof of server-side committed transitions. "
                 "A running/incomplete receipt is only the last checkpoint, not a release decision.\n")
    return "\n".join(lines)


if __name__ == "__main__":
    path = Path(sys.argv[1])
    if path.is_file():
        print(traffic_summary(json.loads(path.read_text(encoding="utf-8"))))
