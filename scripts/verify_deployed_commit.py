#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify that a deployed EduAgent instance serves the expected commit.")
    parser.add_argument("--ready-url", required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.ready_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"require_runtime": "false", "require_rag": "false", "require_external": "false"})
    url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "edu-agent-deployment-verifier/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        payload = json.loads(response.read().decode("utf-8") or "{}")
    deployment = ((payload.get("checks") or {}).get("deployment") or {}) if isinstance(payload, dict) else {}
    actual = str(deployment.get("deployed_commit") or "")
    if actual != args.expected_commit:
        raise SystemExit(f"deployed commit mismatch: expected={args.expected_commit} actual={actual or 'missing'}")
    print(json.dumps({
        "status": "pass",
        "deployed_commit": actual,
        "environment": deployment.get("environment"),
        "runtime_config_version": deployment.get("runtime_config_version"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
