"""Local demo admission is not a production permission."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]
from scripts.dev_autotutor_graph_demo import prepare_directory, demo_environment
from agents.autotutor_demo_policy import configuration_errors, eligibility_reason


def main():
    directory = prepare_directory()
    env = demo_environment(directory, {})
    assert configuration_errors({}) == []
    assert configuration_errors(env) == []
    sanitized = demo_environment(directory, {"OPENAI_API_KEY": "fake-secret", "BAILIAN_API_KEY": "fake-secret", "LANGSMITH_TRACING": "true"})
    assert "OPENAI_API_KEY" not in sanitized and "BAILIAN_API_KEY" not in sanitized
    assert sanitized["LANGSMITH_TRACING"] == "false"
    for change in ({"EDU_AGENT_ENVIRONMENT": "production"}, {"RENDER_SERVICE_NAME": "app"},
                   {"EDU_AGENT_ENVIRONMENT": "unknown"}, {"DATABASE_URL": "postgresql://invalid"},
                   {"EDU_AGENT_AUTH_REQUIRED": "false"}, {"EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "active_canary"},
                   {"EDU_AGENT_DATA_SCOPE": "runtime"}, {"EDU_AGENT_LLM_DISABLED": "0"},
                   {"EDU_AGENT_AUTH_DB_AUTHORITY": "false"}, {"OPENAI_API_KEY": "fake-secret"}):
        assert configuration_errors({**env, **change}), change
    with patch.dict(os.environ, env, clear=True):
        with patch("security.accounts.get_account", return_value={"role": "student", "account_status": "active", "traffic_cohort": "demo"}):
            assert eligibility_reason("s", actor_id="s", actor_role="student") is None
            assert eligibility_reason("s", actor_id="t", actor_role="student")
            assert eligibility_reason("s", actor_id="s", actor_role="teacher")
            assert eligibility_reason("s", actor_id="s", actor_role="student", traffic_source="release_verification")
            with patch.dict(os.environ, {"EDU_AGENT_AUTOTUTOR_GRAPH_KILL_SWITCH": "true"}):
                assert eligibility_reason("s", actor_id="s", actor_role="student") == "kill_switch_enabled"
        with patch("security.accounts.get_account", return_value={"role": "student", "account_status": "disabled", "traffic_cohort": "demo"}):
            assert eligibility_reason("s", actor_id="s", actor_role="student") == "demo_actor_ineligible"
    try:
        demo_environment(directory, {"DATABASE_URL": "postgresql://invalid"})
    except ValueError:
        pass
    else:
        raise AssertionError("inherited database accepted")
    print("autotutor_demo_graph_policy_smoke=PASS")


if __name__ == "__main__":
    main()
