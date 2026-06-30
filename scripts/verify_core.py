#!/usr/bin/env python3
"""CI 入口：后端语法检查 + 核心 smoke/eval 转发。

GitHub Actions 使用本脚本作为稳定入口，避免 workflow 直接绑定多条命令。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_FILES = [
    ROOT / "backend" / "api" / "main.py",
    ROOT / "backend" / "rag" / "knowledge_base.py",
    ROOT / "eval" / "run_core_evals.py",
]


def run(command: list[str]) -> None:
    print("$ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify backend syntax and eval suites.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--smoke", action="store_true", help="Run smoke suites after syntax checks.")
    group.add_argument("--quick", action="store_true", help="Run quick suites after syntax checks.")
    parser.add_argument("--no-report", action="store_true", help="Forward --no-report to eval runner.")
    args = parser.parse_args()

    run([sys.executable, "-m", "py_compile", *[str(path.relative_to(ROOT)) for path in PY_FILES]])

    eval_cmd = [sys.executable, "eval/run_core_evals.py"]
    if args.quick:
        eval_cmd.append("--quick")
    else:
        eval_cmd.append("--smoke")
    if args.no_report:
        eval_cmd.append("--no-report")
    run(eval_cmd)


if __name__ == "__main__":
    main()
