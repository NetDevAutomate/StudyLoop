#!/usr/bin/env bash
# Thin bootstrap wrapper for studyloop source installs.
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
NO_SMOKE=false

for arg in "$@"; do
  case "$arg" in
    --tools-only)      TOOLS_ONLY=true ;;
    --agents-only)     AGENTS_ONLY=true ;;
    --non-interactive) NON_INTERACTIVE=true ;;
    --no-smoke)        NO_SMOKE=true ;;
    --help|-h)
      echo "Usage: ./scripts/install.sh [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --non-interactive  Accepted for CI/automation compatibility"
      echo "  --tools-only       Only install CLI tools globally"
      echo "  --agents-only      Only install agent definitions"
      echo "  --no-smoke         Skip installed CLI smoke checks"
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

export PATH="$HOME/.local/bin:$PATH"

run_cli() {
  (cd "$REPO_DIR" && uv run studyloop "$@")
}

run_smoke_checks() {
  step "Running installed CLI smoke checks"
  studyloop --version
  studyloop --help >/dev/null
  session-export --help >/dev/null

  set +e
  self_test_json=$(studyloop self-test --json)
  self_test_status=$?
  set -e

  case "$self_test_status" in
    0|1) ;;
    *)
      err "studyloop self-test --json failed with unexpected status ${self_test_status}"
      exit "$self_test_status"
      ;;
  esac

  if ! printf '%s' "$self_test_json" | python3 -m json.tool >/dev/null; then
    err "studyloop self-test --json did not emit valid JSON"
    exit 1
  fi

  set +e
  doctor_json=$(studyloop doctor --json)
  doctor_status=$?
  set -e

  case "$doctor_status" in
    0|1|2) ;;
    *)
      err "studyloop doctor --json failed with unexpected status ${doctor_status}"
      exit "$doctor_status"
      ;;
  esac

  if ! printf '%s' "$doctor_json" | python3 -m json.tool >/dev/null; then
    err "studyloop doctor --json did not emit valid JSON"
    exit 1
  fi
  info "Installed CLI smoke checks passed"
}

if $AGENTS_ONLY; then
  step "Installing agent definitions"
  run_cli install agents
  exit 0
fi

if ! $TOOLS_ONLY; then
  step "Syncing workspace"
  (cd "$REPO_DIR" && uv sync --all-packages)
  info "Workspace synced"
fi

step "Installing CLI tools globally"
if $TOOLS_ONLY; then
  run_cli install tools
else
  run_cli install tools --skip-sync
fi
info "CLI tools installed"

if ! $NO_SMOKE; then
  run_smoke_checks
fi

if $TOOLS_ONLY; then
  echo ""
  printf '%b\n' "${BOLD}${GREEN}Tools installed!${NC}"
  exit 0
fi

step "Installing agent definitions"
run_cli install agents
info "Agent definitions installed"

echo ""
printf '%b\n' "${BOLD}${GREEN}Installation complete!${NC}"
echo ""

if ! $NON_INTERACTIVE; then
  echo "Next steps:"
  echo "  1. Run 'studyloop setup' to create or update ~/.config/studyloop/config.yaml"
  echo "  2. Run 'studyloop doctor --fix' to apply safe post-install fixes"
  echo "  3. Start a study session with 'studyloop study \"Python\" --mode co-study'"
  echo "  4. Launch the web UI with 'studyloop web'"
fi
