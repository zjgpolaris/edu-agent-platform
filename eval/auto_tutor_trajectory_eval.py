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


def _current_correct_letter(session_id: str) -> str:
    state = at._store.get(session_id)
    if state.phase == "exit_ticket" and state.exit_ticket:
        return str((state.exit_ticket.question or {}).get("answer", "A")).strip()[:1].upper()
    return _correct_letter(session_id)


def _answer_until_exit_ticket(session_id: str, state: dict, *, max_turns: int = 30) -> dict:
    guard = 0
    current = state
    while current.get("status") != "completed" and current.get("phase") != "exit_ticket" and guard < max_turns:
        guard += 1
        current = at.submit_answer(session_id, _current_correct_letter(session_id), actor_role="student")
    current["guard"] = guard
    return current


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
    wrong = _wrong_letter(_current_correct_letter(sess))
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
    res = at.submit_answer(sess, _current_correct_letter(sess), actor_role="student")
    detail = {"replans": res["replans"], "correct": res.get("last_answer_correct"), "reflect_log": res["reflect_log"]}
    if not res.get("last_answer_correct"):
        return False, "answer unexpectedly judged wrong", detail
    if res["replans"] != 0:
        return False, "spurious re-plan on correct answer", detail
    if res["reflect_log"]:
        return False, "spurious reflection on correct answer", detail
    return True, "ok", detail


def case_closure_writes_memory_and_review() -> tuple[bool, str, dict]:
    """闭环命中：课后写 memory + 掌握证据累积（掌握度模型：单次答对记 evidence，未必立即移除）。"""
    sid = "traj-closure"
    _seed(sid, ["分封制", "甲骨文"])
    st = at.start_session(sid, grade="七年级上册", actor_role="student")
    sess = st["session_id"]
    guard = 0
    while st["status"] != "completed" and guard < 30:
        guard += 1
        st = at.submit_answer(sess, _current_correct_letter(sess), actor_role="student")
    detail = {"status": st["status"], "summary": st.get("summary"), "guard": guard}
    if st["status"] != "completed":
        return False, "session did not finalize", detail
    if not any(s["event_type"] == "memory" and "Finalize" in s["step_name"] for s in st["runtime_steps"]):
        return False, "no finalize/memory trace step", detail
    mems = list_memory_entries(sid, memory_type="review_goal")
    if not any(m.source_feature == "auto_tutor" for m in mems):
        return False, "no auto_tutor review_goal memory written", detail
    # 掌握度模型：全部答对 → 掌握点应累积 correct_streak（>=1），或已达阈值被移除
    wps = {w["knowledge_tag"]: w.get("correct_streak", 0) for w in get_weakpoints(sid)}
    mastered = {p["source_tag"] or p["knowledge_point"] for p in st["lesson_plan"] if p["status"] == "mastered"}
    detail["remaining_weakpoints"] = wps
    detail["mastered"] = list(mastered)
    if not mastered:
        return False, "no step reached mastered status", detail
    for tag in mastered:
        # 已移除（达阈值）或仍在但连对计数>=1 都算证据生效
        if tag in wps and wps[tag] < 1:
            return False, f"mastered point '{tag}' did not accumulate correct evidence", detail
    return True, "ok", detail


def case_focus_tags_prioritized_in_plan() -> tuple[bool, str, dict]:
    """focus_tags（作业错题引导）应把指定知识点排到计划最前。

    回归护栏：此前 focus_tags 只重排 weakpoints 列表，LLM 规划按 wrong_count 排序会忽略它，
    导致 focus_tags 在 LLM 可用时失效。现已在 plan prompt 显式 pin。
    """
    sid = "traj-focus"
    _seed(sid, ["科举制", "安史之乱", "贞观之治"])
    focus = "安史之乱"
    st = at.start_session(sid, grade="七年级下册", actor_role="student", focus_tags=[focus])
    plan = st["lesson_plan"]
    detail = {"plan": [p["knowledge_point"] for p in plan], "focus": focus,
              "first_source_tag": plan[0].get("source_tag") if plan else None}
    if not plan:
        return False, "plan empty", detail
    first = plan[0]
    hit = (first.get("source_tag") == focus) or (focus in (first.get("knowledge_point") or ""))
    if not hit:
        return False, "focus tag not prioritized as first step", detail
    return True, "ok", detail


def case_repeated_wrong_downgrades_difficulty() -> tuple[bool, str, dict]:
    """连续答错应触发难度下调（reflect→re_plan 中 hard/medium 逐步降级）。"""
    sid = "traj-downgrade"
    _seed(sid, ["鸦片战争", "洋务运动"])
    st = at.start_session(sid, grade="八年级上册", actor_role="student")
    sess = st["session_id"]
    diffs: list[str] = []
    guard = 0
    st_cur = st
    # 对当前步连续答错两次，观察难度是否下调
    start_diff = st["lesson_plan"][st["current_step_index"]]["difficulty"]
    while guard < 3 and st_cur["status"] == "awaiting_answer":
        guard += 1
        idx = st_cur["current_step_index"]
        wrong = _wrong_letter(_current_correct_letter(sess))
        st_cur = at.submit_answer(sess, wrong, actor_role="student")
        cur_idx = min(idx, len(st_cur["lesson_plan"]) - 1)
        diffs.append(st_cur["lesson_plan"][cur_idx]["difficulty"])
    detail = {"start_difficulty": start_diff, "difficulties_after_wrong": diffs, "replans": st_cur["replans"]}
    if st_cur["replans"] < 1:
        return False, "no re-plan after wrong answers", detail
    order = {"easy": 0, "medium": 1, "hard": 2}
    # 至少出现一次难度不升（下调或维持在 easy），且计划确实被标记 replanned
    if not any(p["replanned"] for p in st_cur["lesson_plan"]):
        return False, "no step marked replanned", detail
    if start_diff != "easy" and diffs and order.get(diffs[0], 2) >= order.get(start_diff, 2):
        return False, f"difficulty not downgraded after wrong ({start_diff}->{diffs})", detail
    return True, "ok", detail


def case_empty_weakpoints_still_plans() -> tuple[bool, str, dict]:
    """错题本为空的新学生也应规划出合理（非空、有效难度）的计划。"""
    sid = "traj-empty"
    clear_weakpoints(sid)
    st = at.start_session(sid, grade="七年级上册", actor_role="student")
    plan = st["lesson_plan"]
    detail = {"plan": [p["knowledge_point"] for p in plan]}
    if not plan:
        return False, "empty weakpoints produced empty plan", detail
    if not all((p.get("knowledge_point") or "").strip() for p in plan):
        return False, "plan contains empty knowledge_point", detail
    if not all(p.get("difficulty") in {"easy", "medium", "hard"} for p in plan):
        return False, "plan contains invalid difficulty", detail
    return True, "ok", detail


def case_exit_ticket_runs_before_finalize() -> tuple[bool, str, dict]:
    """教学步骤结束后应先进入退出票，而不是直接 completed。"""
    sid = "traj-exit-before-finalize"
    _seed(sid, ["辛亥革命历史意义"])
    st = at.start_session(sid, grade="八年级上册", actor_role="student", focus_tags=["辛亥革命历史意义"])
    sess = st["session_id"]
    st = _answer_until_exit_ticket(sess, st)
    detail = {"status": st.get("status"), "phase": st.get("phase"), "current_question": st.get("current_question"), "guard": st.get("guard")}
    if st.get("status") != "awaiting_answer" or st.get("phase") != "exit_ticket":
        return False, "lesson ended without awaiting exit_ticket", detail
    if (st.get("current_question") or {}).get("kind") != "exit_ticket":
        return False, "current question is not marked as exit_ticket", detail
    return True, "ok", detail


def case_exit_ticket_answer_finalizes_session() -> tuple[bool, str, dict]:
    """退出票答完后才进入 completed，并返回退出票结果与证据摘要。"""
    sid = "traj-exit-finalize"
    _seed(sid, ["洋务运动目的"])
    st = at.start_session(sid, grade="八年级上册", actor_role="student", focus_tags=["洋务运动目的"])
    sess = st["session_id"]
    st = _answer_until_exit_ticket(sess, st)
    st = at.submit_answer(sess, _current_correct_letter(sess), actor_role="student")
    detail = {"status": st.get("status"), "phase": st.get("phase"), "exit_ticket_result": st.get("exit_ticket_result"), "evidence": st.get("evidence")}
    if st.get("status") != "completed" or st.get("phase") != "completed":
        return False, "exit ticket answer did not finalize session", detail
    if not st.get("exit_ticket_result"):
        return False, "missing exit_ticket_result", detail
    if not (st.get("evidence") or {}).get("exit_ticket_recorded"):
        return False, "missing evidence summary", detail
    return True, "ok", detail


def case_exit_ticket_result_written_to_learning_events() -> tuple[bool, str, dict]:
    """退出票结果应写入 learning_events，供 tutor effectiveness 聚合。"""
    from db.engine import get_connection
    from sqlalchemy import text

    sid = "traj-exit-event"
    _seed(sid, ["戊戌变法失败原因"])
    st = at.start_session(sid, grade="八年级上册", actor_role="student", focus_tags=["戊戌变法失败原因"])
    sess = st["session_id"]
    st = _answer_until_exit_ticket(sess, st)
    st = at.submit_answer(sess, _current_correct_letter(sess), actor_role="student")
    with get_connection() as conn:
        count = conn.execute(
            text("""SELECT COUNT(*) FROM learning_events
                 WHERE student_id=:sid AND session_id=:session_id
                   AND feature='auto_tutor' AND event_type='auto_tutor_exit_ticket'"""),
            {"sid": sid, "session_id": sess},
        ).scalar_one()
    detail = {"event_count": count, "status": st.get("status"), "result": st.get("exit_ticket_result")}
    if count < 1:
        return False, "auto_tutor_exit_ticket learning event missing", detail
    return True, "ok", detail


def case_exit_ticket_wrong_records_weakpoint() -> tuple[bool, str, dict]:
    """退出票答错后应回流/强化错题本。"""
    sid = "traj-exit-wrong"
    tag = "甲午中日战争"
    _seed(sid, [tag])
    before = {w["knowledge_tag"]: int(w.get("wrong_count") or 0) for w in get_weakpoints(sid)}
    st = at.start_session(sid, grade="八年级上册", actor_role="student", focus_tags=[tag])
    sess = st["session_id"]
    st = _answer_until_exit_ticket(sess, st)
    wrong = _wrong_letter(_current_correct_letter(sess))
    st = at.submit_answer(sess, wrong, actor_role="student")
    after = {w["knowledge_tag"]: int(w.get("wrong_count") or 0) for w in get_weakpoints(sid)}
    result = st.get("exit_ticket_result") or {}
    detail = {"before": before, "after": after, "result": result}
    if result.get("is_correct") is not False:
        return False, "exit ticket was not judged wrong", detail
    if after.get(tag, 0) <= before.get(tag, 0):
        return False, "wrong exit ticket did not strengthen weakpoint", detail
    return True, "ok", detail


CASES = [
    ("plan_targets_weakpoints", case_plan_targets_weakpoints),
    ("wrong_answer_triggers_replan", case_wrong_answer_triggers_replan),
    ("correct_answer_no_spurious_replan", case_correct_answer_no_spurious_replan),
    ("closure_writes_memory_and_review", case_closure_writes_memory_and_review),
    ("focus_tags_prioritized_in_plan", case_focus_tags_prioritized_in_plan),
    ("repeated_wrong_downgrades_difficulty", case_repeated_wrong_downgrades_difficulty),
    ("empty_weakpoints_still_plans", case_empty_weakpoints_still_plans),
    ("exit_ticket_runs_before_finalize", case_exit_ticket_runs_before_finalize),
    ("exit_ticket_answer_finalizes_session", case_exit_ticket_answer_finalizes_session),
    ("exit_ticket_result_written_to_learning_events", case_exit_ticket_result_written_to_learning_events),
    ("exit_ticket_wrong_records_weakpoint", case_exit_ticket_wrong_records_weakpoint),
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
