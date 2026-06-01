#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"

cleanup() {
  rm -rf "$tmp"
}
trap cleanup EXIT

mkdir -p \
  "$tmp/home" \
  "$tmp/xdg-config" \
  "$tmp/xdg-cache" \
  "$tmp/xdg-data"

export HOME="$tmp/home"
export XDG_CONFIG_HOME="$tmp/xdg-config"
export XDG_CACHE_HOME="$tmp/xdg-cache"
export XDG_DATA_HOME="$tmp/xdg-data"
TOOL_BIN="$tmp/bin"

uv tool install --force --editable "$ROOT_DIR/packages/studyloop[sessions,web,content]" \
  --with-editable "$ROOT_DIR/packages/agent-session-tools"

test -x "$TOOL_BIN/studyloop"
PATH="$TOOL_BIN:$PATH" "$ROOT_DIR/scripts/smoke-installed-cli.sh"
