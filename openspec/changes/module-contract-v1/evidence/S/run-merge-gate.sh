#!/usr/bin/env bash
# S merge gate (design.md §7a): gate G's `just preflight` plus the full `just e2e`,
# run alone in the lane worktree. Full logs go to the per-user temp dir; the
# coordinator copies the summary lines into evidence/S/ after reading them.
set -uo pipefail
cd /Users/ataylor/code/personal/tools/studyloop-wt/module-schema || exit 99
export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"
unset VIRTUAL_ENV
LOGDIR="$TMPDIR/studyloop-s-gate"
mkdir -p "$LOGDIR"
echo "sha=$(git rev-parse --short HEAD) start=$(date -Iseconds)" > "$LOGDIR/status.txt"

just preflight > "$LOGDIR/preflight.log" 2>&1
echo "preflight_exit=$?" >> "$LOGDIR/status.txt"

just e2e -q > "$LOGDIR/e2e.log" 2>&1
echo "e2e_exit=$?" >> "$LOGDIR/status.txt"

echo "end=$(date -Iseconds)" >> "$LOGDIR/status.txt"
echo DONE >> "$LOGDIR/status.txt"
