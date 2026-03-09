#!/usr/bin/env bash
# install.sh — Full installation of Socratic Study Mentor
#
# Usage:
#   ./scripts/install.sh
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
info()  { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$1"; }
err()   { printf "${RED}✗${NC} %s\n" "$1"; }
step()  { printf "\n${BOLD}▸ %s${NC}\n" "$1"; }

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(dirname "$SCRIPT_DIR")

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
step "Installing Python packages"
cd "$REPO_DIR"
uv sync
info "Packages installed"

# --- Install CLI tools globally ---
step "Installing CLI tools to ~/.local/bin"
uv tool install --force --from "${REPO_DIR}/packages/agent-session-tools" agent-session-tools
uv tool install --force --from "${REPO_DIR}/packages/studyctl" studyctl
info "CLI tools installed (session-export, session-query, session-sync, session-maint, tutor-checkpoint, studyctl)"

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
  if command -v studyctl &>/dev/null; then
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
echo "  1. Edit ${CONFIG_FILE} to configure your study topics"
echo "  2. Start a study session:"
echo "     • kiro-cli: select the 'study-mentor' agent"
echo "     • Claude Code: /agent socratic-mentor"
echo "  3. See docs/setup-guide.md for detailed instructions"
