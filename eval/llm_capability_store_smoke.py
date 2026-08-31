from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = Path(tempfile.gettempdir()) / "edu-agent-llm-capability-store.sqlite3"
DB_PATH.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from db.engine import engine
from db.schema import metadata
from eval.llm_capability_test_support import configure_provenance, valid_manifest
from llm.capability_manifest import current_provenance
from llm.capability_store import load_capability_manifest_by_hash, load_capability_manifest_exact, save_capability_manifest
from llm.registry import get_default_registry


def main() -> None:
    configure_provenance()
    metadata.create_all(engine)
    registry = get_default_registry()
    manifest = valid_manifest(registry)
    assert save_capability_manifest(manifest, registry) == manifest
    assert save_capability_manifest(manifest, registry) == manifest
    assert load_capability_manifest_exact(current_provenance()) == manifest
    assert load_capability_manifest_by_hash(manifest["manifest_sha256"]) == manifest
    secret = dict(manifest)
    secret["api_key"] = "must-not-persist"
    try:
        save_capability_manifest(secret, registry)
    except ValueError as exc:
        assert "forbidden" in str(exc)
    else:
        raise AssertionError("secret-bearing manifest was accepted")
    print("llm capability store smoke passed")


if __name__ == "__main__":
    main()
