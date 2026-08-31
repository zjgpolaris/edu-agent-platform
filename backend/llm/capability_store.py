"""Append-only database storage for provenance-bound LLM capability manifests."""
from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from db.engine import get_connection

_FORBIDDEN_KEYS = {
    "authorization", "api_key", "apikey", "prompt", "raw_prompt", "raw_output",
    "student_content", "image_base64", "error_body", "request_body", "response_body",
}


class CapabilityManifestStoreUnavailable(RuntimeError):
    pass


def _assert_minimized(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _FORBIDDEN_KEYS:
                raise ValueError(f"capability manifest contains forbidden field: {key}")
            _assert_minimized(item)
    elif isinstance(value, list):
        for item in value:
            _assert_minimized(item)


def _context(connection: Any | None):
    return nullcontext(connection) if connection is not None else get_connection()


def _require_table(conn: Any) -> None:
    if "llm_capability_manifests" not in set(sa_inspect(conn).get_table_names()):
        raise CapabilityManifestStoreUnavailable("LLM capability manifest schema is not migrated")


def save_capability_manifest(payload: dict[str, Any], registry: Any | None = None, *, connection: Any | None = None) -> dict[str, Any]:
    from .capability_manifest import capability_manifest_sha256, validate_capability_manifest

    if not isinstance(payload, dict):
        raise ValueError("capability manifest must be an object")
    _assert_minimized(payload)
    if payload.get("manifest_sha256") != capability_manifest_sha256(payload):
        raise ValueError("capability manifest hash is invalid")
    reasons = validate_capability_manifest(payload, registry, expected_provenance={}, require_expected_provenance=False)
    if reasons:
        raise ValueError(f"capability manifest is invalid: {','.join(reasons)}")
    required = ("provider", "environment", "deployed_commit", "image_digest", "runtime_config_version", "endpoint_fingerprint", "generated_at", "expires_at")
    if any(not str(payload.get(field) or "").strip() for field in required):
        raise ValueError("capability manifest provenance is incomplete")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    params = {field: payload[field] for field in required}
    params.update({
        "manifest_id": f"llm_manifest_{uuid4().hex}",
        "schema_version": int(payload["schema_version"]),
        "manifest_sha256": payload["manifest_sha256"],
        "payload_json": encoded,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    existing = load_capability_manifest_by_hash(str(payload["manifest_sha256"]), connection=connection)
    if existing is not None:
        return existing
    try:
        with _context(connection) as conn:
            _require_table(conn)
            conn.execute(text("""INSERT INTO llm_capability_manifests (
                manifest_id, schema_version, provider, environment, deployed_commit, image_digest,
                runtime_config_version, endpoint_fingerprint, manifest_sha256, generated_at,
                expires_at, payload_json, created_at
            ) VALUES (
                :manifest_id, :schema_version, :provider, :environment, :deployed_commit, :image_digest,
                :runtime_config_version, :endpoint_fingerprint, :manifest_sha256, :generated_at,
                :expires_at, :payload_json, :created_at
            )"""), params)
    except IntegrityError:
        existing = load_capability_manifest_by_hash(str(payload["manifest_sha256"]))
        if existing is None:
            raise
        return existing
    return payload


def _decode(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, json.JSONDecodeError):
        return None
    from .capability_manifest import capability_manifest_sha256
    digest = str(row["manifest_sha256"] or "")
    if not isinstance(payload, dict) or payload.get("manifest_sha256") != digest or capability_manifest_sha256(payload) != digest:
        return None
    return payload


def load_capability_manifest_exact(provenance: dict[str, str], *, connection: Any | None = None) -> dict[str, Any] | None:
    fields = ("provider", "environment", "deployed_commit", "image_digest", "runtime_config_version", "endpoint_fingerprint")
    if any(not str(provenance.get(field) or "").strip() for field in fields):
        return None
    try:
        with _context(connection) as conn:
            _require_table(conn)
            row = conn.execute(text("""SELECT payload_json, manifest_sha256 FROM llm_capability_manifests
                WHERE provider=:provider AND environment=:environment AND deployed_commit=:deployed_commit AND image_digest=:image_digest
                  AND runtime_config_version=:runtime_config_version AND endpoint_fingerprint=:endpoint_fingerprint
                ORDER BY generated_at DESC LIMIT 1"""), {field: provenance[field] for field in fields}).mappings().first()
    except SQLAlchemyError as exc:
        raise CapabilityManifestStoreUnavailable(str(exc)) from exc
    return _decode(row)


def load_capability_manifest_by_hash(digest: str, *, connection: Any | None = None) -> dict[str, Any] | None:
    try:
        with _context(connection) as conn:
            _require_table(conn)
            row = conn.execute(text("""SELECT payload_json, manifest_sha256 FROM llm_capability_manifests
                WHERE manifest_sha256=:digest LIMIT 1"""), {"digest": digest}).mappings().first()
    except SQLAlchemyError as exc:
        raise CapabilityManifestStoreUnavailable(str(exc)) from exc
    return _decode(row)
