#!/usr/bin/env bash
# install-agents.sh — Install Socratic Study Mentor agents for all supported AI tools
#
# Usage:
#   ./scripts/install-agents.sh              # Install all detected
#   ./scripts/install-agents.sh --kiro       # Kiro CLI only
#   ./scripts/install-agents.sh --claude     # Claude Code only
#   ./scripts/install-agents.sh --gemini     # Gemini CLI only
#   ./scripts/install-agents.sh --opencode   # OpenCode only
#   ./scripts/install-agents.sh --amp        # Amp only
#   ./scripts/install-agents.sh --uninstall
set -euo pipefail

# --- Colors ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { printf "${GREEN}✓${NC} %s\n" "$1"; }
warn()  { printf "${YELLOW}⚠${NC} %s\n" "$1"; }
err()   { printf "${RED}✗${NC} %s\n" "$1"; }

# --- Paths ---
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_DIR=$(dirname "$SCRIPT_DIR")
KIRO_HOME="${HOME}/.kiro"
CLAUDE_HOME="${HOME}/.claude"
GEMINI_HOME="${HOME}/.gemini"
OPENCODE_HOME="${HOME}/.config/opencode"
AMP_HOME="${HOME}/.config/amp"
# Shared agents path (cross-tool standard)
AGENTS_SHARED="${HOME}/.agents"

# --- Parse args ---
MODE="auto"
UNINSTALL=false
for arg in "$@"; do
  case "$arg" in
    --kiro)      MODE="kiro" ;;
    --claude)    MODE="claude" ;;
    --gemini)    MODE="gemini" ;;
    --opencode)  MODE="opencode" ;;
    --amp)       MODE="amp" ;;
    --uninstall) UNINSTALL=true ;;
    -h|--help)
      sed -n '2,11p' "$0"; exit 0 ;;
    *) err "Unknown option: $arg"; exit 1 ;;
  esac
done

# --- Helpers ---
backup_if_exists() {
  local target="$1"
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    mv "$target" "${target}.bak"
    warn "Backed up existing ${target} → ${target}.bak"
  fi
}

create_symlink() {
  local src="$1" target="$2"
  mkdir -p "$(dirname "$target")"
  if [ -L "$target" ]; then
    local current
    current=$(readlink "$target" 2>/dev/null || true)
    if [ "$current" = "$src" ]; then
      warn "Already linked: $target"; return 0
    fi
    rm "$target"
  fi
  backup_if_exists "$target"
  ln -s "$src" "$target"
  info "Linked: $target → $src"
}

remove_symlink() {
  local target="$1"
  if [ -L "$target" ]; then
    local current
    current=$(readlink "$target" 2>/dev/null || true)
    case "$current" in
      "${REPO_DIR}"*)
        rm "$target"
        info "Removed: $target"
        ;;
      *)
        warn "Skipped (not ours): $target"
        ;;
    esac
  fi
}

# --- Link definitions per platform ---

KIRO_LINKS=(
  "agents/kiro/study-mentor.json:${KIRO_HOME}/agents/study-mentor.json"
  "agents/kiro/study-mentor:${KIRO_HOME}/agents/study-mentor"
  "agents/kiro/skills/study-mentor:${KIRO_HOME}/skills/study-mentor"
  "agents/kiro/skills/audhd-socratic-mentor:${KIRO_HOME}/skills/audhd-socratic-mentor"
  "agents/kiro/skills/tutor-progress-tracker:${KIRO_HOME}/skills/tutor-progress-tracker"
  "agents/kiro/skills/study-speak:${KIRO_HOME}/skills/study-speak"
  "agents/mcp/study-speak-server.py:${KIRO_HOME}/agents/mcp/study-speak-server.py"
)

CLAUDE_LINKS=(
  "agents/claude/socratic-mentor.md:${CLAUDE_HOME}/agents/socratic-mentor.md"
  "agents/claude/mentor-reviewer.yaml:${CLAUDE_HOME}/agents/mentor-reviewer.yaml"
)

GEMINI_LINKS=(
  "agents/gemini/study-mentor.md:${GEMINI_HOME}/agents/study-mentor.md"
  "agents/gemini/GEMINI.md:${REPO_DIR}/GEMINI.md"
)

OPENCODE_LINKS=(
  "agents/opencode/study-mentor.md:${OPENCODE_HOME}/agents/study-mentor.md"
)

AMP_LINKS=(
  "agents/amp/AGENTS.md:${REPO_DIR}/AGENTS.md"
)

# Shared skills (cross-tool standard — works with Gemini, OpenCode, Amp)
SHARED_LINKS=(
  "agents/shared:${AGENTS_SHARED}/shared"
)

install_links() {
  local arr_name=$1
  local label="$2"
  echo ""
  echo "=== Installing ${label} agents ==="
  local count=0
  eval "local entries=(\"\${${arr_name}[@]}\")"
  for entry in "${entries[@]}"; do
    local src="${REPO_DIR}/${entry%%:*}"
    local target="${entry#*:}"
    if [ ! -e "$src" ]; then
      err "Source not found: $src"; continue
    fi
    create_symlink "$src" "$target" && ((count++)) || true
  done
  info "${label}: ${count} link(s) installed"
}

uninstall_links() {
  local arr_name=$1
  local label="$2"
  echo ""
  echo "=== Uninstalling ${label} agents ==="
  eval "local entries=(\"\${${arr_name}[@]}\")"
  for entry in "${entries[@]}"; do
    local target="${entry#*:}"
    remove_symlink "$target"
  done
  info "${label}: uninstall complete"
}

# --- Main ---
if $UNINSTALL; then
  [[ "$MODE" == "auto" || "$MODE" == "kiro" ]]     && uninstall_links KIRO_LINKS "kiro-cli"
  [[ "$MODE" == "auto" || "$MODE" == "claude" ]]    && uninstall_links CLAUDE_LINKS "Claude Code"
  [[ "$MODE" == "auto" || "$MODE" == "gemini" ]]    && uninstall_links GEMINI_LINKS "Gemini CLI"
  [[ "$MODE" == "auto" || "$MODE" == "opencode" ]]  && uninstall_links OPENCODE_LINKS "OpenCode"
  [[ "$MODE" == "auto" || "$MODE" == "amp" ]]       && uninstall_links AMP_LINKS "Amp"
  uninstall_links SHARED_LINKS "Shared"
  echo ""
  info "Uninstall complete."
  exit 0
fi

do_kiro=false; do_claude=false; do_gemini=false; do_opencode=false; do_amp=false

case "$MODE" in
  kiro)     do_kiro=true ;;
  claude)   do_claude=true ;;
  gemini)   do_gemini=true ;;
  opencode) do_opencode=true ;;
  amp)      do_amp=true ;;
  auto)
    [ -d "$KIRO_HOME" ]     && do_kiro=true     || warn "kiro-cli not detected (~/.kiro/ missing)"
    [ -d "$CLAUDE_HOME" ]   && do_claude=true    || warn "Claude Code not detected (~/.claude/ missing)"
    [ -d "$GEMINI_HOME" ]   && do_gemini=true    || warn "Gemini CLI not detected (~/.gemini/ missing)"
    command -v opencode &>/dev/null && do_opencode=true || warn "OpenCode not detected"
    command -v amp &>/dev/null      && do_amp=true      || warn "Amp not detected"
    ;;
esac

# Always install shared docs
install_links SHARED_LINKS "Shared"

$do_kiro     && install_links KIRO_LINKS "kiro-cli"
$do_claude   && install_links CLAUDE_LINKS "Claude Code"
$do_gemini   && install_links GEMINI_LINKS "Gemini CLI"
$do_opencode && install_links OPENCODE_LINKS "OpenCode"
$do_amp      && install_links AMP_LINKS "Amp"

# --- Claude Code status line ---
if $do_claude; then
  echo ""
  echo "=== Installing Claude Code status line ==="
  cp "${REPO_DIR}/agents/claude/study-statusline.sh" "${CLAUDE_HOME}/study-statusline.sh"
  chmod 755 "${CLAUDE_HOME}/study-statusline.sh"
  info "Installed: ${CLAUDE_HOME}/study-statusline.sh"

  if [ -f "${CLAUDE_HOME}/settings.json" ]; then
    warn "Existing ${CLAUDE_HOME}/settings.json found — add manually:"
    echo '  "statusLine": { "type": "command", "command": "~/.claude/study-statusline.sh" }'
  else
    cp "${REPO_DIR}/agents/claude/settings.json" "${CLAUDE_HOME}/settings.json"
    info "Installed: ${CLAUDE_HOME}/settings.json"
  fi

  echo ""
  info "Status line shows: energy level, pomodoro phase, context usage, cost"
  info "State file: ~/.config/studyctl/session-state.json"
fi

# --- Gemini CLI settings ---
if $do_gemini; then
  GEMINI_SETTINGS="${GEMINI_HOME}/settings.json"
  if [ -f "$GEMINI_SETTINGS" ]; then
    if ! grep -q '"enableAgents"' "$GEMINI_SETTINGS" 2>/dev/null; then
      warn "Add to ${GEMINI_SETTINGS}: { \"experimental\": { \"enableAgents\": true } }"
    fi
  else
    mkdir -p "$GEMINI_HOME"
    cat > "$GEMINI_SETTINGS" << 'EOF'
{
  "experimental": {
    "enableAgents": true
  }
}
EOF
    info "Created: ${GEMINI_SETTINGS} (subagents enabled)"
  fi
fi

if ! $do_kiro && ! $do_claude && ! $do_gemini && ! $do_opencode && ! $do_amp; then
  err "No AI tools detected. Install kiro-cli, Claude Code, Gemini CLI, OpenCode, or Amp first."
  exit 1
fi

echo ""
info "Agent installation complete!"
echo ""
echo "Installed for:"
$do_kiro     && echo "  • kiro-cli    — select 'study-mentor' agent"
$do_claude   && echo "  • Claude Code — /agent socratic-mentor"
$do_gemini   && echo "  • Gemini CLI  — study-mentor subagent (auto-detected)"
$do_opencode && echo "  • OpenCode    — Tab to switch to study-mentor"
$do_amp      && echo "  • Amp         — AGENTS.md loaded automatically"
echo ""
echo "Shared framework: ${AGENTS_SHARED}/shared/"
