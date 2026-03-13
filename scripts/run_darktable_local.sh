#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)

INSTALL_PREFIX="${INSTALL_PREFIX:-$REPO_ROOT/darktable/.install-5.4.1}"
RUNTIME_DIR="${RUNTIME_DIR:-$REPO_ROOT/.darktable-local}"
CONFIG_DIR="${CONFIG_DIR:-$RUNTIME_DIR/config}"
CACHE_DIR="${CACHE_DIR:-$RUNTIME_DIR/cache}"
DARKTABLE_LIBRARY_FILE="${DARKTABLE_LIBRARY_FILE:-$RUNTIME_DIR/library.db}"

mkdir -p "$CONFIG_DIR" "$CACHE_DIR"

exec "$INSTALL_PREFIX/bin/darktable" \
  --configdir "$CONFIG_DIR" \
  --cachedir "$CACHE_DIR" \
  --library "$DARKTABLE_LIBRARY_FILE" \
  "$@"
