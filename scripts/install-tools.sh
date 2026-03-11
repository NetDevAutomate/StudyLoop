#!/bin/bash
# Install all workspace packages as uv tools (globally available CLIs).
#
# Usage:
#   ./scripts/install-tools.sh            # fresh install
#   ./scripts/install-tools.sh --force    # reinstall / upgrade
#
# This installs each package under packages/ as a standalone tool,
# making studyctl, session-export, session-query etc. available
# system-wide without activating a venv.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
FORCE_FLAG=""

if [[ "${1:-}" == "--force" ]]; then
    FORCE_FLAG="--force"
fi

cd "$REPO_ROOT"

echo "Installing workspace packages as uv tools..."
echo ""

for pkg in packages/*/; do
    pkg_name=$(basename "$pkg")
    echo "  → $pkg_name"
    uv tool install "$pkg" --editable $FORCE_FLAG 2>&1 | sed 's/^/    /'
    echo ""
done

echo "Done. Installed tools:"
uv tool list 2>/dev/null | grep -E "^(studyctl|agent-session-tools)" | sed 's/^/  /'
