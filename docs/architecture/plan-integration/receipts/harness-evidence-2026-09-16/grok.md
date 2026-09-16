## Grok Build (`grok`) — live items in scrubbed scratch mode

- binary: `/Users/ataylor/.local/bin/grok` — `--version` → `grok 1.0.30 (04b7ffed98c6)`
- recorded: 2026-09-16T00:18:44+00:00 on macOS-27.0-arm64-arm-64bit; repo `fe7534d6` (dirty=True)
- scratch root: `/tmp/sl-ev-grok-bm3c5sqs` (swept: True)

| # | Item | Verdict | Decisive line |
| --- | --- | --- | --- |
| 1-install-doctor | install-doctor | **PASS** | install exit 0; 38 entries now under scratch harness dirs |
| 2+4-live-lane | live-lane | **FAIL** | pytest exit 1: 1 failed, 5 deselected in 60.26s (0:01:00); bundle outcome(s)=['errored']; turn audit=[{'turns': 2, 'turns_with_no_model_marker': 0, 'turns_over_1s': 0, 'real_model_reply_plausible': False}] |
| 5-plan-architect | plan-architect | **PASS** | persona_file=/tmp/sl-ev-grok-bm3c5sqs/home/.config/studyloop/sessions/study-plan-architect-evide-1e28449c/AGENTS.md plan-architect=True agent_in_pane=True final_mode=ended |

### grok — item 1-install-doctor — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli install agents --repo-root /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier --tool grok` → exit `0` (0.36s)

stdout:
```text
Updated agent definitions.
  shared: 3
  grok: 4
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli doctor --json` → exit `1` (1.28s)

stdout:
```text
<58 checks; parsed>
```

details:
```json
{
  "scratch_harness_dirs_after_install": {
    ".grok": [
      "F active_sessions.json",
      "F active_sessions.lock",
      "F config.toml",
      "D docs",
      "D docs/user-guide",
      "F docs/user-guide/01-getting-started.md",
      "F docs/user-guide/02-authentication.md",
      "F docs/user-guide/03-keyboard-shortcuts.md",
      "F docs/user-guide/04-slash-commands.md",
      "F docs/user-guide/05-configuration.md",
      "F docs/user-guide/06-theming.md",
      "F docs/user-guide/07-mcp-servers.md",
      "F docs/user-guide/08-skills.md",
      "F docs/user-guide/09-plugins.md",
      "F docs/user-guide/10-hooks.md",
      "F docs/user-guide/11-custom-models.md",
      "F docs/user-guide/12-project-rules.md",
      "F docs/user-guide/13-memory.md",
      "F docs/user-guide/14-headless-mode.md",
      "F docs/user-guide/15-agent-mode.md",
      "F docs/user-guide/16-subagents.md",
      "F docs/user-guide/17-sessions.md",
      "F docs/user-guide/18-sandbox.md",
      "F docs/user-guide/19-plan-mode.md",
      "F docs/user-guide/20-background-tasks.md",
      "F docs/user-guide/21-terminal-support.md",
      "F docs/user-guide/22-permissions-and-safety.md",
      "F docs/user-guide/23-dashboard.md",
      "F docs/user-guide/24-monitoring-usage.md",
      "F docs/user-guide/25-status-line.md",
      "F docs/user-guide/26-config-reference.md",
      "F docs/user-guide/27-grok-clone.md",
      "D hooks",
      "F hooks/studyloop.json",
      "D logs",
      "F logs/unified.jsonl",
      "D rules",
      "F rules/session-db.md"
    ]
  },
  "doctor_parsed": true,
  "doctor_status_totals": {
    "pass": 31,
    "warn": 21,
    "info": 5,
    "fail": 1
  },
  "doctor_checks_naming_harness": [
    {
      "category": "agents",
      "name": "agent_grok",
      "status": "info",
      "message": "No manifest entry for grok",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "smoke_grok",
      "status": "pass",
      "message": "grok responds (grok 1.0.30 (04b7ffed98c6))",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "mcp_grok",
      "status": "pass",
      "message": "grok has session-db and studyloop MCP servers registered via /tmp/sl-ev-grok-bm3c5sqs/home/.grok/config.toml",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "session_memory_skill_grok",
      "status": "pass",
      "message": "grok: session-memory query skill installed",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "export_mandate_grok",
      "status": "pass",
      "message": "grok: session-export mandate present in session-db.md",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "session_export_hook_grok",
      "status": "pass",
      "message": "grok: automatic SessionEnd export hook installed",
      "fix_hint": "",
      "fix_auto": false
    }
  ]
}
```

### grok — item 2+4-live-lane — FAIL

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest -m acceptance packages/studyloop/tests/acceptance/test_harness_matrix_live.py -k [grok] -q -rA -p no:cacheprovider --basetemp=/tmp/sl-lane-grok-4gwngsxw` → exit `1` (60.58s)

stdout:
```text
F                                                                        [100%]
=================================== FAILURES ===================================
_ TestHarnessMatrixLive.test_cli_tmux_lane_completes_a_full_scripted_lifecycle[grok] _
packages/studyloop/tests/acceptance/test_harness_matrix_live.py:281: in test_cli_tmux_lane_completes_a_full_scripted_lifecycle
    driver.send_turn(turn.prompt)
packages/studyloop/tests/harness/drive.py:100: in send_turn
    self.tmux.wait_for(
packages/studyloop/tests/harness/tmux.py:63: in wait_for
    time.sleep(interval)
E   Failed: Timeout (>60.0s) from pytest-timeout.
=========================== short test summary info ============================
FAILED packages/studyloop/tests/acceptance/test_harness_matrix_live.py::TestHarnessMatrixLive::test_cli_tmux_lane_completes_a_full_scripted_lifecycle[grok]
1 failed, 5 deselected in 60.26s (0:01:00)
```

details:
```json
{
  "turn_audit": [
    {
      "turns": 2,
      "turns_with_no_model_marker": 0,
      "turns_over_1s": 0,
      "real_model_reply_plausible": false
    }
  ],
  "real_auth": false,
  "actor_requested": "gateway",
  "note": "The matrix lane drives the LEARNER side with its own 3 scripted prompts and records actor='scripted' in its bundle regardless of STUDYLOOP_ACC_ACTOR; the actor value is validated by the gate but does not add gateway spend to this lane."
}
```

### grok — item 5-plan-architect — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Plan Architect Evidence: grok --energy 5 --agent grok --mode plan-architect` → exit `1` (0.28s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.14s)

stdout:
```text
Session ended: Plan Architect Evidence: grok
  tmux session closed.
```

details:
```json
{
  "state_file_appeared": true,
  "state_after_launch": {
    "session_dir": "/tmp/sl-ev-grok-bm3c5sqs/home/.config/studyloop/sessions/study-plan-architect-evide-1e28449c",
    "mode": "plan-architect",
    "topic": "Plan Architect Evidence: grok",
    "agent": "grok",
    "tmux_session": "study-plan-architect-evide-1e28449c",
    "tmux_main_pane": "%0",
    "persona_file": "/tmp/sl-ev-grok-bm3c5sqs/home/.config/studyloop/sessions/study-plan-architect-evide-1e28449c/AGENTS.md",
    "persona_hash": "52f8d0…",
    "session_mode": null,
    "energy": 5
  },
  "tmux_session_exists": true,
  "agent_process_in_pane": true,
  "pane_after_settle": "\n  /private/tmp/sl-ev-grok-bm3c5sqs/home/.config/studyloo\u2026\n\n\n\n\n         Approve in your browser to finish signing\n                            in.\n\n                         S38J-6ZXB\n\n          Make sure your browser shows this code.\n\n          If it doesn't open, click here to copy.\n\n\n\n          Copying not working? Click here to show\n                         full URL.\n\n\n                       ctrl+q  quit\n\n\n",
  "persona_file": "/tmp/sl-ev-grok-bm3c5sqs/home/.config/studyloop/sessions/study-plan-architect-evide-1e28449c/AGENTS.md",
  "persona_first_lines": "# Study Session Context\n\n**Topic:** Plan Architect Evidence: grok",
  "persona_mentions_plan_architect": true,
  "persona_bytes": 7231,
  "tmux_session_gone_after_end": true,
  "final_mode": "ended"
}
```
