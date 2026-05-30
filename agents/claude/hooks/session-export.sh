#!/usr/bin/env bash
# StudyLoop session-export Stop hook.
# Persists the just-finished Claude Code session (conversation + struggle
# signals) into the shared sessions DB. Best-effort: never blocks or fails
# the session close.
session-export --claude-only >/dev/null 2>&1 || true
