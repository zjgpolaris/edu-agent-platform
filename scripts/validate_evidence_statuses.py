#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate aggregate evidence status artifacts.")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--release-required", action="store_true")
    args = parser.parse_args()
    failures: list[str] = []
    statuses: list[dict] = []
    for path in args.paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            failures.append(f"missing_or_invalid:{path}")
            continue
        statuses.append(payload)
        status = payload.get("status")
        if status in {"fail", "stale"}:
            failures.append(f"{payload.get('profile')}:{status}")
        if args.release_required and status != "pass":
            failures.append(f"{payload.get('profile')}:release_requires_pass")
    print(json.dumps({"status": "fail" if failures else "pass", "profiles": statuses, "reasons": failures}, ensure_ascii=False, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
