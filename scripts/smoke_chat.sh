#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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

"$PYTHON_BIN" - <<PY
import httpx

base_url = "http://${HOST}:${PORT}"
client = httpx.Client(base_url=base_url, timeout=2.0)

cases = [
    (
        "echo",
        {
            "schemaVersion": "1.0",
            "requestId": "smoke-echo",
            "conversationId": "smoke-conv",
            "message": {"role": "user", "text": "Hello smoke"},
            "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
            "mockActionId": None,
        },
        lambda body: body["status"] == "ok" and body["actions"] == [],
        200,
    ),
    (
        "brighten",
        {
            "schemaVersion": "1.0",
            "requestId": "smoke-brighten",
            "conversationId": "smoke-conv",
            "message": {"role": "user", "text": "Brighten"},
            "uiContext": {"view": "darkroom", "imageId": 5, "imageName": "image.jpg"},
            "mockActionId": "brighten-exposure",
        },
        lambda body: body["actions"][0]["parameters"]["deltaEv"] == 0.7,
        200,
    ),
    (
        "darken",
        {
            "schemaVersion": "1.0",
            "requestId": "smoke-darken",
            "conversationId": "smoke-conv",
            "message": {"role": "user", "text": "Darken"},
            "uiContext": {"view": "darkroom", "imageId": 6, "imageName": "image.jpg"},
            "mockActionId": "darken-exposure",
        },
        lambda body: body["requestId"] == "smoke-darken"
        and body["conversationId"] == "smoke-conv"
        and body["actions"][0]["parameters"]["deltaEv"] == -0.7,
        200,
    ),
    (
        "invalid",
        {
            "schemaVersion": "1.0",
            "requestId": "smoke-invalid",
            "conversationId": "smoke-conv",
            "message": {"role": "assistant", "text": "bad"},
            "uiContext": {"view": "darkroom", "imageId": None, "imageName": None},
            "mockActionId": None,
        },
        lambda body: body["status"] == "error" and body["error"]["code"] == "invalid_request",
        422,
    ),
]

for name, payload, check, expected_status in cases:
    response = client.post("/v1/chat", json=payload)
    body = response.json()
    assert response.status_code == expected_status, (name, body)
    assert check(body), (name, body)
    print(f"[ok] {name}")
PY

echo "Smoke test passed"
