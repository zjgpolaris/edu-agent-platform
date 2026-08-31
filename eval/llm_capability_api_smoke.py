from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.pop("EDU_AGENT_LLM_CAPABILITY_MANIFEST_PATH", None)
os.environ.pop("EDU_AGENT_LLM_ENABLED_CAPABILITIES", None)

from api.routers.debug import llm_capabilities, llm_health, router  # noqa: E402
from security.auth import Actor  # noqa: E402


async def main_async() -> None:
    admin = Actor(actor_id="admin", role="admin", traffic_cohort="operator")
    capability = await llm_capabilities(admin)
    assert capability["status"] == "missing", capability
    assert capability["reasons"] == ["manifest_missing"]
    encoded = str(capability).lower()
    for forbidden in ("authorization", "api_key", "image:data", "student_content"):
        assert forbidden not in encoded, forbidden

    shallow = await llm_health(deep=False, actor=admin)
    assert shallow["ok"] is True
    assert "capability_manifest" in shallow

    paths = [getattr(route, "path", "") for route in router.routes]
    assert paths.count("/api/admin/llm/capabilities") == 1
    print("llm_capability_api_smoke=PASS")


if __name__ == "__main__":
    asyncio.run(main_async())
