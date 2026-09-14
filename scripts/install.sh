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

# Interpreters this installer will proceed with. 3.12 is the repo's
# .python-version pin and is installed through uv if it is missing; 3.13 and
# 3.14 are accepted when UV_PYTHON selects them, but 3.14 is checked only by
# the nightly install job, not this script.
SUPPORTED_PYTHONS=("3.12" "3.13" "3.14")

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

# A25: `uv python find` prints a resolved interpreter PATH, not a version, so
# the version has to be asked of that interpreter directly. This deliberately
# does not gate on a `python3` found on PATH: uv resolves and, if needed,
# downloads the interpreter .python-version pins (or UV_PYTHON overrides)
# regardless of what a bare `python3` on PATH happens to be.
#
# `uv python find` (unlike `uv sync`/`uv run`) does NOT treat UV_PYTHON as
# taking priority over an on-disk .python-version file -- once this repo's
# .python-version exists, a plain `uv python find` reports 3.12 even with
# UV_PYTHON=3.13 set, which would make this diagnostic lie about what
# `uv sync` is about to do. Passing UV_PYTHON as an explicit request
# argument makes `uv python find` agree with `uv sync`.
#
# `uv python find` only FINDS. On a machine with no interpreter matching the
# request (a fresh laptop with Homebrew's newest Python only), it fails where
# `uv sync` would have downloaded one. So a miss falls back to
# `uv python install <request>` -- the same managed download `uv sync` would
# perform, done here explicitly so the user sees it before the heavy
# dependency download starts.
py_request="${UV_PYTHON:-$(tr -d '[:space:]' < "$REPO_DIR/.python-version")}"
if ! py_path=$(cd "$REPO_DIR" && uv python find "$py_request" 2>/dev/null); then
  warn "No Python ${py_request} found locally — installing it with uv..."
  if ! (cd "$REPO_DIR" && uv python install "$py_request"); then
    err "Could not install Python ${py_request} with uv. Install it (e.g. 'uv python install ${py_request}') or set UV_PYTHON to an installed version, then rerun."
    exit 1
  fi
  py_path=$(cd "$REPO_DIR" && uv python find "$py_request")
fi
py_ver=$("$py_path" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

py_supported=false
for supported in "${SUPPORTED_PYTHONS[@]}"; do
  if [ "$py_ver" = "$supported" ]; then
    py_supported=true
  fi
done

if ! $py_supported; then
  err "Python ${py_ver} from ${py_path} is not supported (need one of: ${SUPPORTED_PYTHONS[*]}). Set UV_PYTHON to choose a supported version, e.g. UV_PYTHON=3.13 ./scripts/install.sh"
  exit 1
fi

info "uv will use Python ${py_ver} from ${py_path} (pinned by .python-version; override with UV_PYTHON=3.13)"

run_cli() {
  (cd "$REPO_DIR" && uv run studyloop "$@")
}

run_smoke_checks() {
  step "Running installed CLI smoke checks"
  studyloop --version
  studyloop --help >/dev/null
  session-export --help >/dev/null
  session-query --help >/dev/null
  command -v session-db-mcp >/dev/null

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

# A26: the interpreter uv resolved was reported before the install; report the
# one each tool venv actually received, so a workspace/tool mismatch is visible
# in this log instead of inferred later.
tool_dir=$(uv tool dir)
for tool in studyloop agent-session-tools; do
  tool_py="${tool_dir}/${tool}/bin/python"
  if [ -x "$tool_py" ]; then
    info "${tool} tool venv uses Python $("$tool_py" -c 'import sys; print(sys.version.split()[0])')"
  fi
done

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
  echo "  3. Build a study plan. This is what makes 'studyloop now' recommend the"
  echo "     right thing, so it is worth doing before your first session:"
  echo "       - Easiest: 'studyloop web', then the Study Plans tab. The create form"
  echo "         opens with a free-text box — describe your goal in your own words."
  echo "       - Or be interviewed: start the study-plan-architect agent with"
  echo "         'studyloop plan architect' (it reads your session history first)."
  echo "       - Or direct: studyloop plan new --title \"Data Engineering\" \\"
  echo "                      --why \"why this matters\" --topic \"SQL\" --topic \"Spark\""
  echo "  4. Start a study session with 'studyloop study \"Python\" --mode co-study'"
  echo "  5. Launch the web UI with 'studyloop web' — plans, flashcards, live sessions"
  echo ""
  echo "New here? 'docs/first-week.md' is a day-by-day path through the above."
fi
