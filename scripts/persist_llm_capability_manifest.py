#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from llm.capability_store import save_capability_manifest
from llm.registry import get_default_registry


def main() -> None:
    parser = argparse.ArgumentParser(description="Persist a validated, content-minimized LLM capability manifest.")
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"invalid manifest: {exc}") from exc
    saved = save_capability_manifest(payload, get_default_registry())
    print(json.dumps({"status": "pass", "manifest_sha256": saved["manifest_sha256"], "source": "database"}, sort_keys=True))


if __name__ == "__main__":
    main()
