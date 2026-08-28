#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Write a non-secret PASS/FAIL/NOT_RUN evidence status artifact.")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--status", choices=("pass", "fail", "not_run", "stale"), required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--reason", default="")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = None
    if args.report and args.report.is_file():
        try:
            report = json.loads(args.report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            report = None
    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "status": args.status,
        "commit": args.commit,
        "reason": args.reason or None,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "eval_run_id": ((report or {}).get("eval_run") or {}).get("run_id"),
        "report_commit": ((report or {}).get("source_revision") or {}).get("commit_sha"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
