"""Keep AutoTutor database work away from the API event loop."""
from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _threadpool_targets(path: Path, function_name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    function = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == function_name
    )
    targets: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Await) or not isinstance(node.value, ast.Call):
            continue
        call = node.value
        if not isinstance(call.func, ast.Name) or call.func.id != "run_in_threadpool" or not call.args:
            continue
        target = call.args[0]
        if isinstance(target, ast.Name):
            targets.add(target.id)
    return targets


def main() -> None:
    learning = ROOT / "backend" / "api" / "routers" / "learning.py"
    runtime = ROOT / "backend" / "api" / "routers" / "agent_runtime.py"

    start_targets = _threadpool_targets(learning, "autotutor_start_session")
    assert {
        "check_rate_limit",
        "resolve_autotutor_verification_traffic",
        "record_audit_event",
        "autotutor_start",
    }.issubset(start_targets), start_targets

    answer_targets = _threadpool_targets(learning, "autotutor_submit_answer")
    assert {
        "autotutor_get",
        "resolve_autotutor_verification_traffic",
        "record_audit_event",
        "autotutor_answer",
    }.issubset(answer_targets), answer_targets

    verification_targets = _threadpool_targets(runtime, "get_autotutor_canary_verification")
    assert {
        "build_autotutor_canary_verification",
        "_audit_autotutor_verification",
    }.issubset(verification_targets), verification_targets

    snapshot_targets = _threadpool_targets(runtime, "create_autotutor_canary_snapshot")
    assert {
        "build_autotutor_canary_snapshot",
        "_audit_autotutor_verification",
    }.issubset(snapshot_targets), snapshot_targets

    print("autotutor_async_db_boundaries_smoke=PASS")


if __name__ == "__main__":
    main()
