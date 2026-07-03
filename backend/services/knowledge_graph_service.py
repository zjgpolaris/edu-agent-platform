"""知识图谱前置依赖服务。

现有的 learning-path 只是错题的扁平清单，学生看不到"知识点之间的先后依赖"——
比如没弄懂"鸦片战争"就直接学"洋务运动"是学不透的。本服务补上这层结构：

- 用一张静态的学科前置依赖图（KNOWLEDGE_GRAPH）描述知识点先后关系；
- 结合学生 profile（strong/weak topics）与 weakpoints（错题）推导每个节点的状态：
    mastered   已掌握（strong_topics 命中，或错题已连对达标移出）
    weak       有错题在身，需强化
    available  前置已全部掌握，可以开始学
    locked     还有前置未掌握，暂时锁住
- 拓扑判断给出 next_recommended：优先未掌握的 weak，其次前置已通的 available。

纯静态 + 纯计算，无 LLM 调用，确定性强，便于 smoke 覆盖。图之外出现的知识点
（学生错题里有但图里没定义的）作为"孤立节点"照样纳入，状态按错题推导，不丢数据。
"""
from __future__ import annotations

from typing import Any

# ── 学科前置依赖图 ──────────────────────────────────────────────
# key 是知识点，value 是它的直接前置（必须先掌握这些才谈得上学 key）。
# 以中国近代史主线为主干，后续可扩到更多单元。边保持有向无环（DAG）。
KNOWLEDGE_GRAPH: dict[str, dict[str, Any]] = {
    "鸦片战争": {"prereqs": [], "grade": "8", "label": "鸦片战争"},
    "第二次鸦片战争": {"prereqs": ["鸦片战争"], "grade": "8", "label": "第二次鸦片战争"},
    "太平天国运动": {"prereqs": ["鸦片战争"], "grade": "8", "label": "太平天国运动"},
    "洋务运动": {"prereqs": ["第二次鸦片战争"], "grade": "8", "label": "洋务运动"},
    "甲午中日战争": {"prereqs": ["洋务运动"], "grade": "8", "label": "甲午中日战争"},
    "戊戌变法": {"prereqs": ["甲午中日战争"], "grade": "8", "label": "戊戌变法"},
    "义和团运动": {"prereqs": ["甲午中日战争"], "grade": "8", "label": "义和团运动"},
    "辛亥革命": {"prereqs": ["戊戌变法"], "grade": "8", "label": "辛亥革命"},
    "新文化运动": {"prereqs": ["辛亥革命"], "grade": "8", "label": "新文化运动"},
    "五四运动": {"prereqs": ["新文化运动"], "grade": "8", "label": "五四运动"},
}

# 状态优先级（数值越小越"卡住学生"，next_recommended 时优先处理）
_STATUS_PRIORITY = {"weak": 0, "available": 1, "locked": 2, "mastered": 3}


def _normalize_tags(tags: Any) -> set[str]:
    if not tags:
        return set()
    return {str(t).strip() for t in tags if str(t).strip()}


def build_graph(
    *,
    strong_topics: list[str] | None = None,
    weak_topics: list[str] | None = None,
    weakpoint_tags: list[str] | None = None,
) -> dict[str, Any]:
    """根据学生已知信息推导知识图谱各节点状态。

    参数
    ----
    strong_topics: profile.strong_topics —— 视为已掌握。
    weak_topics: profile.weak_topics —— 若无错题在身也标记为需关注。
    weakpoint_tags: 当前错题本里的知识点 —— 有错题即 weak。

    返回
    ----
    {
      "nodes": [{"tag","label","grade","status","prereqs","locked_by"}...],
      "edges": [{"from","to"}...],
      "next_recommended": tag | None,
      "counts": {"mastered":n,"weak":n,"available":n,"locked":n},
    }
    """
    strong = _normalize_tags(strong_topics)
    weak_profile = _normalize_tags(weak_topics)
    wrong = _normalize_tags(weakpoint_tags)

    # 图里的节点 + 学生数据里出现但图外的孤立节点，一起纳入
    all_tags: list[str] = list(KNOWLEDGE_GRAPH.keys())
    for extra in sorted((weak_profile | wrong | strong) - set(KNOWLEDGE_GRAPH)):
        all_tags.append(extra)

    # 掌握集合：strong 明确掌握 + 没有错题也不在 weak 名单里的"默认无需学"不算掌握，
    # 只有 strong 才算真正 mastered，避免把没学过的当成学会了。
    mastered = set(strong)

    def prereqs_of(tag: str) -> list[str]:
        return list(KNOWLEDGE_GRAPH.get(tag, {}).get("prereqs", []))

    nodes: list[dict[str, Any]] = []
    for tag in all_tags:
        prereqs = prereqs_of(tag)
        unmet = [p for p in prereqs if p not in mastered]

        if tag in mastered:
            status = "mastered"
        elif tag in wrong or tag in weak_profile:
            status = "weak"
        elif unmet:
            status = "locked"
        else:
            status = "available"

        nodes.append(
            {
                "tag": tag,
                "label": KNOWLEDGE_GRAPH.get(tag, {}).get("label", tag),
                "grade": KNOWLEDGE_GRAPH.get(tag, {}).get("grade"),
                "status": status,
                "prereqs": prereqs,
                # 锁定时告诉学生"卡在哪个前置上"，便于引导
                "locked_by": unmet if status == "locked" else [],
            }
        )

    edges = [
        {"from": prereq, "to": tag}
        for tag, meta in KNOWLEDGE_GRAPH.items()
        for prereq in meta.get("prereqs", [])
    ]

    # next_recommended：先 weak 后 available，同状态按图的定义顺序稳定取第一个
    ordered = sorted(
        nodes,
        key=lambda n: (_STATUS_PRIORITY[n["status"]], all_tags.index(n["tag"])),
    )
    next_recommended = next(
        (n["tag"] for n in ordered if n["status"] in ("weak", "available")),
        None,
    )

    counts = {s: sum(1 for n in nodes if n["status"] == s) for s in _STATUS_PRIORITY}

    return {
        "nodes": nodes,
        "edges": edges,
        "next_recommended": next_recommended,
        "counts": counts,
    }


def _has_cycle() -> bool:
    """自检：前置依赖图必须无环，否则拓扑推导会出错。"""
    color: dict[str, int] = {}  # 0=white 1=gray 2=black

    def dfs(tag: str) -> bool:
        color[tag] = 1
        for prereq in KNOWLEDGE_GRAPH.get(tag, {}).get("prereqs", []):
            c = color.get(prereq, 0)
            if c == 1:
                return True
            if c == 0 and dfs(prereq):
                return True
        color[tag] = 2
        return False

    return any(color.get(tag, 0) == 0 and dfs(tag) for tag in KNOWLEDGE_GRAPH)
