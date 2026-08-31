from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    evidence = (ROOT / ".github/workflows/runtime-rollout-evidence.yml").read_text()
    deploy = (ROOT / ".github/workflows/deploy-environment.yml").read_text()
    assert "test \"$MINIMUM_SAMPLES\" -ge 100" in evidence
    assert evidence.index("Persist capability manifest") < evidence.index("Run real LLM business profile")
    assert evidence.index("Run real LLM business profile") < evidence.index("Run production RAG profile")
    assert "if [ \"$TARGET\" = staging ]; then test \"$PERCENT\" = 1; fi" in deploy
    assert "environment: ${{ inputs.target_environment }}" in deploy
    print("staging canary contract smoke passed")


if __name__ == "__main__":
    main()
