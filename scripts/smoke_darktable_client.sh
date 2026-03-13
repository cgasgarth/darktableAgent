#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DARKTABLE_DIR="$ROOT_DIR/darktable"
HOST="127.0.0.1"
PORT="${PORT:-8001}"
SERVER_LOG="$(mktemp)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ -n "${SMOKE_BIN:-}" ]]; then
    rm -f "$SMOKE_BIN"
  fi
  rm -f "$SERVER_LOG"
}
trap cleanup EXIT

cd "$ROOT_DIR"
HOST="$HOST" PORT="$PORT" timeout 15s ./scripts/run_server.sh >"$SERVER_LOG" 2>&1 &
SERVER_PID=$!

ready=0
for _ in $(seq 1 30); do
  if "$PYTHON_BIN" - <<PY
import sys
import httpx
try:
    response = httpx.get("http://${HOST}:${PORT}/health", timeout=0.5)
    sys.exit(0 if response.status_code == 200 else 1)
except Exception:
    sys.exit(1)
PY
  then
    ready=1
    break
  fi
  sleep 0.2
done

if [[ "$ready" -ne 1 ]]; then
  echo "Server did not become ready" >&2
  cat "$SERVER_LOG" >&2
  exit 1
fi

(
  cd "$DARKTABLE_DIR"
  SMOKE_BIN="$(mktemp ./agent_client_smoke.XXXXXX)"
  trap 'rm -f "$SMOKE_BIN"' RETURN
  export DT_AGENT_TEST_ENDPOINT="http://${HOST}:${PORT}/v1/chat"
  cc -I. -I./src \
    $(pkg-config --cflags glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0) \
    $(curl-config --cflags) \
    src/tests/unittests/agent/agent_client_smoke.c \
    src/tests/unittests/agent/agent_stubs.c \
    src/common/agent_protocol.c \
    src/common/agent_client.c \
    src/common/agent_actions.c \
    -o "$SMOKE_BIN" \
    $(pkg-config --libs glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0) \
    $(curl-config --libs) -lm
  "$SMOKE_BIN"
)

echo "Darktable client smoke passed"
