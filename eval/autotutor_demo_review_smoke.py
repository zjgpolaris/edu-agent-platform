"""Review-pack failure contracts; no models, servers, or real browser required."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_autotutor_demo_review as review


def main():
    revision = {"commit_sha": "a" * 40, "short_sha": "a" * 12, "dirty": False, "source_sha256": "b" * 64}
    data = {"ok": True, "source_revision": {k: revision[k] for k in ("commit_sha", "short_sha", "dirty")},
            "suites": [{"name": name, "status": "passed", "passed_cases": 1, "failed_cases_count": 0, "skipped_cases_count": 0, "total_cases": 1} for name in review.SUITES]}
    assert review.parse_eval(json.dumps(data), revision)["status"] == "pass"
    for change in ({"skipped_cases_count": 1, "passed_cases": 0, "status": "skipped"}, {"failed_cases_count": 1, "passed_cases": 0, "status": "failed"}):
        broken = copy.deepcopy(data)
        broken["suites"][0].update(change)
        assert review.parse_eval(json.dumps(broken), revision)["status"] == "fail"
    for raw in ("", "{}", "not json", json.dumps({**data, "suites": []})):
        try:
            review.parse_eval(raw, revision)
        except (ValueError, KeyError):
            pass
        else:
            raise AssertionError("missing/malformed report accepted")
    print("OK review_eval_missing_skipped_failure")
    browser = {"stats": {"expected": 5, "unexpected": 0, "flaky": 0, "skipped": 0}, "errors": [], "secret": "Bearer private"}
    safe = review.parse_browser(json.dumps(browser))
    assert safe["status"] == "pass" and "private" not in str(safe)
    for field in ("unexpected", "flaky", "skipped"):
        broken = copy.deepcopy(browser)
        broken["stats"][field] = 1
        assert review.parse_browser(json.dumps(broken))["status"] == "fail"
    print("OK review_browser_counts_and_redaction")
    env = {"PATH": os.environ.get("PATH", "")}
    for command, timeout, reason in ((["/missing-v151-python"], 2, "dependency_missing"),
            ([sys.executable, "-c", "raise SystemExit(3)"], 2, "child_failed"),
            ([sys.executable, "-c", "import time; time.sleep(10)"], 0.05, "timeout")):
        result, _ = review.run_process(command, env=env, timeout=timeout)
        assert result["status"] == "fail" and result["reason"] == reason
    result, _ = review.run_process([sys.executable, "-c", "print('ok')"], env=env, timeout=5)
    assert result["status"] == "pass"
    print("OK review_process_success_failure_timeout_missing_dependency")
    steps = {k: {"status": "pass"} for k in review.STEPS}
    assert review.overall(steps, True) == "pass" and review.overall(steps, False) == "fail"
    assert review.overall({**steps, "graph": {"status": "not_run"}}, True) == "partial"
    assert review.overall({**steps, "graph": {"status": "skipped"}}, True) == "partial"
    with tempfile.TemporaryDirectory() as name:
        root = Path(name)
        marker = root / "orphan-survived"
        child_code = f"import time; from pathlib import Path; time.sleep(0.5); Path({str(marker)!r}).write_text('unexpected')"
        command = [sys.executable, "-c", f"import subprocess,sys,time; subprocess.Popen([sys.executable, '-c', {child_code!r}]); time.sleep(10)"]
        result, _ = review.run_process(command, env=env, timeout=0.15)
        time.sleep(0.6)
        assert result["reason"] == "timeout" and not marker.exists(), "timed out child group survived"
        # A source edit while already dirty must still change the content fingerprint.
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / "tracked.py").write_text("before")
        subprocess.run(["git", "-C", str(root), "add", "tracked.py"], check=True)
        with patch.object(review, "ROOT", root):
            first = review.source_snapshot()
            (root / "tracked.py").write_text("after")
            assert review.source_snapshot()["source_sha256"] != first["source_sha256"]
        generated = root / "next-env.d.ts"
        before = b'import "./.next/dev/types/routes.d.ts";\n'
        generated.write_bytes(b'import "./.next-e2e/dev/types/routes.d.ts";\n')
        assert review.restore_generated_next_env(generated, before, "legacy") and generated.read_bytes() == before
        generated.write_bytes(b'// concurrent user edit\n')
        assert not review.restore_generated_next_env(generated, before, "legacy") and generated.read_bytes() == b'// concurrent user edit\n'
        # Real CLI dependency preflight failure still leaves a readable pack.
        target = root / "failure-pack"
        with patch.object(review, "source_snapshot", return_value=revision), patch.object(review, "run_process", return_value=({"status": "fail"}, "")), patch.dict(os.environ, {"DATABASE_URL": "", "DIRECT_URL": ""}):
            assert review.main(["--output", str(target), "--backend-only"]) == 1
        manifest = json.loads((target / "manifest.json").read_text())
        assert manifest["status"] == "fail" and (target / "summary.md").is_file()
        try:
            review.main(["--output", str(target)])
        except SystemExit as exc:
            assert exc.code == 2
        else:
            raise AssertionError("existing directory overwritten")
        # Collection never admits a stale commit, even when an imported pack says PASS.
        output = root / "collected"
        output.mkdir()
        (output / "cases").mkdir()
        receiver = {"source_before": {**revision, "commit_sha": "c" * 40}, "ci_run": manifest["ci_run"], "steps": steps}
        try:
            review.collect([target], output, receiver)
        except ValueError:
            pass
        else:
            raise AssertionError("stale collection accepted")
    print("OK review_source_change_partial_existing_output_collection")


if __name__ == "__main__":
    main()
