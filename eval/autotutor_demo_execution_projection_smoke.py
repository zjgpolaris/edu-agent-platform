from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from agents.autotutor_demo_execution import project_execution


def main():
    assert project_execution(None) is None
    assert project_execution({}) is None
    raw = {"schema_version": 1, "profile": "local_demo_graph", "revision": 2,
           "assigned_executor": "graph_active", "selected_executor": "legacy",
           "graph_attempt_status": "mismatch", "visited_nodes": ["load_context", "answer-secret", "build_outcome"],
           "fallback_reason": "active_comparator_mismatch:secret", "password": "secret", "production_evidence": True}
    result = project_execution(raw)
    assert result["visited_nodes"] == ["load_context", "build_outcome"]
    assert result["fallback_reason"] == "comparator_mismatch"
    assert result["production_evidence"] is False and "secret" not in str(result)
    assert project_execution(result) == result
    print("autotutor_demo_execution_projection_smoke=PASS")


if __name__ == "__main__":
    main()
