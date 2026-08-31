#!/usr/bin/env bash
# Compatibility wrapper around `studyloop install agents`.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(dirname "$SCRIPT_DIR")

TOOLS=()
UNINSTALL=false

for arg in "$@"; do
  case "$arg" in
    --kiro)      TOOLS+=("--tool" "kiro") ;;
    --claude)    TOOLS+=("--tool" "claude") ;;
    --opencode)  TOOLS+=("--tool" "opencode") ;;
    --codex)     TOOLS+=("--tool" "codex") ;;
    --pi)        TOOLS+=("--tool" "pi") ;;
    --uninstall) UNINSTALL=true ;;
    -h|--help)
      echo "Usage: ./scripts/install-agents.sh [--kiro|--codex|--claude|--opencode|--pi] [--uninstall]"
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

CMD=(uv run studyloop install agents)
CMD+=("${TOOLS[@]}")
if $UNINSTALL; then
  CMD+=("--uninstall")
fi

(cd "$REPO_DIR" && "${CMD[@]}")
