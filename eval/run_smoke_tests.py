"""Smoke runner — 自动发现 eval/ 下所有 *_smoke.py 文件，无需手动注册。

新增 smoke 测试文件后直接运行即可，无需修改本文件。
优先入口是 eval/run_core_evals.py（会生成 JSON/Markdown 报告）；
本文件用于快速本地验证。
"""
import subprocess
import sys
from pathlib import Path

EVAL_DIR = Path(__file__).parent

# 按文件名排序，确保运行顺序稳定
SMOKE_TESTS: list[Path] = sorted(EVAL_DIR.glob("*_smoke.py"))


def run_test(test_path: Path) -> tuple[bool, str]:
    """运行单个测试，返回 (成功, 输出)"""
    result = subprocess.run(
        [sys.executable, str(test_path)],
        capture_output=True,
        text=True,
        cwd=EVAL_DIR.parent,
    )
    return result.returncode == 0, result.stdout + result.stderr


def main() -> int:
    print(f"Auto-discovered {len(SMOKE_TESTS)} smoke tests in {EVAL_DIR}\n")

    passed = 0
    failed = 0
    results: list[tuple[str, bool, str]] = []

    for test_path in SMOKE_TESTS:
        name = test_path.name
        print(f"Running {name}...")
        success, output = run_test(test_path)

        if success:
            print(f"✅ {name} passed")
            passed += 1
            results.append((name, True, ""))
        else:
            print(f"❌ {name} failed")
            failed += 1
            results.append((name, False, output))
            if output:
                print(f"   Error: {output[:200]}")
        print()

    total = passed + failed
    print("=" * 50)
    print(f"Smoke tests summary: {passed}/{total} passed")
    if failed:
        print("\nFailed tests:")
        for name, success, output in results:
            if not success:
                print(f"  - {name}")
                if output:
                    print(f"    {output[:300]}")
        return 1
    print("✅ All smoke tests passed!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
