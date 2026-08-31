from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from llm.capability_probe import run_live_probe  # noqa: E402
from llm.capability_manifest import build_capability_manifest  # noqa: E402
from llm.registry import get_default_registry  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", action="append", dest="profiles")
    parser.add_argument("--output")
    parser.add_argument("--manifest-output", default=os.getenv("EDU_AGENT_LLM_MANIFEST_OUTPUT"))
    parser.add_argument("--expires-hours", type=int, default=168)
    args = parser.parse_args()

    if os.getenv("EDU_AGENT_REAL_LLM", "").strip().lower() not in {"1", "true", "yes", "on"}:
        print("SKIP llm_provider_live_probe: set EDU_AGENT_REAL_LLM=1")
        return
    if not os.getenv("BAILIAN_API_KEY"):
        print("SKIP llm_provider_live_probe: BAILIAN_API_KEY not configured")
        return

    report = run_live_probe(args.profiles)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    if args.manifest_output:
        manifest = build_capability_manifest(
            report,
            get_default_registry(),
            expires_hours=max(1, args.expires_hours),
        )
        manifest_path = Path(args.manifest_output)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(rendered)
    if report["result"] != "pass":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
