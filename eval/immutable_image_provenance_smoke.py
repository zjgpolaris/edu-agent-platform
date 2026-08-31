from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    workflow = (ROOT / ".github/workflows/backend-image-release.yml").read_text()
    deploy = (ROOT / ".github/workflows/deploy-environment.yml").read_text()
    render = (ROOT / "render.yaml").read_text()
    assert "platforms: linux/amd64" in workflow
    assert "docker/build-push-action@v6" in workflow
    assert "steps.build.outputs.digest" in workflow
    assert "build-args: EDU_AGENT_BUILD_COMMIT=${{ inputs.commit }}" in workflow
    assert "imgURL=${IMAGE_BASE}@${DIGEST}" in deploy
    assert "api.render.com/v1/services/$RENDER_SERVICE_ID/env-vars/$1" in deploy
    assert "update_env EDU_AGENT_IMAGE_DIGEST \"$DIGEST\"" in deploy
    assert "--expected-image-digest \"$DIGEST\"" in deploy
    assert "autoDeploy: false" in render
    print("immutable image provenance smoke passed")


if __name__ == "__main__":
    main()
