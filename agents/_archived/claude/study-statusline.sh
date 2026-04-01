#!/usr/bin/env bash
# study-statusline.sh — Claude Code status line for Socratic Study Mentor
# Shows: energy level, session timer, pomodoro phase, context usage
#
# Claude Code pipes JSON to stdin with: model, cost, context_window, session_id, etc.
# We also read study session state from a state file.

set -euo pipefail

# Colors
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
CYAN='\033[36m'
DIM='\033[2m'
BOLD='\033[1m'
RESET='\033[0m'

# Read Claude Code JSON from stdin
if command -v python3 &>/dev/null; then
    read -r INPUT
    eval "$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    ctx = d.get('context_window', {})
    cost = d.get('cost', {})
    model = d.get('model', {}).get('display_name', '?')
    print(f'CTX_PCT={ctx.get(\"used_percentage\", 0)}')
    print(f'COST={cost.get(\"total_cost_usd\", 0):.4f}')
    print(f'DURATION_MS={cost.get(\"total_duration_ms\", 0)}')
    print(f'MODEL={model}')
except: pass
" 2>/dev/null)"
fi

# Defaults
CTX_PCT=${CTX_PCT:-0}
COST=${COST:-0}
DURATION_MS=${DURATION_MS:-0}
MODEL=${MODEL:-unknown}

# Read study session state file
STATE_FILE="${HOME}/.config/studyctl/session-state.json"
ENERGY="-"
POMO_PHASE="-"
POMO_REMAINING=""
TOPIC=""

if [[ -f "$STATE_FILE" ]] && command -v python3 &>/dev/null; then
    eval "$(python3 -c "
import json, sys
from pathlib import Path
from datetime import datetime, timezone
try:
    state = json.loads(Path('$STATE_FILE').read_text())
    print(f'ENERGY={state.get(\"energy\", \"-\")}')
    pomo = state.get('pomodoro', {})
    if pomo:
        print(f'POMO_PHASE={pomo.get(\"phase\", \"-\")}')
        remaining = pomo.get('remaining_min', 0)
        print(f'POMO_REMAINING={remaining}m')
    print(f'TOPIC={state.get(\"topic\", \"\")}')
except: pass
" 2>/dev/null)"
fi

# Format duration
DURATION_SEC=$((DURATION_MS / 1000))
DURATION_MIN=$((DURATION_SEC / 60))
DURATION_DISPLAY="${DURATION_MIN}m"

# Energy emoji and color
case "$ENERGY" in
    high)   ENERGY_DISPLAY="${GREEN}🔋 High${RESET}" ;;
    medium) ENERGY_DISPLAY="${YELLOW}🔋 Med${RESET}" ;;
    low)    ENERGY_DISPLAY="${RED}🔋 Low${RESET}" ;;
    *)      ENERGY_DISPLAY="${DIM}🔋 -${RESET}" ;;
esac

# Context color
CTX_INT=${CTX_PCT%.*}
if (( CTX_INT > 80 )); then
    CTX_COLOR="$RED"
elif (( CTX_INT > 50 )); then
    CTX_COLOR="$YELLOW"
else
    CTX_COLOR="$GREEN"
fi

# Pomodoro display
if [[ "$POMO_PHASE" != "-" && -n "$POMO_PHASE" ]]; then
    case "$POMO_PHASE" in
        review)    POMO_DISPLAY="🔄 Review ${POMO_REMAINING}" ;;
        focus)     POMO_DISPLAY="🍅 Focus ${POMO_REMAINING}" ;;
        summarise) POMO_DISPLAY="📝 Summary ${POMO_REMAINING}" ;;
        break)     POMO_DISPLAY="☕ Break ${POMO_REMAINING}" ;;
        *)         POMO_DISPLAY="" ;;
    esac
else
    POMO_DISPLAY=""
fi

# Topic display
TOPIC_DISPLAY=""
if [[ -n "$TOPIC" ]]; then
    TOPIC_DISPLAY="${CYAN}📚 ${TOPIC}${RESET}"
fi

# Build status line
PARTS=()
[[ -n "$TOPIC_DISPLAY" ]] && PARTS+=("$TOPIC_DISPLAY")
PARTS+=("$ENERGY_DISPLAY")
[[ -n "$POMO_DISPLAY" ]] && PARTS+=("$POMO_DISPLAY")
PARTS+=("${DIM}⏱️ ${DURATION_DISPLAY}${RESET}")
PARTS+=("${CTX_COLOR}📊 ${CTX_PCT}%${RESET}")
PARTS+=("${DIM}\$${COST}${RESET}")

# Join with separator
IFS=' │ '
echo -e "${PARTS[*]}"
