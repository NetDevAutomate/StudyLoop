#!/usr/bin/env bash
# Compatibility wrapper around `studyctl install agents`.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(dirname "$SCRIPT_DIR")

TOOLS=()
UNINSTALL=false

for arg in "$@"; do
  case "$arg" in
    --kiro)      TOOLS+=("--tool" "kiro") ;;
    --claude)    TOOLS+=("--tool" "claude") ;;
    --gemini)    TOOLS+=("--tool" "gemini") ;;
    --opencode)  TOOLS+=("--tool" "opencode") ;;
    --codex)     TOOLS+=("--tool" "codex") ;;
    --amp)       TOOLS+=("--tool" "amp") ;;
    --uninstall) UNINSTALL=true ;;
    -h|--help)
      echo "Usage: ./scripts/install-agents.sh [--kiro|--claude|--gemini|--opencode|--codex|--amp] [--uninstall]"
      exit 0
      ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

CMD=(uv run studyctl install agents)
CMD+=("${TOOLS[@]}")
if $UNINSTALL; then
  CMD+=("--uninstall")
fi

(cd "$REPO_DIR" && "${CMD[@]}")
