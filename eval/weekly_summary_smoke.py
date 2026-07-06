from __future__ import annotations

import os
import sys
import tempfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["EDU_AGENT_DB_PATH"] = str(Path(tempfile.gettempdir()) / "edu-agent-weekly-summary-smoke.sqlite3")

import services.weekly_summary_service as wss
from services.weekly_summary_service import _rule_based_narrative, build_weekly_summary


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def _metrics(**over) -> dict:
    base = {
        "active_days": 5, "streak_days": 3,
        "reviews_done": 5, "reviews_total": 10, "review_completion_rate": 50,
        "homework_count": 2, "homework_avg_score": 82.0,
        "autotutor_sessions": 1,
        "weakpoint_count": 2, "top_weakpoints": [{"tag": "鸦片战争", "count": 3}],
    }
    base.update(over)
    return base


def rule_narrative_empty() -> None:
    summary, suggestions = _rule_based_narrative(_metrics(active_days=0, streak_days=0))
    assert "还没有学习记录" in summary, summary
    assert len(suggestions) >= 1


def rule_narrative_normal() -> None:
    summary, suggestions = _rule_based_narrative(_metrics())
    assert "5 天" in summary, summary
    assert "连续打卡 3 天" in summary, summary
    assert "复习完成率 50%" in summary, summary
    assert "作业平均分 82" in summary, summary
    assert 1 <= len(suggestions) <= 3


def rule_triggers_targeted_suggestions() -> None:
    # rate<60 → 复习建议；weak>0+tops → 错题建议；active<5 → 习惯建议
    _, suggestions = _rule_based_narrative(_metrics(active_days=3, review_completion_rate=40))
    joined = " ".join(suggestions)
    assert "完成率" in joined, joined
    assert "鸦片战争" in joined, joined
    assert "连续打卡" in joined, joined
    assert len(suggestions) <= 3  # 上限截断


def rule_no_weakpoints_fallback_suggestion() -> None:
    _, suggestions = _rule_based_narrative(
        _metrics(active_days=7, review_completion_rate=95, weakpoint_count=0, top_weakpoints=[])
    )
    assert any("挑战" in s for s in suggestions), suggestions


def build_assembles_and_degrades() -> None:
    # monkeypatch 掉 DB 聚合与 LLM，验证组装 + 降级路径
    fixed = _metrics()
    wss._collect_metrics = lambda sid, today: fixed
    wss._llm_narrative = lambda m: None
    result = build_weekly_summary("stu-weekly-x", today=date(2026, 7, 6))
    assert result["student_id"] == "stu-weekly-x"
    assert result["week_start"] == "2026-06-30", result["week_start"]
    assert result["week_end"] == "2026-07-06", result["week_end"]
    assert result["generated_by"] == "rule"
    assert result["metrics"] is fixed
    assert result["summary"]
    assert 1 <= len(result["suggestions"]) <= 3


def build_prefers_llm_when_available() -> None:
    wss._collect_metrics = lambda sid, today: _metrics()
    wss._llm_narrative = lambda m: ("本周表现很棒！", ["建议一", "建议二"])
    result = build_weekly_summary("stu-weekly-y", today=date(2026, 7, 6))
    assert result["generated_by"] == "llm"
    assert result["summary"] == "本周表现很棒！"
    assert result["suggestions"] == ["建议一", "建议二"]


def main() -> None:
    cases = [
        ("rule_narrative_empty", rule_narrative_empty),
        ("rule_narrative_normal", rule_narrative_normal),
        ("rule_triggers_targeted_suggestions", rule_triggers_targeted_suggestions),
        ("rule_no_weakpoints_fallback_suggestion", rule_no_weakpoints_fallback_suggestion),
        ("build_assembles_and_degrades", build_assembles_and_degrades),
        ("build_prefers_llm_when_available", build_prefers_llm_when_available),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"weekly_summary_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
