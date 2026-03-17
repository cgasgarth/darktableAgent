#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd -P)

info()  { printf '\033[36m[INFO]\033[0m %s\n' "$1"; }
warn()  { printf '\033[33m[WARN]\033[0m %s\n' "$1"; }
error() { printf '\033[31m[ERROR]\033[0m %s\n' "$1"; }

OS="$(uname -s)"

install_macos_deps() {
  if ! command -v brew &>/dev/null; then
    error "Homebrew is required but not found. Install it from https://brew.sh/"
    exit 1
  fi
  info "Installing darktable build dependencies via Homebrew..."

  local deps=(
    cmake
    ninja
    pkg-config
    curl
    desktop-file-utils
    exiv2
    gettext
    glib
    gtk-mac-integration
    gtk+3
    icu4c
    intltool
    iso-codes
    jpeg-turbo
    lensfun
    libomp
    librsvg
    little-cms2
    llvm
    lua
    openexr
    perl
    pugixml
    sdl2
    graphicsmagick
    gphoto2
    webp
    libavif
    libraw
    libsecret
    sqlite
    portmidi
    po4a
    adwaita-icon-theme
    json-glib
  )

  local missing=()
  local installed
  installed=$(brew list --formula --quiet)

  for dep in "${deps[@]}"; do
    if ! echo "$installed" | grep -qx "$dep"; then
      missing+=("$dep")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    info "Installing missing packages: ${missing[*]}"
    brew install "${missing[@]}"
  else
    info "All Homebrew dependencies already installed."
  fi

  brew link --force libomp 2>/dev/null || true
}

install_linux_deps() {
  info "On Linux, install darktable build dependencies using your package manager."
  info "Examples:"
  info "  Fedora/RHEL:   sudo dnf builddep darktable"
  info "  Ubuntu/Debian: sudo apt-get build-dep darktable"
  info "  OpenSuse:      sudo zypper si -d darktable"
  info "Also ensure ninja and cmake are installed."
}

install_python_deps() {
  if ! command -v uv &>/dev/null; then
    error "'uv' is required but not found. Install it from https://docs.astral.sh/uv/"
    exit 1
  fi
  info "Installing Python dependencies with uv..."
  cd "$REPO_ROOT"
  uv sync --extra dev
}

info "Detected OS: $OS"

case "$OS" in
  Darwin)
    install_macos_deps
    ;;
  Linux)
    install_linux_deps
    ;;
  *)
    warn "Unsupported OS '$OS'. Skipping system dependency installation."
    ;;
esac

install_python_deps

info "Setup complete. Next steps:"
info "  npm run darktable:build   # build darktable"
info "  npm run server:start      # start the backend"
info "  npm run darktable:start   # start darktable"
