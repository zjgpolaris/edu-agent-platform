from __future__ import annotations

import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from agents.learning_assistant_rollout import build_rollout_decision
from agents.learning_assistant_planner import build_task_plan
from agents.learning_assistant_router import IntentName, RoutedTask, RoutingDecision


ROLLOUT_KEYS = {
    "EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED",
    "EDU_AGENT_ASSISTANT_PLANNER_ENABLED",
    "EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE",
    "EDU_AGENT_ASSISTANT_ROLLOUT_KILL_SWITCH",
    "EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS",
    "EDU_AGENT_ASSISTANT_PLANNER_PERCENT_BPS",
    "EDU_AGENT_ASSISTANT_ROLLOUT_SALT",
    "EDU_AGENT_ASSISTANT_ROLLOUT_CONFIG_VERSION",
}


@contextmanager
def rollout_env(**values: str):
    previous = {key: os.environ.get(key) for key in ROLLOUT_KEYS}
    for key in ROLLOUT_KEYS:
        os.environ.pop(key, None)
    os.environ.update(values)
    try:
        yield
    finally:
        for key in ROLLOUT_KEYS:
            os.environ.pop(key, None)
        for key, value in previous.items():
            if value is not None:
                os.environ[key] = value


def main() -> None:
    request = {"student_id": "stable-student", "session_id": "session-a", "trace_id": "trace-a"}

    with rollout_env(
        EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED="1",
        EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE="0",
        EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS="10000",
        EDU_AGENT_ASSISTANT_ROLLOUT_SALT="stable-v1",
    ):
        first = build_rollout_decision(request, high_risk=False, composition_candidate=False)
        second = build_rollout_decision(request, high_risk=False, composition_candidate=False)
        probe = (
            "from agents.learning_assistant_rollout import build_rollout_decision; "
            "print(build_rollout_decision({'student_id':'stable-student'}, high_risk=False, composition_candidate=False).bucket)"
        )
        child_env = os.environ.copy()
        child_env["PYTHONPATH"] = str(BACKEND)
        child_bucket = int(subprocess.run(
            [sys.executable, "-c", probe],
            cwd=ROOT,
            env=child_env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip())
        assert first.bucket == second.bucket
        assert first.bucket == child_bucket
        assert first.subject_hash == second.subject_hash
        assert first.route_mode == "semantic_active"

    with rollout_env(
        EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED="1",
        EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE="0",
        EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS="0",
    ):
        assert build_rollout_decision(request, high_risk=False, composition_candidate=False).route_mode == "control"

    with rollout_env(
        EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED="1",
        EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE="1",
        EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS="10000",
    ):
        assert build_rollout_decision(request, high_risk=False, composition_candidate=False).route_mode == "shadow"

    with rollout_env(
        EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED="1",
        EDU_AGENT_ASSISTANT_PLANNER_ENABLED="1",
        EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE="0",
        EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS="10000",
        EDU_AGENT_ASSISTANT_PLANNER_PERCENT_BPS="10000",
        EDU_AGENT_ASSISTANT_ROLLOUT_KILL_SWITCH="1",
    ):
        killed = build_rollout_decision(request, high_risk=False, composition_candidate=True)
        assert killed.route_mode == "control"
        assert killed.planner_mode == "control"
        assert killed.reason_code == "kill_switch"

    with rollout_env(
        EDU_AGENT_ASSISTANT_SEMANTIC_ROUTER_ENABLED="1",
        EDU_AGENT_ASSISTANT_PLANNER_ENABLED="1",
        EDU_AGENT_ASSISTANT_ROUTER_SHADOW_MODE="0",
        EDU_AGENT_ASSISTANT_SEMANTIC_PERCENT_BPS="10000",
        EDU_AGENT_ASSISTANT_PLANNER_PERCENT_BPS="10000",
    ):
        guarded = build_rollout_decision(request, high_risk=True, composition_candidate=True)
        assert guarded.route_mode == "control"
        assert guarded.planner_mode == "control"
        assert guarded.reason_code == "high_risk_rule_only"

    with rollout_env(
        EDU_AGENT_ASSISTANT_PLANNER_ENABLED="1",
        EDU_AGENT_ASSISTANT_PLANNER_PERCENT_BPS="10000",
    ):
        planner_only = build_rollout_decision(request, high_risk=False, composition_candidate=True)
        assert planner_only.route_mode == "control"
        assert planner_only.planner_mode == "composition_active"

    valid_composition = RoutingDecision(
        mode="rule",
        tasks=[
            RoutedTask(task_id="task_1", intent=IntentName.history_search, topic="洋务运动"),
            RoutedTask(task_id="task_2", intent=IntentName.quiz_generation, topic="洋务运动", count=3, depends_on=["task_1"]),
        ],
        confidence=0.95,
        reason_code="multi_intent_explain_then_quiz",
    )
    valid_plan = build_task_plan(valid_composition, {"message": "先解释洋务运动，再出3道题"}, enable_composition=True)
    assert [step.operation for step in valid_plan.steps] == ["search_history_knowledge", "answer_from_sources", "quiz_from_sources"]

    forbidden_composition = RoutingDecision(
        mode="semantic",
        tasks=[
            RoutedTask(task_id="task_1", intent=IntentName.character_recommendation, topic="洋务运动"),
            RoutedTask(task_id="task_2", intent=IntentName.quiz_generation, topic="洋务运动", count=3, depends_on=["task_1"]),
        ],
        confidence=0.9,
        reason_code="semantic_multi_intent",
    )
    guarded_plan = build_task_plan(forbidden_composition, {"message": "推荐人物再出题"}, enable_composition=True)
    assert [step.operation for step in guarded_plan.steps] == ["recommend_character"]

    print("learning_assistant_rollout_smoke=PASS")
    print("stable_bucket_rate=1.0")
    print("rollout_boundary_rate=1.0")
    print("rollout_safety_override_rate=1.0")
    print("planner_explain_then_quiz_only_rate=1.0")


if __name__ == "__main__":
    main()
