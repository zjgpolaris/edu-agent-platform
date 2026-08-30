#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agent_runtime.rollout_config import validate_runtime_rollout_config


def _load_status(url: str) -> dict[str, Any]:
    headers = {"Accept": "application/json", "User-Agent": "edu-agent-runtime-rollout-preflight/1.0"}
    token = os.getenv("API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("rollout status response must be an object")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate an EduAgent Runtime rollout configuration without mutating production.")
    parser.add_argument("--phase", required=True, choices=("control", "shadow"))
    parser.add_argument("--agent-type", required=True)
    parser.add_argument("--status-url", help="Optional admin rollout-status URL used to verify deployed commit and control samples.")
    parser.add_argument("--json", action="store_true", help="Print the structured validation result.")
    args = parser.parse_args()

    try:
        online_status = _load_status(args.status_url) if args.status_url else None
        result = validate_runtime_rollout_config(
            phase=args.phase,
            agent_type=args.agent_type,
            online_status=online_status,
        )
        payload = result.as_dict()
    except Exception as exc:
        payload = {
            "schema_version": 1,
            "phase": args.phase,
            "agent_type": args.agent_type,
            "ok": False,
            "errors": ["rollout_preflight_unavailable"],
            "error_type": exc.__class__.__name__,
        }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        print(f"runtime_rollout_config={'PASS' if payload.get('ok') else 'FAIL'} phase={args.phase} agent={args.agent_type}")
        for error in payload.get("errors") or []:
            print(f"- {error}")
    if payload.get("ok") is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
