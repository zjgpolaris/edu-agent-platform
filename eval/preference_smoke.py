#!/usr/bin/env python3
"""
学习偏好配置 smoke test
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_DB = Path(tempfile.gettempdir()) / "edu-agent-preference-smoke.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite:///{_DB}"
try:
    _DB.unlink()
except FileNotFoundError:
    pass

sys.path.insert(0, str(ROOT / "backend"))

from services.learning_preference_service import (
    get_preferences,
    set_preferences,
    build_preference_prompt,
    get_preference_schema,
    PREFERENCE_DIMS,
)


def run_case(name: str, fn):
    print(f"  ⏳ {name}...", end=" ", flush=True)
    try:
        fn()
        print("✅")
    except AssertionError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        import traceback
        print(f"❌ unexpected: {e}")
        traceback.print_exc()
        sys.exit(1)


def test_get_default_preferences():
    """C1: 获取默认偏好 — 未设置时返回所有默认值"""
    prefs = get_preferences("pref_c1")
    assert prefs["pace"] == "normal", f"默认pace应为normal，实际{prefs['pace']}"
    assert prefs["style"] == "example", f"默认style应为example，实际{prefs['style']}"
    assert prefs["interaction"] == "medium"
    assert prefs["difficulty"] == "match"


def test_set_and_get_preferences():
    """C2: 保存并读取偏好 — 部分更新"""
    result = set_preferences("pref_c2", {"pace": "fast", "style": "logic"})
    assert result["pace"] == "fast"
    assert result["style"] == "logic"
    assert result["interaction"] == "medium"  # 未修改的保持默认

    prefs = get_preferences("pref_c2")
    assert prefs["pace"] == "fast"
    assert prefs["style"] == "logic"


def test_invalid_preference_values():
    """C3: 传入无效的偏好值 — 应被忽略，保留有效值"""
    result = set_preferences("pref_c3", {
        "pace": "invalid_value",  # 无效值，应被忽略
        "style": "story",          # 有效值
        "unknown_key": "foo",      # 未知 key，应被忽略
    })
    assert result["pace"] == "normal"  # 无效值被忽略，保持默认
    assert result["style"] == "story"  # 有效值生效
    assert "unknown_key" not in result


def test_build_preference_prompt_default():
    """C4: 全部默认值时 prompt 为空"""
    set_preferences("pref_c4", {})  # 全部默认
    prompt = build_preference_prompt("pref_c4")
    assert prompt == "", f"全默认值应返回空字符串，实际: {prompt}"


def test_build_preference_prompt_custom():
    """C5: 自定义偏好时生成 prompt 片段"""
    set_preferences("pref_c5", {"pace": "fast", "interaction": "high"})
    prompt = build_preference_prompt("pref_c5")
    assert "【学生偏好设置】" in prompt, f"应包含偏好设置标题，实际: {prompt}"
    assert "简洁" in prompt or "80字" in prompt, "快速模式应提到简洁或字数限制"
    assert "追问" in prompt or "提问" in prompt, "高互动应提到追问"


def test_get_preference_schema():
    """C6: 获取偏好维度定义"""
    schema = get_preference_schema()
    assert "pace" in schema
    assert "style" in schema
    assert "interaction" in schema
    assert "difficulty" in schema
    assert schema["pace"]["label"] == "学习速度"
    assert "fast" in schema["pace"]["options"]
    assert schema["pace"]["default"] == "normal"


def main():
    print("preference_smoke.py — 学习偏好配置 smoke test")
    run_case("C1: 获取默认偏好配置", test_get_default_preferences)
    run_case("C2: 保存并读取偏好", test_set_and_get_preferences)
    run_case("C3: 无效值被过滤", test_invalid_preference_values)
    run_case("C4: 全默认值时 prompt 为空", test_build_preference_prompt_default)
    run_case("C5: 自定义偏好生成 prompt", test_build_preference_prompt_custom)
    run_case("C6: 获取偏好维度定义", test_get_preference_schema)
    print("✅ 6/6 all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
