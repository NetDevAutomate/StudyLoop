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

# The same interpreter pin the installer applies (installers.install_workspace_tools
# passes --python); without it this smoke exercised whatever Python uv found.
PY_REQUEST="$(tr -d '[:space:]' < "$ROOT_DIR/.python-version")"

uv tool install --force --editable --python "$PY_REQUEST" "$ROOT_DIR/packages/studyloop[all]" \
  --with-editable "$ROOT_DIR/packages/agent-session-tools[all]"
uv tool install --force --editable --python "$PY_REQUEST" "$ROOT_DIR/packages/agent-session-tools[all]"

test -x "$TOOL_BIN/studyloop"
test -x "$TOOL_BIN/session-export"
# The studyloop venv serves `studyloop web`, whose boot-time encoder warm
# imports the semantic runtime in-process; without it the header chip reads
# "semantic: failed". Import level only: this isolated HOME has no Hugging
# Face cache, and fetching the ONNX artefact is `doctor --fix`'s job.
"$(uv tool dir)/studyloop/bin/python" -c "import huggingface_hub, numpy, onnxruntime, sqlite_vec, tokenizers"
STUDYLOOP_EXPECT_BIN_DIR="$TOOL_BIN" PATH="$TOOL_BIN:$PATH" "$ROOT_DIR/scripts/smoke-installed-cli.sh"
