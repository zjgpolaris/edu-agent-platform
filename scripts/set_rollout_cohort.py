#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from security.accounts import get_account, set_account_cohort  # noqa: E402
from security.audit_log import record_audit_event  # noqa: E402


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    parser = argparse.ArgumentParser(description="Approve or revoke one account's trusted rollout cohort.")
    parser.add_argument("--actor-id", required=True)
    parser.add_argument("--cohort", choices=("verified", "unverified"), required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    actor_id = args.actor_id.strip()
    if actor_id.startswith("pilot-"):
        raise SystemExit("pilot accounts cannot join the verified rollout cohort")
    account = get_account(actor_id)
    if not account:
        raise SystemExit("account not found")
    if account["role"] != "student":
        raise SystemExit("only student accounts can join the verified rollout cohort")
    previous = str(account["traffic_cohort"])
    if previous == "demo":
        raise SystemExit("demo accounts cannot join the verified rollout cohort")
    changed = previous != args.cohort and set_account_cohort(actor_id, args.cohort)
    fingerprint = _fingerprint(actor_id)
    record_audit_event(
        actor_id=None,
        action="rollout.cohort_updated",
        resource_type="account_fingerprint",
        resource_id=fingerprint,
        success=True,
        metadata={"from": previous, "to": args.cohort, "reason_code": args.reason[:80]},
    )
    print(json.dumps({"status": "updated" if changed else "no_op", "actor_fingerprint": fingerprint, "cohort": args.cohort}, sort_keys=True))


if __name__ == "__main__":
    main()
