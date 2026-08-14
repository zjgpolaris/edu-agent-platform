from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

import run_core_evals as runner


def _result(*, metrics=None, name: str = "synthetic_evidence_suite", stdout: str = "", stderr: str = "") -> runner.SuiteResult:
    return runner.SuiteResult(
        name=name,
        command=[],
        returncode=0,
        duration_sec=0.01,
        stdout=stdout,
        stderr=stderr,
        passed_cases=1,
        failed_cases_count=0,
        total_cases=1,
        metrics=metrics or {},
        failed_cases=[],
    )


def _skipped_result(name: str = "learning_assistant_semantic_router_eval") -> runner.SuiteResult:
    return runner.SuiteResult(
        name=name,
        command=[],
        returncode=0,
        duration_sec=0.01,
        stdout="SKIP learning_assistant_semantic_router_eval: llm_credentials_not_configured\n",
        stderr="",
        passed_cases=0,
        failed_cases_count=0,
        total_cases=1,
        metrics={"real_llm_calls": {"value": 0.0}},
        failed_cases=[],
        skipped_cases_count=1,
        skipped_cases=["learning_assistant_semantic_router_eval: llm_credentials_not_configured"],
    )


def main() -> None:
    first_id = runner.new_eval_run_id()
    second_id = runner.new_eval_run_id()
    assert first_id != second_id

    original_revision = runner.source_revision
    original_agent_ops = runner.collect_agent_ops_snapshot
    original_provider = os.environ.get("LLM_PROVIDER")
    original_model = os.environ.get("LLM_MODEL_QUALITY")
    runner.collect_agent_ops_snapshot = lambda **_: {"status": "no_events"}
    try:
        runner.source_revision = lambda: {"commit_sha": "a" * 40, "short_sha": "a" * 12, "dirty": False}
        fallback_only = runner.build_json_summary(
            [_result(metrics={"fallback_calls": {"value": 3.0}})],
            include_output=False,
            require_real_llm=True,
            evidence_profile="real_llm",
        )
        assert fallback_only["schema_version"] == 3
        assert fallback_only["ok"] is False
        assert fallback_only["llm_execution"]["run_scoped_calls"] == 0
        assert fallback_only["llm_execution"]["status"] == "not_run"

        os.environ["LLM_PROVIDER"] = "synthetic-provider"
        os.environ["LLM_MODEL_QUALITY"] = "synthetic-model-v1"
        provenance = runner.build_json_summary(
            [_result(metrics={"real_llm_calls": {"value": 1.0}})],
            include_output=False,
            evidence_profile="real_llm",
        )
        assert provenance["provenance"]["report_commit_sha"] == "a" * 40
        assert provenance["provenance"]["commit_matches_current_head"] is True
        assert provenance["provenance"]["provider"] == "synthetic-provider"
        assert provenance["provenance"]["model"] == "synthetic-model-v1"
        assert provenance["provenance"]["dataset_versions"]
        assert runner.report_runtime_status(provenance)["status"] == "fresh"
        runner.source_revision = lambda: {"commit_sha": "c" * 40, "short_sha": "c" * 12, "dirty": False}
        runtime_status = runner.report_runtime_status(provenance)
        assert runtime_status["status"] == "stale"
        assert "commit_mismatch" in runtime_status["reasons"]
        runner.source_revision = lambda: {"commit_sha": "a" * 40, "short_sha": "a" * 12, "dirty": False}

        normal_output = _result(
            stdout="OPENAI_API_KEY=sk-example-secret-value PRIVATE_PROMPT=student raw question",
            stderr="Authorization: Bearer abcdefghijklmnop",
        ).to_dict(include_output=True)
        normal_serialized = json.dumps(normal_output)
        assert "sk-example-secret-value" not in normal_serialized
        assert "student raw question" not in normal_serialized
        assert "abcdefghijklmnop" not in normal_serialized

        private_output = _result(
            name="learning_assistant_blind_eval",
            stdout="PRIVATE_PROMPT=never publish this prompt",
            stderr="ANTHROPIC_API_KEY=private-key-value",
        ).to_dict(include_output=True)
        private_serialized = json.dumps(private_output)
        assert "never publish this prompt" not in private_serialized
        assert "private-key-value" not in private_serialized
        assert private_output["stdout"] == "[REDACTED_PRIVATE_EVAL_OUTPUT]"

        credentials_missing = runner.build_json_summary(
            [_skipped_result()],
            include_output=False,
            require_real_llm=True,
            evidence_profile="real_llm",
        )
        assert credentials_missing["ok"] is False
        assert credentials_missing["llm_execution"]["status"] == "not_run"
        assert credentials_missing["skipped_suites"] == ["learning_assistant_semantic_router_eval"]
        assert credentials_missing["suites"][0]["status"] == "skipped"

        skipped_blind = runner.build_json_summary(
            [_skipped_result("learning_assistant_blind_eval")],
            include_output=False,
            evidence_profile="real_llm",
            require_release_seal=True,
        )
        assert "blind" not in skipped_blind["release_seal"]["required_profiles_passed"]
        assert "blind_profile_not_proven" in skipped_blind["release_seal"]["reasons"]

        observed = runner.build_json_summary(
            [_result(metrics={"real_llm_calls": {"value": 2.0}})],
            include_output=False,
            require_real_llm=True,
            evidence_profile="real_llm",
        )
        assert observed["ok"] is True
        assert observed["llm_execution"]["run_scoped_calls"] == 2
        assert observed["llm_execution"]["status"] == "observed"

        runner.source_revision = lambda: {"commit_sha": "b" * 40, "short_sha": "b" * 12, "dirty": True}
        dirty = runner.build_json_summary(
            [_result(metrics={"real_llm_calls": {"value": 2.0}})],
            include_output=False,
            evidence_profile="real_llm",
            require_release_seal=True,
        )
        assert dirty["release_seal"]["status"] == "fail"
        assert "working_tree_dirty" in dirty["release_seal"]["reasons"]
    finally:
        runner.source_revision = original_revision
        runner.collect_agent_ops_snapshot = original_agent_ops
        if original_provider is None:
            os.environ.pop("LLM_PROVIDER", None)
        else:
            os.environ["LLM_PROVIDER"] = original_provider
        if original_model is None:
            os.environ.pop("LLM_MODEL_QUALITY", None)
        else:
            os.environ["LLM_MODEL_QUALITY"] = original_model

    print("eval_run_evidence_smoke=PASS")
    print("run_id_uniqueness_rate=1.0")
    print("run_scoped_llm_evidence_rate=1.0")
    print("dirty_revision_rejection_rate=1.0")
    print("report_provenance_traceability_rate=1.0")
    print("report_privacy_redaction_rate=1.0")


if __name__ == "__main__":
    main()
