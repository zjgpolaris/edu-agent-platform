from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    dockerfile = (ROOT / "backend" / "Dockerfile").read_text(encoding="utf-8")
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    render = (ROOT / "render.yaml").read_text(encoding="utf-8")

    assert "ENV PORT=10000" in dockerfile
    assert "EXPOSE 10000" in dockerfile
    assert "os.getenv('PORT', '10000')" in dockerfile
    assert "- PORT=8000" in compose
    assert "healthCheckPath: /api/health" in render
    assert "key: EDU_AGENT_AUTH_REQUIRED" in render
    assert 'value: "true"' in render
    assert "key: JWT_SECRET" in render
    assert "# 生产认证签名密钥，必须在 Render 面板设置为随机高强度值。" in render
    print("render_container_contract_smoke=PASS")


if __name__ == "__main__":
    main()
