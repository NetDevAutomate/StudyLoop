#!/usr/bin/env bash
# StudyLoop session-export Stop hook.
# Persists the just-finished Claude Code session (conversation + struggle
# signals) into the shared sessions DB. Best-effort: never blocks or fails
# the session close.
#
# REFERENCE COPY -- no install path reads this file. installers.py's
# install_claude_stop_hook() writes this exact command inline into
# ~/.claude/settings.json via export_hook_command("--claude-only")
# (installers.py:200); this .sh is kept only so a reader can see the shape
# of the hook without opening installers.py. Keep it byte-identical to
# export_hook_command's output or it will mislead rather than document.
$HOME/.local/bin/session-export --claude-only >>$HOME/.config/studyloop/export-hook.log 2>&1 || { rc=$?; echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) session-export --claude-only FAILED exit=$rc" >>$HOME/.config/studyloop/export-hook.log; }
