#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)

INSTALL_PREFIX="${INSTALL_PREFIX:-$REPO_ROOT/darktable/.install-5.4.1}"
RUNTIME_DIR="${RUNTIME_DIR:-$REPO_ROOT/.darktable-local}"
CONFIG_DIR="${CONFIG_DIR:-$RUNTIME_DIR/config}"
CACHE_DIR="${CACHE_DIR:-$RUNTIME_DIR/cache}"
DARKTABLE_LIBRARY_FILE="${DARKTABLE_LIBRARY_FILE:-$RUNTIME_DIR/library.db}"
DARKTABLE_AGENT_SERVER_TIMEOUT_SECONDS="${DARKTABLE_AGENT_SERVER_TIMEOUT_SECONDS:-180}"
DARKTABLE_LOG_FILE="${DARKTABLE_LOG_FILE:-$RUNTIME_DIR/darktable.log}"
FOREGROUND="${DARKTABLE_FOREGROUND:-0}"

args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --foreground)
      FOREGROUND=1
      shift
      ;;
    --detached)
      FOREGROUND=0
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

mkdir -p "$CONFIG_DIR" "$CACHE_DIR"

cmd=(
  "$INSTALL_PREFIX/bin/darktable"
  --conf "plugins/ai/agent/timeout_seconds=$DARKTABLE_AGENT_SERVER_TIMEOUT_SECONDS"
  --configdir "$CONFIG_DIR"
  --cachedir "$CACHE_DIR"
  --library "$DARKTABLE_LIBRARY_FILE"
  "${args[@]}"
)

if [[ "$FOREGROUND" == "1" ]]; then
  exec "${cmd[@]}"
fi

nohup "${cmd[@]}" >"$DARKTABLE_LOG_FILE" 2>&1 < /dev/null &
echo "Started darktable (PID $!)"
echo "Log: $DARKTABLE_LOG_FILE"
