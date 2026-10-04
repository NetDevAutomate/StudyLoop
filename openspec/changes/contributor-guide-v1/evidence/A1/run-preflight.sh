#!/usr/bin/env bash
# A1 gate: full preflight on the assembled guide, run alone, detached.
set -uo pipefail
cd /Users/ataylor/code/personal/tools/studyloop-wt/contributor-guide || exit 99
export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"; unset VIRTUAL_ENV
L="$TMPDIR/studyloop-a1-gate"; mkdir -p "$L"
echo "sha=$(git rev-parse --short HEAD) start=$(date -Iseconds)" > "$L/status.txt"
just preflight > "$L/preflight.log" 2>&1; echo "preflight_exit=$?" >> "$L/status.txt"
echo "end=$(date -Iseconds)" >> "$L/status.txt"; echo DONE >> "$L/status.txt"
