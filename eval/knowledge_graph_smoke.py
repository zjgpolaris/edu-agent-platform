"""知识图谱前置依赖服务 smoke。

覆盖：
- 无前置的根节点默认 available；
- 前置未掌握则下游 locked，并给出 locked_by；
- 前置掌握后下游转为 available；
- 错题在身的知识点标记 weak；
- next_recommended 优先 weak，其次 available；
- 依赖图无环（DAG 自检）；
- 图外的孤立错题知识点也纳入且不报错。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from services.knowledge_graph_service import build_graph, predict_risks, _has_cycle


def run_case(name: str, fn) -> bool:
    try:
        fn()
        print(f"OK {name}")
        return True
    except Exception as exc:
        print(f"FAIL {name}: {exc}")
        return False


def _status_of(graph: dict, tag: str) -> str:
    return next(n["status"] for n in graph["nodes"] if n["tag"] == tag)


def root_node_available_by_default() -> None:
    g = build_graph()
    assert _status_of(g, "鸦片战争") == "available", g["nodes"][0]


def downstream_locked_when_prereq_unmet() -> None:
    g = build_graph()
    # 洋务运动依赖 第二次鸦片战争 ← 鸦片战争，均未掌握
    assert _status_of(g, "洋务运动") == "locked"
    node = next(n for n in g["nodes"] if n["tag"] == "洋务运动")
    assert node["locked_by"] == ["第二次鸦片战争"], node["locked_by"]


def prereq_mastered_unlocks_downstream() -> None:
    # 掌握 鸦片战争 → 第二次鸦片战争 应从 locked 变 available
    g = build_graph(strong_topics=["鸦片战争"])
    assert _status_of(g, "第二次鸦片战争") == "available"
    # 但洋务运动仍锁（第二次鸦片战争还没掌握）
    assert _status_of(g, "洋务运动") == "locked"


def wrong_answer_marks_weak() -> None:
    g = build_graph(weakpoint_tags=["鸦片战争"])
    assert _status_of(g, "鸦片战争") == "weak"


def next_recommended_prefers_weak() -> None:
    g = build_graph(strong_topics=["鸦片战争"], weakpoint_tags=["第二次鸦片战争"])
    # 第二次鸦片战争有错题 → weak，应作为下一步
    assert g["next_recommended"] == "第二次鸦片战争", g["next_recommended"]


def next_recommended_falls_back_to_available() -> None:
    g = build_graph()
    # 无错题、无掌握时，第一个可学的根节点即下一步
    assert g["next_recommended"] == "鸦片战争", g["next_recommended"]


def graph_is_acyclic() -> None:
    assert _has_cycle() is False


def isolated_offgraph_tag_included() -> None:
    g = build_graph(weakpoint_tags=["某个图外知识点"])
    tags = {n["tag"] for n in g["nodes"]}
    assert "某个图外知识点" in tags
    assert _status_of(g, "某个图外知识点") == "weak"


def counts_sum_matches_nodes() -> None:
    g = build_graph(strong_topics=["鸦片战争"], weakpoint_tags=["洋务运动"])
    assert sum(g["counts"].values()) == len(g["nodes"]), g["counts"]


def no_risk_when_no_weak() -> None:
    # 没有任何 weak 时不应产生风险预警
    g = build_graph()
    assert predict_risks(g) == []


def downstream_flagged_at_risk() -> None:
    # 鸦片战争 weak → 其下游（第二次鸦片战争等）尚未出错但应被预警
    g = build_graph(weakpoint_tags=["鸦片战争"])
    risks = predict_risks(g)
    risk_tags = {r["tag"] for r in risks}
    assert "第二次鸦片战争" in risk_tags, risk_tags
    # 洋务运动更靠下游，也应命中
    assert "洋务运动" in risk_tags, risk_tags


def weak_node_not_in_risk() -> None:
    # 已经是 weak 的节点（已在错题本）不重复计入 at_risk
    g = build_graph(weakpoint_tags=["鸦片战争"])
    risks = predict_risks(g)
    assert all(r["tag"] != "鸦片战争" for r in risks)


def risk_score_reflects_weak_prereq_count() -> None:
    # 两个前置链上的 weak 越多，分越高；戊戌变法在 甲午→洋务→...→鸦片 之下
    g = build_graph(weakpoint_tags=["鸦片战争", "甲午中日战争"])
    risks = predict_risks(g)
    by_tag = {r["tag"]: r for r in risks}
    # 戊戌变法上游同时有鸦片战争与甲午中日战争两个 weak
    assert by_tag["戊戌变法"]["score"] == 2, by_tag.get("戊戌变法")
    # 结果按分降序
    scores = [r["score"] for r in risks]
    assert scores == sorted(scores, reverse=True), scores


def main() -> None:
    cases = [
        ("root_node_available_by_default", root_node_available_by_default),
        ("downstream_locked_when_prereq_unmet", downstream_locked_when_prereq_unmet),
        ("prereq_mastered_unlocks_downstream", prereq_mastered_unlocks_downstream),
        ("wrong_answer_marks_weak", wrong_answer_marks_weak),
        ("next_recommended_prefers_weak", next_recommended_prefers_weak),
        ("next_recommended_falls_back_to_available", next_recommended_falls_back_to_available),
        ("graph_is_acyclic", graph_is_acyclic),
        ("isolated_offgraph_tag_included", isolated_offgraph_tag_included),
        ("counts_sum_matches_nodes", counts_sum_matches_nodes),
        ("no_risk_when_no_weak", no_risk_when_no_weak),
        ("downstream_flagged_at_risk", downstream_flagged_at_risk),
        ("weak_node_not_in_risk", weak_node_not_in_risk),
        ("risk_score_reflects_weak_prereq_count", risk_score_reflects_weak_prereq_count),
    ]
    passed = sum(1 for name, fn in cases if run_case(name, fn))
    print(f"knowledge_graph_smoke={passed}/{len(cases)}")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
