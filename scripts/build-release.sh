#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

rm -rf dist
mkdir -p dist

# The studyloop wheel declares agent-session-tools as a required dependency,
# but agent-session-tools is not published on PyPI — a release therefore
# ships BOTH wheels, installed together:
#   uv pip install dist/agent_session_tools-*.whl "dist/studyloop-*.whl[web]"
uv build --package studyloop --no-sources "$@"
uv build --package agent-session-tools --no-sources "$@"
