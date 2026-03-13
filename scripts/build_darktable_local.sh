#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)
DARKTABLE_DIR="$REPO_ROOT/darktable"

BUILD_DIR="${BUILD_DIR:-$DARKTABLE_DIR/build-5.4.1}"
INSTALL_PREFIX="${INSTALL_PREFIX:-$DARKTABLE_DIR/.install-5.4.1}"
BUILD_TYPE="${BUILD_TYPE:-RelWithDebInfo}"
BUILD_GENERATOR="${BUILD_GENERATOR:-Ninja}"
JOBS="${JOBS:-$(nproc)}"

exec "$DARKTABLE_DIR/build.sh" \
  --build-generator "$BUILD_GENERATOR" \
  --build-dir "$BUILD_DIR" \
  --prefix "$INSTALL_PREFIX" \
  --build-type "$BUILD_TYPE" \
  --install \
  -j "$JOBS" \
  "$@"
