"""Allowlisted execution facts, independent of pedagogical event labels."""
from __future__ import annotations

NODES = frozenset({"load_context", "plan", "judge", "advance", "reflect", "re_plan", "reteach",
                   "mark_struggling", "verify_exit_ticket", "recovery_resume", "fail", "build_outcome",
                   "content_gate", "teach", "prepare_assessment", "next_content_or_exit", "calculate_mastery",
                   "build_effect_intents", "validate_state", "route_current_phase"})
REASONS = frozenset({"kill_switch_enabled", "demo_graph_disabled", "demo_actor_ineligible",
                    "demo_environment_forbidden", "demo_hosted_environment_forbidden", "demo_configuration_invalid",
                    "demo_external_database_forbidden", "demo_database_isolation_required", "demo_verification_traffic_forbidden",
                    "graph_execution_failed", "comparator_mismatch", "execution_degraded", "demo_external_provider_forbidden"})


def safe_reason(reason):
    if not reason:
        return None
    if not isinstance(reason, str):
        return "execution_degraded"
    if reason in REASONS:
        return reason
    if str(reason).startswith("graph_precommit_fallback:"):
        return "graph_execution_failed"
    if str(reason).startswith("active_comparator_mismatch:"):
        return "comparator_mismatch"
    return "execution_degraded"


def project_execution(raw):
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        return None
    if raw.get("profile") != "local_demo_graph":
        return None
    revision = raw.get("revision")
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        return None
    nodes = raw.get("visited_nodes") if isinstance(raw.get("visited_nodes"), list) else []
    # Ignore malformed enum values without raising on unhashable payloads.
    raw = {key: value for key, value in raw.items() if isinstance(value, (str, int, bool)) or value is None}
    return {
        "schema_version": 1, "profile": "local_demo_graph", "production_evidence": False,
        "revision": revision,
        "transition_kind": raw.get("transition_kind") if raw.get("transition_kind") in {"start", "lesson_answer", "exit_ticket_answer", "recovery_resume"} else None,
        "assigned_executor": raw.get("assigned_executor") if raw.get("assigned_executor") in {"legacy", "graph_active"} else None,
        "selected_executor": raw.get("selected_executor") if raw.get("selected_executor") in {"legacy", "graph_active"} else None,
        "graph_attempt_status": raw.get("graph_attempt_status") if raw.get("graph_attempt_status") in {"completed", "failed", "not_run", "mismatch"} else "not_run",
        "visited_nodes": [n for n in nodes if isinstance(n, str) and n in NODES][:30],
        "fallback_reason": safe_reason(raw.get("fallback_reason")),
        "input_mode": "deterministic_fixture",
    }


def record_execution(outcome, *, before, transition_kind, nodes, attempt_status):
    if before.execution_profile != "local_demo_graph":
        return outcome
    state = outcome.next_state
    state.execution_summary = project_execution({
        "schema_version": 1, "profile": before.execution_profile, "revision": state.revision,
        "transition_kind": transition_kind, "assigned_executor": state.executor_assigned_mode,
        "selected_executor": state.executor_mode, "graph_attempt_status": attempt_status,
        "visited_nodes": nodes, "fallback_reason": state.executor_fallback_reason,
    })
    # Preserve transition-only reflection/feedback and idempotency information.
    # Rebuilding from persisted state discards these response fields.
    outcome.public_result = {**outcome.public_result, "execution": state.execution_summary}
    return outcome
