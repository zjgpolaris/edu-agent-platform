#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def validation_errors(payload: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if str(payload.get("status") or "unknown") != "pass":
        errors.append("rollout gate did not pass")
    if payload.get("run_provenance_coverage") != 1.0:
        errors.append("rollout gate provenance coverage is not 100%")
    if payload.get("observation_write_failures") != 0:
        errors.append("rollout observation writes are unhealthy")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Require a persisted per-agent rollout gate response to pass.")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"rollout gate payload is missing or invalid: {exc}") from exc
    status = str(payload.get("status") or "unknown")
    print(json.dumps({
        "status": status,
        "agent_type": payload.get("agent_type"),
        "config_version": payload.get("config_version"),
        "terminal_runs": payload.get("terminal_runs"),
        "run_provenance_coverage": payload.get("run_provenance_coverage"),
        "observation_write_failures": payload.get("observation_write_failures"),
        "reasons": payload.get("reasons") or [],
    }, ensure_ascii=False, sort_keys=True))
    errors = validation_errors(payload)
    if errors:
        raise SystemExit("; ".join(errors))


if __name__ == "__main__":
    main()
