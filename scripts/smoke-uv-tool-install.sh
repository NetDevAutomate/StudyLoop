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
export UV_TOOL_BIN_DIR="$tmp/bin"
TOOL_BIN="$UV_TOOL_BIN_DIR"

uv tool install --force --editable "$ROOT_DIR/packages/studyloop[all]" \
  --with-editable "$ROOT_DIR/packages/agent-session-tools"
uv tool install --force --editable "$ROOT_DIR/packages/agent-session-tools[all]"

test -x "$TOOL_BIN/studyloop"
test -x "$TOOL_BIN/session-export"
STUDYLOOP_EXPECT_BIN_DIR="$TOOL_BIN" PATH="$TOOL_BIN:$PATH" "$ROOT_DIR/scripts/smoke-installed-cli.sh"
