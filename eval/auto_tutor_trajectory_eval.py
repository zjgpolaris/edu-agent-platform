"""AutoTutor 轨迹评测。

验证自主辅导 agent 的三个核心轨迹维度（参见 docs/202606291030-autotutor-autonomous-loop-dev.md 第四节）：

1. 规划合理性：生成的计划是否对准学生的薄弱点（换学生计划应不同）。
2. 反思触发正确性：该反思时是否反思（答错→reflect→真实 re-plan），
   不该反思时是否没乱改（答对→不 re-plan）。
3. 闭环命中：课程结束是否覆盖目标薄弱点，并正确写入 memory / 错题（接 SM-2 复习）。

设计为离线可跑：plan / 出题 / 反思在无 LLM 凭证时走确定性 fallback，
因此该 suite 在 CI 的 quick-eval 中也能稳定产出指标。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

DEFAULT_LOCAL_EMBED_MODEL_PATH = Path("/Users/cengjiguang/.cache/modelscope/BAAI/bge-large-zh-v1___5")
if not os.environ.get("EMBED_MODEL_PATH") and DEFAULT_LOCAL_EMBED_MODEL_PATH.exists():
    os.environ["EMBED_MODEL_PATH"] = str(DEFAULT_LOCAL_EMBED_MODEL_PATH)

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents import auto_tutor as at
from services.weakpoint_service import clear_weakpoints, get_weakpoints, record_weakpoint
from student_profile import list_memory_entries


def _seed(student_id: str, tags: list[str]) -> None:
    clear_weakpoints(student_id)
    for tag in tags:
        record_weakpoint(student_id, tag, source="trajectory_eval")
        record_weakpoint(student_id, tag, source="trajectory_eval")  # 错 2 次，触发 easy 起步


def _correct_letter(session_id: str) -> str:
    state = at._store.get(session_id)
    step = state.lesson_plan[state.current_step_index]
    return str((step.question or {}).get("answer", "A")).strip()[:1].upper()


def _wrong_letter(correct: str) -> str:
    for letter in "ABCD":
        if letter != correct:
            return letter
    return "B"


def _tag_covered(tag: str, plan: list[dict]) -> bool:
    return any(tag in (p.get("knowledge_point") or "") or (p.get("knowledge_point") or "") in tag or p.get("source_tag") == tag for p in plan)


# --------------------------------------------------------------------------- #
# cases
# --------------------------------------------------------------------------- #
def case_plan_targets_weakpoints() -> tuple[bool, str, dict]:
    """规划合理性：计划对准薄弱点，且不同学生计划不同。"""
    sid_a, sid_b = "traj-plan-a", "traj-plan-b"
    _seed(sid_a, ["鸦片战争", "戊戌变法"])
    _seed(sid_b, ["科举制", "安史之乱"])
    st_a = at.start_session(sid_a, grade="八年级上册", actor_role="student")
    st_b = at.start_session(sid_b, grade="七年级下册", actor_role="student")
    plan_a, plan_b = st_a["lesson_plan"], st_b["lesson_plan"]
    detail = {
        "plan_a": [p["knowledge_point"] for p in plan_a],
        "plan_b": [p["knowledge_point"] for p in plan_b],
    }
    if not plan_a:
        return False, "plan_a empty", detail
    covered = sum(1 for t in ["鸦片战争", "戊戌变法"] if _tag_covered(t, plan_a))
    if covered == 0:
        return False, "plan does not target seeded weakpoints", detail
    points_a = {p["knowledge_point"] for p in plan_a}
    points_b = {p["knowledge_point"] for p in plan_b}
    if points_a == points_b:
        return False, "plan identical across different students (hardcoded?)", detail
    return True, "ok", detail


def case_wrong_answer_triggers_replan() -> tuple[bool, str, dict]:
    """反思触发正确性（正例）：答错 → reflect → 真实 re-plan。"""
    sid = "traj-replan"
    _seed(sid, ["鸦片战争", "辛亥革命"])
    st = at.start_session(sid, grade="八年级上册", actor_role="student")
    sess = st["session_id"]
    before = [(p["knowledge_point"], p["difficulty"]) for p in st["lesson_plan"]]
    wrong = _wrong_letter(_correct_letter(sess))
    res = at.submit_answer(sess, wrong, actor_role="student")
    after = [(p["knowledge_point"], p["difficulty"], p["replanned"]) for p in res["lesson_plan"]]
    has_reflect_step = any(s["event_type"] == "reflect" for s in res["runtime_steps"])
    has_replan_step = any(s["event_type"] == "re_plan" for s in res["runtime_steps"])
    detail = {"before": before, "after": after, "replans": res["replans"], "reflection": bool(res.get("reflection"))}
    if res.get("last_answer_correct"):
        return False, "answer unexpectedly judged correct", detail
    if not res["reflect_log"]:
        return False, "no reflection recorded", detail
    if res["replans"] < 1:
        return False, "no re-plan happened", detail
    if not (has_reflect_step and has_replan_step):
        return False, "reflect/re_plan trace steps missing", detail
    if not any(p["replanned"] for p in res["lesson_plan"]):
        return False, "no step marked replanned", detail
    return True, "ok", detail


def case_correct_answer_no_spurious_replan() -> tuple[bool, str, dict]:
    """反思触发正确性（反例）：答对不该乱反思 / 乱改计划。"""
    sid = "traj-correct"
    _seed(sid, ["唐朝", "宋朝"])
    st = at.start_session(sid, grade="七年级下册", actor_role="student")
    sess = st["session_id"]
    res = at.submit_answer(sess, _correct_letter(sess), actor_role="student")
    detail = {"replans": res["replans"], "correct": res.get("last_answer_correct"), "reflect_log": res["reflect_log"]}
    if not res.get("last_answer_correct"):
        return False, "answer unexpectedly judged wrong", detail
    if res["replans"] != 0:
        return False, "spurious re-plan on correct answer", detail
    if res["reflect_log"]:
        return False, "spurious reflection on correct answer", detail
    return True, "ok", detail


def case_closure_writes_memory_and_review() -> tuple[bool, str, dict]:
    """闭环命中：课后写 memory + 错题进复习池 / 已掌握移出错题本。"""
    sid = "traj-closure"
    _seed(sid, ["分封制", "甲骨文"])
    st = at.start_session(sid, grade="七年级上册", actor_role="student")
    sess = st["session_id"]
    guard = 0
    while st["status"] != "completed" and guard < 30:
        guard += 1
        st = at.submit_answer(sess, _correct_letter(sess), actor_role="student")
    detail = {"status": st["status"], "summary": st.get("summary"), "guard": guard}
    if st["status"] != "completed":
        return False, "session did not finalize", detail
    if not any(s["event_type"] == "memory" and "Finalize" in s["step_name"] for s in st["runtime_steps"]):
        return False, "no finalize/memory trace step", detail
    mems = list_memory_entries(sid, memory_type="review_goal")
    if not any(m.source_feature == "auto_tutor" for m in mems):
        return False, "no auto_tutor review_goal memory written", detail
    # 全部答对 → 已掌握应从错题本移除
    remaining = {w["knowledge_tag"] for w in get_weakpoints(sid)}
    mastered = {p["source_tag"] or p["knowledge_point"] for p in st["lesson_plan"] if p["status"] == "mastered"}
    detail["remaining_weakpoints"] = list(remaining)
    if mastered & remaining:
        return False, f"mastered points still in weakpoints: {mastered & remaining}", detail
    return True, "ok", detail


CASES = [
    ("plan_targets_weakpoints", case_plan_targets_weakpoints),
    ("wrong_answer_triggers_replan", case_wrong_answer_triggers_replan),
    ("correct_answer_no_spurious_replan", case_correct_answer_no_spurious_replan),
    ("closure_writes_memory_and_review", case_closure_writes_memory_and_review),
]


def print_failed_case(name: str, reason: str, detail: dict) -> None:
    payload = {"name": name, "reason": reason, "category": "autotutor_trajectory", **detail}
    print("FAILED_CASE_DETAIL=" + json.dumps(payload, ensure_ascii=False, default=str))


def main() -> None:
    passed = 0
    failed: list[str] = []
    replan_cases = 0
    replan_triggered = 0
    for name, fn in CASES:
        try:
            ok, reason, detail = fn()
        except Exception as exc:  # noqa: BLE001
            ok, reason, detail = False, f"exception: {exc}", {}
        if name == "wrong_answer_triggers_replan":
            replan_cases += 1
            if ok:
                replan_triggered += 1
        if ok:
            passed += 1
            print(f"OK {name}")
        else:
            failed.append(name)
            print(f"FAIL {name} {reason}")
            print_failed_case(name, reason, detail)

    total = len(CASES)
    print(f"autotutor_trajectory={passed}/{total}")
    print(f"replan_trigger_rate={round(replan_triggered / replan_cases, 4) if replan_cases else 0.0}")
    if failed:
        print(f"failed cases: {', '.join(failed)}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
