#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$PYTHON_BIN"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

cleanup() {
  if [[ -n "${BACKEND_PID:-}" ]]; then
    kill "$BACKEND_PID" 2>/dev/null || true
  fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then
    kill "$FRONTEND_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$ROOT_DIR"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  source "$ROOT_DIR/.env.local"
  set +a
fi

export PYTHONPATH="$ROOT_DIR/backend${PYTHONPATH:+:$PYTHONPATH}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1 && [[ ! -x "$PYTHON_BIN" ]]; then
  printf 'Backend startup failed: Python interpreter not found: %s\n' "$PYTHON_BIN" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import alembic, fastapi, pydantic, sqlalchemy, uvicorn' >/dev/null 2>&1; then
  printf 'Backend startup failed: required Python packages are missing from %s\n' "$PYTHON_BIN" >&2
  printf 'Run: npm run setup:backend\n' >&2
  printf 'Or select an existing environment: PYTHON_BIN=/path/to/python npm run dev\n' >&2
  exit 1
fi

"$PYTHON_BIN" -m uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload &
BACKEND_PID=$!

sleep 1
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  backend_status=0
  wait "$BACKEND_PID" || backend_status=$?
  printf 'Backend exited during startup (status %s). Frontend was not started.\n' "$backend_status" >&2
  exit "$backend_status"
fi

npm run dev --prefix frontend &
FRONTEND_PID=$!

printf '\nEduAgent dev services started:\n'
printf '  Backend:  http://localhost:8000\n'
printf '  Frontend: http://localhost:3000\n\n'
printf 'Press Ctrl+C to stop both services.\n\n'

while kill -0 "$BACKEND_PID" 2>/dev/null && kill -0 "$FRONTEND_PID" 2>/dev/null; do
  sleep 1
done

if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  backend_status=0
  wait "$BACKEND_PID" || backend_status=$?
  printf '\nBackend exited (status %s); stopping frontend.\n' "$backend_status" >&2
  exit "$backend_status"
fi

frontend_status=0
wait "$FRONTEND_PID" || frontend_status=$?
printf '\nFrontend exited (status %s); stopping backend.\n' "$frontend_status" >&2
exit "$frontend_status"
