#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from db.engine import get_connection  # noqa: E402
from security.accounts import create_account  # noqa: E402
from sqlalchemy import text  # noqa: E402


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def main() -> None:
    username = os.getenv("ADMIN_USERNAME", "").strip()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not username or len(password) < 12:
        raise SystemExit("ADMIN_USERNAME and ADMIN_PASSWORD (minimum 12 characters) are required")
    actor_id = f"admin-{hashlib.sha256(username.encode('utf-8')).hexdigest()[:24]}"
    with get_connection() as conn:
        existing = conn.execute(text("SELECT actor_id, role FROM accounts WHERE username=:username"), {"username": username}).mappings().first()
    if existing:
        if existing["role"] != "admin":
            raise SystemExit("existing username is not an admin account")
        print(json.dumps({"status": "no_op", "actor_fingerprint": _fingerprint(str(existing["actor_id"]))}, sort_keys=True))
        return
    create_account(actor_id, username, password, "admin", "Runtime Operator", traffic_cohort="operator")
    print(json.dumps({"status": "created", "actor_fingerprint": _fingerprint(actor_id)}, sort_keys=True))


if __name__ == "__main__":
    main()
