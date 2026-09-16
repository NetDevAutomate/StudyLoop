## OpenCode (`opencode`) — live items in scrubbed scratch mode

- binary: `/opt/homebrew/bin/opencode` — `--version` → `1.18.30`
- recorded: 2026-09-16T00:08:46+00:00 on macOS-27.0-arm64-arm-64bit; repo `fe7534d6` (dirty=True)
- scratch root: `/tmp/sl-ev-opencode-uihfanwl` (swept: True)

| # | Item | Verdict | Decisive line |
| --- | --- | --- | --- |
| 1-install-doctor | install-doctor | **PASS** | install exit 0; 9 entries now under scratch harness dirs |
| 2+4-live-lane | live-lane | **PASS** | pytest exit 0: 1 passed, 5 deselected in 5.51s; bundle outcome(s)=['completed']; turn audit=[{'turns': 3, 'turns_with_no_model_marker': 0, 'turns_over_1s': 2, 'real_model_reply_plausible': False}] |
| 5-plan-architect | plan-architect | **PASS** | persona_file=/tmp/sl-ev-opencode-uihfanwl/home/.config/studyloop/sessions/study-plan-architect-evide-1931464d/.opencode/agents/study-mentor.md plan-architect=True agent_in_pane=True final_mode=ended |

### opencode — item 1-install-doctor — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli install agents --repo-root /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier --tool opencode` → exit `0` (0.09s)

stdout:
```text
Updated agent definitions.
  shared: 3
  opencode: 5
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli doctor --json` → exit `1` (1.06s)

stdout:
```text
<58 checks; parsed>
```

details:
```json
{
  "scratch_harness_dirs_after_install": {
    ".config/opencode": [
      "D agents",
      "L agents/study-mentor.md",
      "L agents/study-plan-architect.md",
      "F opencode.json",
      "D plugins",
      "L plugins/studyloop-session-export.js",
      "F session-db.md"
    ],
    ".local/share/opencode": [
      "D log",
      "D repos"
    ]
  },
  "doctor_parsed": true,
  "doctor_status_totals": {
    "pass": 34,
    "warn": 18,
    "info": 5,
    "fail": 1
  },
  "doctor_checks_naming_harness": [
    {
      "category": "core",
      "name": "config_file",
      "status": "pass",
      "message": "Config valid: /tmp/sl-ev-opencode-uihfanwl/home/.config/studyloop/config.yaml",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "database",
      "name": "review_db",
      "status": "warn",
      "message": "Review DB not found: /tmp/sl-ev-opencode-uihfanwl/home/.config/studyloop/sessions.db",
      "fix_hint": "studyloop review will create it on first use",
      "fix_auto": false
    },
    {
      "category": "database",
      "name": "sessions_db",
      "status": "warn",
      "message": "Sessions DB not found: /tmp/sl-ev-opencode-uihfanwl/home/.config/studyloop/sessions.db",
      "fix_hint": "Run any agent session tool to create it",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "agent_opencode_studyloop-session-export",
      "status": "pass",
      "message": "opencode studyloop-session-export agent definition current",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "agent_opencode",
      "status": "pass",
      "message": "opencode agent definition current",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "agent_opencode_study-plan-architect",
      "status": "pass",
      "message": "opencode study-plan-architect agent definition current",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "smoke_opencode",
      "status": "pass",
      "message": "opencode responds (1.18.30)",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "mcp_opencode",
      "status": "pass",
      "message": "opencode has session-db and studyloop MCP servers registered",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "exporter_schema",
      "status": "fail",
      "message": "pinned exporter /tmp/sl-ev-opencode-uihfanwl/home/.local/bin/session-export is missing; every export hook fails",
      "fix_hint": "studyloop install tools",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "session_memory_skill_opencode",
      "status": "pass",
      "message": "opencode: session-memory query skill installed",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "export_mandate_opencode",
      "status": "pass",
      "message": "opencode: session-export mandate present in session-db.md",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "session_export_hook_opencode",
      "status": "pass",
      "message": "opencode: automatic session-export hook installed",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "session_export_hook_codex",
      "status": "warn",
      "message": "codex: missing SessionEnd export hook in /tmp/sl-ev-opencode-uihfanwl/home/.codex/hooks.json",
      "fix_hint": "studyloop doctor --fix  (merges Codex SessionEnd hook)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "export_mandate_pi",
      "status": "warn",
      "message": "pi: no session-export mandate in /tmp/sl-ev-opencode-uihfanwl/home/.pi/agent/session-db.md \u2014 sessions/struggles won't be persisted to the session DB at session end",
      "fix_hint": "studyloop doctor --fix  (writes the session-export steering mandate)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "session_export_hook_pi",
      "status": "warn",
      "message": "pi: missing automatic session-export hook at /tmp/sl-ev-opencode-uihfanwl/home/.pi/agent/extensions/studyloop-session-export.ts",
      "fix_hint": "studyloop doctor --fix  (installs session-end hook)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "export_mandate_grok",
      "status": "warn",
      "message": "grok: no session-export mandate in /tmp/sl-ev-opencode-uihfanwl/home/.grok/rules/session-db.md \u2014 sessions/struggles won't be persisted to the session DB at session end",
      "fix_hint": "studyloop doctor --fix  (writes the session-export steering mandate)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "session_export_hook_grok",
      "status": "warn",
      "message": "grok: missing SessionEnd export hook in /tmp/sl-ev-opencode-uihfanwl/home/.grok/hooks/studyloop.json",
      "fix_hint": "studyloop doctor --fix  (writes Grok SessionEnd hook)",
      "fix_auto": true
    }
  ]
}
```

### opencode — item 2+4-live-lane — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest -m acceptance packages/studyloop/tests/acceptance/test_harness_matrix_live.py -k [opencode] -q -rA -p no:cacheprovider --basetemp=/tmp/sl-lane-opencode-4fidgny7` → exit `0` (5.81s)

stdout:
```text
.                                                                        [100%]
==================================== PASSES ====================================
=========================== short test summary info ============================
PASSED packages/studyloop/tests/acceptance/test_harness_matrix_live.py::TestHarnessMatrixLive::test_cli_tmux_lane_completes_a_full_scripted_lifecycle[opencode]
1 passed, 5 deselected in 5.51s
```

details:
```json
{
  "turn_audit": [
    {
      "turns": 3,
      "turns_with_no_model_marker": 0,
      "turns_over_1s": 2,
      "real_model_reply_plausible": false
    }
  ],
  "real_auth": false,
  "actor_requested": "gateway",
  "note": "The matrix lane drives the LEARNER side with its own 3 scripted prompts and records actor='scripted' in its bundle regardless of STUDYLOOP_ACC_ACTOR; the actor value is validated by the gate but does not add gateway spend to this lane."
}
```

### opencode — item 5-plan-architect — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Plan Architect Evidence: opencode --energy 5 --agent opencode --mode plan-architect` → exit `1` (0.28s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.14s)

stdout:
```text
Session ended: Plan Architect Evidence: opencode
  tmux session closed.
```

details:
```json
{
  "state_file_appeared": true,
  "state_after_launch": {
    "session_dir": "/tmp/sl-ev-opencode-uihfanwl/home/.config/studyloop/sessions/study-plan-architect-evide-1931464d",
    "mode": "plan-architect",
    "topic": "Plan Architect Evidence: opencode",
    "agent": "opencode",
    "tmux_session": "study-plan-architect-evide-1931464d",
    "tmux_main_pane": "%0",
    "persona_file": "/tmp/sl-ev-opencode-uihfanwl/home/.config/studyloop/sessions/study-plan-architect-evide-1931464d/.opencode/agents/study-mentor.md",
    "persona_hash": "abf45a…",
    "session_mode": null,
    "energy": 5
  },
  "tmux_session_exists": true,
  "agent_process_in_pane": true,
  "pane_after_settle": "\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n",
  "persona_file": "/tmp/sl-ev-opencode-uihfanwl/home/.config/studyloop/sessions/study-plan-architect-evide-1931464d/.opencode/agents/study-mentor.md",
  "persona_first_lines": "---\ndescription: \"AuDHD-aware Socratic study mentor\"\nmode: primary",
  "persona_mentions_plan_architect": true,
  "persona_bytes": 7433,
  "tmux_session_gone_after_end": true,
  "final_mode": "ended"
}
```
