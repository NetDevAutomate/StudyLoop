#!/usr/bin/env bash
# Thin bootstrap wrapper for studyctl source installs.
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$1"; }
err()   { printf "${RED}✗${NC} %s\n" "$1"; }
step()  { printf "\n${BOLD}▸ %s${NC}\n" "$1"; }

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(dirname "$SCRIPT_DIR")

TOOLS_ONLY=false
AGENTS_ONLY=false
NON_INTERACTIVE=false

for arg in "$@"; do
  case "$arg" in
    --tools-only)      TOOLS_ONLY=true ;;
    --agents-only)     AGENTS_ONLY=true ;;
    --non-interactive) NON_INTERACTIVE=true ;;
    --help|-h)
      echo "Usage: ./scripts/install.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --non-interactive  Accepted for CI/automation compatibility"
      echo "  --tools-only       Only install CLI tools globally"
      echo "  --agents-only      Only install agent definitions"
      echo "  -h, --help         Show this help"
      exit 0
      ;;
    *) err "Unknown option: $arg"; exit 1 ;;
  esac
done

step "Checking prerequisites"

if command -v python3 >/dev/null 2>&1; then
  PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
  PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
  if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_MINOR" -lt 12 ]; then
    err "Python >= 3.12 required (found ${PY_VER})"
    exit 1
  fi
  info "Python ${PY_VER} found"
else
  err "python3 not found. Install Python >= 3.12"
  exit 1
fi

if command -v uv >/dev/null 2>&1; then
  info "uv $(uv --version 2>/dev/null | head -1) found"
else
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  if ! command -v uv >/dev/null 2>&1; then
    err "uv installation failed"
    exit 1
  fi
  info "uv $(uv --version 2>/dev/null | head -1) installed"
fi

run_cli() {
  (cd "$REPO_DIR" && uv run studyctl "$@")
}

if $AGENTS_ONLY; then
  step "Installing agent definitions"
  run_cli install agents
  exit 0
fi

if ! $TOOLS_ONLY; then
  step "Syncing workspace"
  (cd "$REPO_DIR" && uv sync)
  info "Workspace synced"
fi

step "Installing CLI tools globally"
if $TOOLS_ONLY; then
  run_cli install tools
else
  run_cli install tools --skip-sync
fi
info "CLI tools installed"

if $TOOLS_ONLY; then
  echo ""
  printf "${BOLD}${GREEN}Tools installed!${NC}\n"
  exit 0
fi

step "Installing agent definitions"
run_cli install agents
info "Agent definitions installed"

echo ""
printf "${BOLD}${GREEN}Installation complete!${NC}\n"
echo ""

if command -v brew >/dev/null 2>&1; then
  echo "Homebrew detected. Preferred user install path:"
  echo "  brew install NetDevAutomate/studyctl/studyctl"
  echo ""
fi

if ! $NON_INTERACTIVE; then
  echo "Next steps:"
  echo "  1. Run 'studyctl setup' to create or update ~/.config/studyctl/config.yaml"
  echo "  2. Run 'studyctl doctor --fix' to apply safe post-install fixes"
  echo "  3. Start a study session with 'studyctl study \"Python\" --mode co-study'"
  echo "  4. Launch the web UI with 'studyctl web'"
fi
