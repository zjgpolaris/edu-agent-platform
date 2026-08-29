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
    print("render_container_contract_smoke=PASS")


if __name__ == "__main__":
    main()
