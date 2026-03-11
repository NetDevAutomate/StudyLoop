#!/usr/bin/env bash
# install.sh — Install Socratic Study Mentor
#
# Usage:
#   ./scripts/install.sh                # Full install (interactive)
#   ./scripts/install.sh --non-interactive  # Full install (no prompts — for Ansible/CI)
#   ./scripts/install.sh --tools-only   # Just install CLI tools globally
#   ./scripts/install.sh --agents-only  # Just install agent definitions
#
# After cloning the repo, this is the only script you need to run.
# For Ansible: clone the repo, then run ./scripts/install.sh --non-interactive
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$1"; }
err()   { printf "${RED}✗${NC} %s\n" "$1"; }
step()  { printf "\n${BOLD}▸ %s${NC}\n" "$1"; }

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(dirname "$SCRIPT_DIR")

# --- Parse flags ---
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
      echo "  --non-interactive  Skip all prompts (for Ansible/CI)"
      echo "  --tools-only       Only install CLI tools globally"
      echo "  --agents-only      Only install agent definitions"
      echo "  -h, --help         Show this help"
      exit 0
      ;;
    *) err "Unknown option: $arg"; exit 1 ;;
  esac
done

# --- Shortcut: agents only ---
if $AGENTS_ONLY; then
  step "Installing agent definitions"
  bash "${SCRIPT_DIR}/install-agents.sh"
  exit 0
fi

# --- Prerequisites ---
step "Checking prerequisites"

# Python >= 3.10
if command -v python3 &>/dev/null; then
  PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
  PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
  PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)
  if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
    info "Python ${PY_VER} found"
  else
    err "Python >= 3.10 required (found ${PY_VER})"
    exit 1
  fi
else
  err "python3 not found. Install Python >= 3.10"
  exit 1
fi

# uv
if command -v uv &>/dev/null; then
  info "uv $(uv --version 2>/dev/null | head -1) found"
else
  warn "uv not found — installing..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  if command -v uv &>/dev/null; then
    info "uv $(uv --version 2>/dev/null | head -1) installed"
  else
    err "uv installation failed"
    exit 1
  fi
fi

# --- Install packages ---
if ! $TOOLS_ONLY; then
  step "Installing Python packages"
  cd "$REPO_DIR"
  uv sync
  info "Packages installed"
fi

# --- Install CLI tools globally ---
step "Installing CLI tools globally"
for pkg in "${REPO_DIR}"/packages/*/; do
  pkg_name=$(basename "$pkg")
  uv tool install "$pkg" --editable --force 2>&1 | while read -r line; do
    echo "  $line"
  done
done
info "CLI tools installed (studyctl, session-export, session-query, session-sync, session-maint, tutor-checkpoint, study-speak)"

# --- Shortcut: tools only ---
if $TOOLS_ONLY; then
  echo ""
  printf "${BOLD}${GREEN}Tools installed!${NC}\n"
  uv tool list 2>/dev/null | grep -E "^(studyctl|agent-session-tools)" | sed 's/^/  /'
  exit 0
fi

# --- Install agents ---
step "Installing agent definitions"
bash "${SCRIPT_DIR}/install-agents.sh"

# --- Config ---
step "Checking configuration"
CONFIG_DIR="${HOME}/.config/studyctl"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
if [ -f "$CONFIG_FILE" ]; then
  if grep -q '^topics:' "$CONFIG_FILE" 2>/dev/null; then
    info "Config exists: ${CONFIG_FILE}"
  else
    warn "Config exists but has no 'topics' section: ${CONFIG_FILE}"
    echo "  Adding study topics template..."
    cat >> "$CONFIG_FILE" <<'EOF'

# Study topics (added by install.sh)
# Uncomment and customise for your learning goals
topics: []
#  - name: Python
#    slug: python
#    obsidian_path: 2-Areas/Study/Python
#    tags: [python, programming]
#  - name: SQL
#    slug: sql
#    obsidian_path: 2-Areas/Study/SQL
#    tags: [sql, databases]
#  - name: Data Engineering
#    slug: data-engineering
#    obsidian_path: 2-Areas/Study/Data-Engineering
#    tags: [data-engineering, spark, glue]
EOF
    info "Topics template appended to ${CONFIG_FILE}"
  fi
else
  if command -v studyctl &>/dev/null && ! $NON_INTERACTIVE; then
    studyctl config init 2>/dev/null && info "Config created via studyctl" || true
  fi
  if [ ! -f "$CONFIG_FILE" ]; then
    mkdir -p "$CONFIG_DIR"
    cat > "$CONFIG_FILE" <<'EOF'
# Socratic Study Mentor configuration
# See docs/setup-guide.md for details

topics: []
#  - name: Python
#    schedule: daily
#  - name: Data Engineering
#    schedule: weekly

notes_dir: ~/Obsidian/Personal/2-Areas/Study
EOF
    info "Default config created: ${CONFIG_FILE}"
  fi
fi

# --- Optional: Voice model ---
KOKORO_DIR="${HOME}/.cache/kokoro-onnx"
KOKORO_MODEL="${KOKORO_DIR}/kokoro-v1.0.onnx"
KOKORO_VOICES="${KOKORO_DIR}/voices-v1.0.bin"
KOKORO_BASE="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

if [ -f "$KOKORO_MODEL" ] && [ -f "$KOKORO_VOICES" ]; then
  info "Voice model already downloaded"
elif $NON_INTERACTIVE; then
  info "Skipped voice model download (non-interactive mode)"
else
  echo ""
  printf "${BOLD}▸ Voice output (optional)${NC}\n"
  echo "  The study mentor can speak questions aloud using kokoro-onnx TTS (~85MB download)."
  printf "  Download voice model now? [y/N] "
  read -r REPLY
  if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    mkdir -p "$KOKORO_DIR"
    for name in kokoro-v1.0.onnx voices-v1.0.bin; do
      if [ ! -f "${KOKORO_DIR}/${name}" ]; then
        echo "  Downloading ${name}..."
        curl -fsSL "${KOKORO_BASE}/${name}" -o "${KOKORO_DIR}/${name}" || {
          err "Failed to download ${name}"
          rm -f "${KOKORO_DIR}/${name}"
        }
      fi
    done
    if [ -f "$KOKORO_MODEL" ] && [ -f "$KOKORO_VOICES" ]; then
      info "Voice model downloaded to ${KOKORO_DIR}"
    fi
  else
    info "Skipped — models will download on first use of study-speak"
  fi
fi

# --- Summary ---
echo ""
printf "${BOLD}${GREEN}Installation complete!${NC}\n"
echo ""
echo "Next steps:"
echo "  1. Run 'studyctl config init' to configure your study environment"
echo "  2. Start a study session:"
echo "     • kiro-cli: select the 'study-mentor' agent"
echo "     • Claude Code: /agent socratic-mentor"
echo "     • Amp: just start amp in the project directory"
echo "  3. See docs/setup-guide.md for detailed instructions"
