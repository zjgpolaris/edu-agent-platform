from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-llm-capability-runtime.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from db.engine import engine
from db.schema import metadata
from eval.llm_capability_test_support import configure_provenance, valid_manifest
from llm.capability_manifest import capability_status, clear_capability_manifest_cache
from llm.capability_store import save_capability_manifest
from llm.registry import get_default_registry


def main() -> None:
    configure_provenance()
    metadata.create_all(engine)
    registry = get_default_registry()
    manifest = valid_manifest(registry)
    save_capability_manifest(manifest, registry)
    clear_capability_manifest_cache()
    status = capability_status(registry)
    assert status["status"] == "pass", status
    assert status["manifest_source"] == "database"
    assert status["manifest_store_status"] == "pass"
    assert capability_status(registry)["cache_status"] == "hit"
    os.environ["EDU_AGENT_DEPLOYED_COMMIT"] = "different-immutable-commit"
    clear_capability_manifest_cache()
    missing = capability_status(registry)
    assert missing["status"] == "missing" and missing["manifest_store_status"] == "missing"
    override = Path(tempfile.gettempdir()) / "edu-agent-capability-override.json"
    override.write_text(json.dumps(manifest), encoding="utf-8")
    os.environ["EDU_AGENT_LLM_CAPABILITY_MANIFEST_PATH"] = str(override)
    os.environ["EDU_AGENT_ENVIRONMENT"] = "production"
    file_status = capability_status(registry)
    assert file_status["manifest_source"] == "file_override"
    assert "manifest_file_override_in_production" in file_status["warnings"]
    print("llm capability runtime resolution smoke passed")


if __name__ == "__main__":
    main()
