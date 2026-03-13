#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DARKTABLE_DIR="$ROOT_DIR/darktable"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  PYTHON_BIN="python3"
fi

cd "$ROOT_DIR"

timeout --signal=KILL 30s "$PYTHON_BIN" -m pytest server/tests -q
timeout --signal=KILL 20s ./scripts/smoke_chat.sh
timeout --signal=KILL 30s bash ./scripts/smoke_darktable_client.sh

(
  cd "$DARKTABLE_DIR"
  timeout --signal=KILL 20s cc -fsyntax-only -I. -I./src \
    $(pkg-config --cflags glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0) \
    $(curl-config --cflags) src/common/agent_protocol.c

  timeout --signal=KILL 20s cc -fsyntax-only -I. -I./src \
    $(pkg-config --cflags glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0) \
    $(curl-config --cflags) src/common/agent_client.c

  timeout --signal=KILL 20s cc -fsyntax-only -I. -I./src \
    $(pkg-config --cflags glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0) \
    src/common/agent_actions.c

  timeout --signal=KILL 20s cc -fsyntax-only -I. -I./src \
    $(pkg-config --cflags glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0) \
    src/libs/agent_chat.c

  SMOKE_BIN="$(mktemp ./agent_common_smoke.XXXXXX)"
  trap 'rm -f "$SMOKE_BIN"' EXIT

  timeout --signal=KILL 20s cc -I. -I./src \
    $(pkg-config --cflags glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0) \
    src/tests/unittests/agent/agent_common_smoke.c \
    src/tests/unittests/agent/agent_stubs.c \
    src/common/agent_protocol.c \
    src/common/agent_actions.c \
    -o "$SMOKE_BIN" \
    $(pkg-config --libs glib-2.0 gobject-2.0 gio-2.0 json-glib-1.0 gtk+-3.0 librsvg-2.0)

  timeout --signal=KILL 20s "$SMOKE_BIN"
)

echo "Step 1 validation passed"
