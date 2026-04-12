#!/bin/sh

set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
resources_dir=$(CDPATH= cd -- "$script_dir/../Resources" && pwd)
share_dir="$resources_dir/share"
schema_dir="$share_dir/glib-2.0/schemas"
binary="$script_dir/darktable-bin"

if [ ! -x "$binary" ]; then
  printf '%s\n' "darktable launcher error: missing executable $binary" >&2
  exit 1
fi

if [ -d "$schema_dir" ]; then
  export GSETTINGS_SCHEMA_DIR="$schema_dir"
fi

if [ -d "$share_dir" ]; then
  export XDG_DATA_DIRS="$share_dir${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}"
fi

exec "$binary" "$@"
