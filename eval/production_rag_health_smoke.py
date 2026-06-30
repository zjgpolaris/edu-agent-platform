"""生产 RAG 健康检查 smoke。

显式通过 API_BASE 指向线上后端；默认不进入本地 smoke/core 套件。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

API_BASE = os.getenv("API_BASE", "").rstrip("/")
COLLECTION = os.getenv("RAG_HEALTH_COLLECTION", "history")
TIMEOUT = float(os.getenv("SMOKE_TIMEOUT_SEC", "60"))
STRICT = os.getenv("PRODUCTION_SMOKE_STRICT") == "1"


def _fail(reason: str, *, detail: dict[str, Any] | None = None) -> None:
    payload = {"name": "production_rag_health", "reason": reason, "category": "rag", **(detail or {})}
    print(f"FAIL production_rag_health {reason}")
    print("FAILED_CASE_DETAIL=" + json.dumps(payload, ensure_ascii=False, sort_keys=True))
    print("production_rag_health_smoke=0/1")
    raise SystemExit(1)


def _skip(reason: str) -> None:
    print(f"SKIP production_rag_health_smoke: {reason}")
    print("production_rag_health_smoke=0/1")
    raise SystemExit(0)


def _request(method: str, path: str, *, token: str | None = None, body: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
    if path.startswith("http"):
        url = path
    else:
        url = f"{API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json", "User-Agent": "edu-agent-platform-production-smoke/1.0"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")[:1000]
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"raw": raw}
        return exc.code, payload
    except Exception as exc:
        _fail(f"request failed: {exc.__class__.__name__}: {str(exc)[:240]}")


def _resolve_token() -> str | None:
    token = os.getenv("API_TOKEN") or os.getenv("AUTH_TOKEN")
    if token:
        return token
    username = os.getenv("SMOKE_USERNAME")
    password = os.getenv("SMOKE_PASSWORD")
    if not username or not password:
        return None
    status, payload = _request("POST", "/api/auth/login", body={"username": username, "password": password})
    if status != 200:
        _fail("smoke login failed", detail={"http_status": status, "response": payload})
    token = payload.get("token")
    if not isinstance(token, str) or not token:
        _fail("smoke login response missing token", detail={"http_status": status})
    return token


def _require_check(payload: dict[str, Any], name: str) -> dict[str, Any]:
    checks = payload.get("checks")
    if not isinstance(checks, dict):
        _fail("response missing checks")
    check = checks.get(name)
    if not isinstance(check, dict):
        _fail(f"response missing check: {name}")
    if check.get("ok") is not True:
        _fail(f"check failed: {name}", detail={"check": check})
    return check


def main() -> None:
    if not API_BASE:
        if STRICT:
            _fail("API_BASE is not set")
        _skip("API_BASE is not set")

    token = _resolve_token()
    query = urllib.parse.urlencode({"collection": COLLECTION, "deep": "true"})
    status, payload = _request("GET", f"/api/debug/rag/health?{query}", token=token)
    if status == 401:
        _fail("missing auth token or smoke login credentials (HTTP 401)", detail={"http_status": status})
    if status != 200:
        _fail(f"rag health endpoint returned non-200 (HTTP {status})", detail={"http_status": status, "response": payload})
    if not isinstance(payload, dict):
        _fail("rag health response is not a JSON object")
    if payload.get("ok") is not True:
        _fail("rag health returned ok=false", detail={"response": payload})

    postgres = _require_check(payload, "postgres")
    if postgres.get("dialect") != "postgresql":
        _fail("database dialect is not postgresql", detail={"check": postgres})

    _require_check(payload, "pgvector_extension")
    _require_check(payload, "rag_table")
    collection = _require_check(payload, "collection")
    doc_count = int(collection.get("document_count") or 0)
    if doc_count < 1:
        _fail("collection has no indexed documents", detail={"check": collection})

    embedding = _require_check(payload, "embedding_api")
    if embedding.get("vector_dim") != embedding.get("expected_dim"):
        _fail("embedding dimension mismatch", detail={"check": embedding})

    vector_query = _require_check(payload, "vector_query")
    if int(vector_query.get("result_count") or 0) < 1:
        _fail("vector query returned no results", detail={"check": vector_query})

    config = payload.get("config") or {}
    embed_config = config.get("embedding") if isinstance(config, dict) else {}
    if isinstance(embed_config, dict) and embed_config.get("api_key_configured") is not True:
        _fail("embedding API key is not configured")

    print(
        f"OK production_rag_health endpoint_ok collection={COLLECTION} docs={doc_count} "
        f"vector_results={vector_query.get('result_count')}"
    )
    print("production_rag_health_smoke=1/1")


if __name__ == "__main__":
    main()
