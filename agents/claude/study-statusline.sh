#!/usr/bin/env bash
# study-statusline.sh — Claude Code status line for StudyLoop
# Shows: study topic, energy level, session timer, context usage, cost
#
# Claude Code pipes JSON to stdin with: model, cost, context_window, session_id, etc.
# We also read study session state from a state file.

set -euo pipefail

# Colors: real escape bytes, so the line is printed with printf '%s' and a
# backslash in the topic stays a backslash.
GREEN=$'\033[32m'
YELLOW=$'\033[33m'
RED=$'\033[31m'
CYAN=$'\033[36m'
DIM=$'\033[2m'
RESET=$'\033[0m'

# Every value shown below is data, never code (F-OPS-01): the topic is free
# text a user typed, and the stdin JSON is whatever Claude Code pipes in. One
# Python process reads both, normalises each field (numbers come back as
# numbers, text loses its control characters, NUL included) and writes the
# fields NUL-terminated; bash reads them with `read -r -d ''`. No value is
# ever parsed as shell code.
STATE_FILE="${HOME}/.config/studyloop/session-state.json"

# Defaults, kept when python3 is missing or its output is not all 6 fields.
CTX_PCT=0
CTX_INT=0
COST=0
DURATION_MIN=0
ENERGY="-"
TOPIC=""

# Single-quoted, so the shell expands nothing inside it: the Python uses
# double quotes only, and the state file path arrives as sys.argv[1].
# Keep it Python 3.9-compatible: that is macOS's /usr/bin/python3.
FIELDS_PY='
import json
import sys
import unicodedata


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if value != value or value in (float("inf"), float("-inf")):
        return 0
    return value


def text(value, default=""):
    if not isinstance(value, str):
        return default
    return "".join(ch for ch in value if unicodedata.category(ch) != "Cc")


def mapping(value):
    return value if isinstance(value, dict) else {}


def load(read):
    try:
        return mapping(json.loads(read()))
    except Exception:
        return {}


def read_state():
    with open(sys.argv[1], encoding="utf-8") as handle:
        return handle.read()


claude = load(sys.stdin.read)
state = load(read_state)
ctx = mapping(claude.get("context_window"))
cost = mapping(claude.get("cost"))

pct = number(ctx.get("used_percentage"))
fields = [
    format(pct, "g"),
    str(max(0, min(100, int(pct)))),
    format(number(cost.get("total_cost_usd")), ".4f"),
    str(int(number(cost.get("total_duration_ms"))) // 60000),
    text(state.get("energy_label"), "-"),
    text(state.get("topic")),
]
sys.stdout.write("".join(field + "\0" for field in fields))
'

if command -v python3 >/dev/null 2>&1; then
    FIELDS=()
    while IFS= read -r -d '' field; do
        FIELDS+=("$field")
    done < <(python3 -c "$FIELDS_PY" "$STATE_FILE" 2>/dev/null)
    if (( ${#FIELDS[@]} == 6 )); then
        CTX_PCT=${FIELDS[0]}
        CTX_INT=${FIELDS[1]}
        COST=${FIELDS[2]}
        DURATION_MIN=${FIELDS[3]}
        ENERGY=${FIELDS[4]}
        TOPIC=${FIELDS[5]}
    fi
fi

# CTX_INT feeds (( )) below, and bash arithmetic runs the command in an array
# subscript such as a[$(cmd)]: let only plain digits through.
case "$CTX_INT" in
    '' | *[!0-9]*) CTX_INT=0 ;;
esac

DURATION_DISPLAY="${DURATION_MIN}m"

# Energy emoji and color
case "$ENERGY" in
    high)   ENERGY_DISPLAY="${GREEN}🔋 High${RESET}" ;;
    medium) ENERGY_DISPLAY="${YELLOW}🔋 Med${RESET}" ;;
    low)    ENERGY_DISPLAY="${RED}🔋 Low${RESET}" ;;
    *)      ENERGY_DISPLAY="${DIM}🔋 -${RESET}" ;;
esac

# Context color
if (( CTX_INT > 80 )); then
    CTX_COLOR="$RED"
elif (( CTX_INT > 50 )); then
    CTX_COLOR="$YELLOW"
else
    CTX_COLOR="$GREEN"
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
PARTS+=("${DIM}⏱️ ${DURATION_DISPLAY}${RESET}")
PARTS+=("${CTX_COLOR}📊 ${CTX_PCT}%${RESET}")
PARTS+=("${DIM}\$${COST}${RESET}")

# Join with separator. An IFS join uses only IFS's first character (a space),
# so the │ never appeared; join explicitly instead.
LINE=""
SEP=""
for part in "${PARTS[@]}"; do
    LINE+="${SEP}${part}"
    SEP=" │ "
done
printf '%s\n' "$LINE"
