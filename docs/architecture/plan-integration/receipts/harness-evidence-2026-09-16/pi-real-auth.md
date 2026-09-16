## pi (`pi`) — live items in real-harness-auth mode

- binary: `/opt/homebrew/bin/pi` — `--version` → `0.65.0`
- recorded: 2026-09-16T00:07:24+00:00 on macOS-27.0-arm64-arm-64bit; repo `fe7534d6` (dirty=True)
- scratch root: `/tmp/sl-ev-pi-7n6b_vn6` (swept: True)

| # | Item | Verdict | Decisive line |
| --- | --- | --- | --- |
| 2+4-live-lane | live-lane | **PASS** | pytest exit 0: 1 passed, 5 deselected in 6.89s; bundle outcome(s)=['completed']; turn audit=[{'turns': 3, 'turns_with_no_model_marker': 0, 'turns_over_1s': 0, 'real_model_reply_plausible': False}] |
| 3-export | export | **PASS** | live transcript exported: 1 sessions row(s) for THIS session with source='pi'; rows by source={'pi': 4} |
| 5-plan-architect | plan-architect | **PASS** | persona_file=/tmp/sl-ev-pi-real-8al06q3c/home/.config/studyloop/sessions/study-plan-architect-evide-060774fb/AGENTS.md plan-architect=True agent_in_pane=True final_mode=ended |

### pi — item 2+4-live-lane — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest -m acceptance packages/studyloop/tests/acceptance/test_harness_matrix_live.py -k [pi] -q -rA -p no:cacheprovider --basetemp=/tmp/sl-lane-pi-0cchvi4f` → exit `0` (7.21s)

stdout:
```text
.                                                                        [100%]
==================================== PASSES ====================================
=========================== short test summary info ============================
PASSED packages/studyloop/tests/acceptance/test_harness_matrix_live.py::TestHarnessMatrixLive::test_cli_tmux_lane_completes_a_full_scripted_lifecycle[pi]
1 passed, 5 deselected in 6.89s
```

details:
```json
{
  "turn_audit": [
    {
      "turns": 3,
      "turns_with_no_model_marker": 0,
      "turns_over_1s": 0,
      "real_model_reply_plausible": false
    }
  ],
  "real_auth": true,
  "actor_requested": "gateway",
  "note": "The matrix lane drives the LEARNER side with its own 3 scripted prompts and records actor='scripted' in its bundle regardless of STUDYLOOP_ACC_ACTOR; the actor value is validated by the gate but does not add gateway spend to this lane."
}
```

### pi — item 3-export — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Export Evidence: pi --energy 5 --agent pi` → exit `1` (2.58s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.16s)

stdout:
```text
Session ended: Export Evidence: pi
  tmux session closed.
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m agent_session_tools.export_sessions --pi-only -o /tmp/sl-ev-pi-real-8al06q3c/home/evidence-sessions.db` → exit `0` (0.29s)

stdout:
```text
Exporting to: /tmp/sl-ev-pi-real-8al06q3c/home/evidence-sessions.db
Applied 48 database migration(s)

Export results:
  added:   4
  updated: 0
  skipped: 0 (unchanged since last export)
  empty:   0 (no supported conversation or native records)

Database stats:
  pi: 4 sessions, 172 messages
semantic index not built: sqlite-vec is not installed; install: uv tool install 'agent-session-tools[semantic]'; run session-maint embed
```

details:
```json
{
  "launch": {
    "state_file_appeared": true,
    "state_after_launch": {
      "session_dir": "/tmp/sl-ev-pi-real-8al06q3c/home/.config/studyloop/sessions/study-export-evidence-pi-a6626228",
      "mode": "study",
      "topic": "Export Evidence: pi",
      "agent": "pi",
      "tmux_session": "study-export-evidence-pi-a6626228",
      "tmux_main_pane": "%0",
      "persona_file": "/tmp/sl-ev-pi-real-8al06q3c/home/.config/studyloop/sessions/study-export-evidence-pi-a6626228/AGENTS.md",
      "persona_hash": "097a97…",
      "session_mode": null,
      "energy": 5
    },
    "tmux_session_exists": true,
    "agent_process_in_pane": true,
    "pane_after_settle": "    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/generate_command/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/resolve_parallel/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user)\n~/.pi/agent/skills/resolve_todo_parallel/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user)\n~/.pi/agent/skills/workflows:brainstorm/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user)\n~/.pi/agent/skills/workflows:compound/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/workflows:plan/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/workflows:review/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/workflows:work/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  ~/.agents/skills/studyloop-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n\n\n Warning: tmux extended-keys is off. Modified Enter keys\n may not work. Add `set -g extended-keys on` to\n ~/.tmux.conf and restart tmux.\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Update Available\n New version 0.73.1 is available. Run: npm install -g\n @mariozechner/pi-coding-agent\n Changelog:\n https://github.com/badlogic/pi-mono/blob/main/packages/co\n ding-agent/CHANGELOG.md\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Package Updates Available\n Package updates are available. Run pi update\n Packages:\n - context-mode\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n/private/tmp/sl-ev-pi-real-8al06q3c/home/.config/studylo...\n0.0%/1.0M (auto)   us.anthropic.claude-opus-4-6-v1 \u2022 medium\n",
    "reply_wait_seconds": 18.1,
    "pane_quiescent": true,
    "pane_after_prompt": "\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n\n\n Warning: tmux extended-keys is off. Modified Enter keys\n may not work. Add `set -g extended-keys on` to\n ~/.tmux.conf and restart tmux.\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Update Available\n New version 0.73.1 is available. Run: npm install -g\n @mariozechner/pi-coding-agent\n Changelog:\n https://github.com/badlogic/pi-mono/blob/main/packages/co\n ding-agent/CHANGELOG.md\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
```

### pi — item 5-plan-architect — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Plan Architect Evidence: pi --energy 5 --agent pi --mode plan-architect` → exit `1` (2.65s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.15s)

stdout:
```text
Session ended: Plan Architect Evidence: pi
  tmux session closed.
```

details:
```json
{
  "state_file_appeared": true,
  "state_after_launch": {
    "session_dir": "/tmp/sl-ev-pi-real-8al06q3c/home/.config/studyloop/sessions/study-plan-architect-evide-060774fb",
    "mode": "plan-architect",
    "topic": "Plan Architect Evidence: pi",
    "agent": "pi",
    "tmux_session": "study-plan-architect-evide-060774fb",
    "tmux_main_pane": "%0",
    "persona_file": "/tmp/sl-ev-pi-real-8al06q3c/home/.config/studyloop/sessions/study-plan-architect-evide-060774fb/AGENTS.md",
    "persona_hash": "46abbc…",
    "session_mode": null,
    "energy": 5
  },
  "tmux_session_exists": true,
  "agent_process_in_pane": true,
  "pane_after_settle": "    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/generate_command/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/resolve_parallel/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user)\n~/.pi/agent/skills/resolve_todo_parallel/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user)\n~/.pi/agent/skills/workflows:brainstorm/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user)\n~/.pi/agent/skills/workflows:compound/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/workflows:plan/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/workflows:review/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  auto (user) ~/.pi/agent/skills/workflows:work/SKILL.md\n    name contains invalid characters (must be lowercase\na-z, 0-9, hyphens only)\n  ~/.agents/skills/studyloop-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n\n\n Warning: tmux extended-keys is off. Modified Enter keys\n may not work. Add `set -g extended-keys on` to\n ~/.tmux.conf and restart tmux.\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Update Available\n New version 0.73.1 is available. Run: npm install -g\n @mariozechner/pi-coding-agent\n Changelog:\n https://github.com/badlogic/pi-mono/blob/main/packages/co\n ding-agent/CHANGELOG.md\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Package Updates Available\n Package updates are available. Run pi update\n Packages:\n - context-mode\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n/private/tmp/sl-ev-pi-real-8al06q3c/home/.config/studylo...\n0.0%/1.0M (auto)   us.anthropic.claude-opus-4-6-v1 \u2022 medium\n",
  "persona_file": "/tmp/sl-ev-pi-real-8al06q3c/home/.config/studyloop/sessions/study-plan-architect-evide-060774fb/AGENTS.md",
  "persona_first_lines": "# Study Session Context\n\n**Topic:** Plan Architect Evidence: pi",
  "persona_mentions_plan_architect": true,
  "persona_bytes": 7238,
  "tmux_session_gone_after_end": true,
  "final_mode": "ended"
}
```
