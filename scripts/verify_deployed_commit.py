#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify that a deployed EduAgent instance serves the expected commit.")
    parser.add_argument("--ready-url", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-image-digest")
    parser.add_argument("--expected-config-version")
    parser.add_argument("--attempts", type=int, default=1)
    parser.add_argument("--interval-seconds", type=int, default=5)
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.ready_url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({"require_runtime": "false", "require_rag": "false", "require_external": "false"})
    url = urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "edu-agent-deployment-verifier/1.0"})
    deployment: dict = {}
    for attempt in range(max(1, args.attempts)):
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8") or "{}")
            deployment = ((payload.get("checks") or {}).get("deployment") or {}) if isinstance(payload, dict) else {}
        except Exception:
            deployment = {}
        actual = str(deployment.get("deployed_commit") or "")
        actual_image = str(deployment.get("image_digest") or "")
        actual_config = str(deployment.get("runtime_config_version") or "")
        if (
            actual == args.expected_commit
            and (not args.expected_image_digest or actual_image == args.expected_image_digest)
            and (not args.expected_config_version or actual_config == args.expected_config_version)
        ):
            break
        if attempt + 1 < max(1, args.attempts):
            time.sleep(max(1, min(args.interval_seconds, 60)))
    else:
        raise SystemExit(
            f"deployed provenance mismatch: expected_commit={args.expected_commit} actual_commit={actual or 'missing'} "
            f"expected_image={args.expected_image_digest or 'not-required'} actual_image={actual_image or 'missing'} "
            f"expected_config={args.expected_config_version or 'not-required'} actual_config={actual_config or 'missing'}"
        )
    print(json.dumps({
        "status": "pass",
        "deployed_commit": actual,
        "image_digest": actual_image or None,
        "environment": deployment.get("environment"),
        "runtime_config_version": deployment.get("runtime_config_version"),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
