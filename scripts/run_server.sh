#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOST="${HOST:-${DARKTABLE_AGENT_SERVER_HOST:-127.0.0.1}}"
PORT="${PORT:-${DARKTABLE_AGENT_SERVER_PORT:-8001}}"

cd "$ROOT_DIR"
exec uv run python -m uvicorn server.app:app --host "$HOST" --port "$PORT"
