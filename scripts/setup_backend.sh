#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BOOTSTRAP="${PYTHON_BIN:-python3}"

cd "$ROOT_DIR"

if [[ -z "${SSL_CERT_FILE:-}" ]]; then
  PYTHON_CA_FILE="$("$PYTHON_BOOTSTRAP" -c 'import ssl; print(ssl.get_default_verify_paths().openssl_cafile or "")')"
  if [[ ! -r "$PYTHON_CA_FILE" && -r /etc/ssl/cert.pem ]]; then
    export SSL_CERT_FILE=/etc/ssl/cert.pem
    printf 'Using macOS system CA bundle: %s\n' "$SSL_CERT_FILE"
  fi
fi

if [[ ! -x "$ROOT_DIR/.venv/bin/python" ]]; then
  "$PYTHON_BOOTSTRAP" -m venv "$ROOT_DIR/.venv"
fi

"$ROOT_DIR/.venv/bin/python" -m pip install --no-cache-dir \
  --constraint "$ROOT_DIR/constraints-runtime.txt" \
  --requirement "$ROOT_DIR/backend/requirements-runtime.txt"

"$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/scripts/verify_environment.py"
printf 'Backend environment ready: %s\n' "$ROOT_DIR/.venv/bin/python"
