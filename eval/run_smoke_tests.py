"""Legacy/simple smoke runner.

Preferred entry point: eval/run_core_evals.py, which records suite metadata and writes
JSON/Markdown reports. This file is kept for quick direct script compatibility.
"""
import subprocess
import sys
from pathlib import Path

# Smoke tests to run (lightweight, no external dependencies)
SMOKE_TESTS = [
    "material_rag_smoke.py",
    "material_rag_isolation_smoke.py",
    "tool_registry_smoke.py",
    "learning_assistant_smoke.py",
    "guardrails_smoke.py",
    "weakpoints_smoke.py",
    "student_profile_smoke.py",
    "homework_grading_smoke.py",
    "learning_closure_smoke.py",
    "teacher_features_smoke.py",
    "variant_question_smoke.py",
    "lecture_review_smoke.py",
    "mastery_heatmap_smoke.py",
    "difficulty_smoke.py",
    "calendar_smoke.py",
]


def run_test(test_file: str) -> tuple[bool, str]:
    """运行单个测试，返回 (成功, 输出)"""
    result = subprocess.run(
        [sys.executable, str(test_file)],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent,
    )
    return result.returncode == 0, result.stdout + result.stderr


def main():
    """Run the legacy simple smoke list without report generation."""
    eval_dir = Path(__file__).parent
    print(f"Running smoke tests from {eval_dir}...\n")

    passed = 0
    failed = 0
    results = []

    for test_file in SMOKE_TESTS:
        test_path = eval_dir / test_file
        if not test_path.exists():
            print(f"⚠️  {test_file} not found, skipping")
            continue

        print(f"Running {test_file}...")
        success, output = run_test(test_path)

        if success:
            print(f"✅ {test_file} passed")
            passed += 1
            results.append((test_file, True, ""))
        else:
            print(f"❌ {test_file} failed")
            failed += 1
            results.append((test_file, False, output))
            # Print error output
            if output:
                print(f"   Error: {output[:200]}")
        print()

    # Summary
    total = passed + failed
    print("=" * 50)
    print(f"Smoke tests summary: {passed}/{total} passed")
    if failed > 0:
        print(f"\nFailed tests:")
        for test_file, success, output in results:
            if not success:
                print(f"  - {test_file}")
                if output:
                    print(f"    {output}")
        return 1
    else:
        print("✅ All smoke tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
