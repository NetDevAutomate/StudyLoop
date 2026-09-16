## Grok Build (`grok`) — live items in real-harness-auth mode

- binary: `/Users/ataylor/.local/bin/grok` — `--version` → `grok 1.0.30 (04b7ffed98c6)`
- recorded: 2026-09-16T00:30:52+00:00 on macOS-27.0-arm64-arm-64bit; repo `f0edce6a` (dirty=True)
- scratch root: `/tmp/sl-ev-grok-0_l_9ity` (swept: True)

| # | Item | Verdict | Decisive line |
| --- | --- | --- | --- |
| 2+4-live-lane | live-lane | **PASS** | pytest exit 0: 1 passed, 5 deselected in 20.48s; bundle outcome(s)=['completed']; turn audit=[{'turns': 3, 'turns_with_no_model_marker': 0, 'turns_over_1s': 1, 'real_model_reply_plausible': False}] |
| 3-export | export | **PASS** | live transcript exported: 2 sessions row(s) from THIS run with source='grok' (4 messages); rows by source={'grok': 8} |
| 5-plan-architect | plan-architect | **PASS** | persona_file=/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloop/sessions/study-plan-architect-evide-cd789f61/AGENTS.md plan-architect=True agent_in_pane=True final_mode=ended |

### grok — item 2+4-live-lane — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest -m acceptance packages/studyloop/tests/acceptance/test_harness_matrix_live.py -k [grok] -q -rA -p no:cacheprovider --basetemp=/tmp/sl-lane-grok-tihya5ya` → exit `0` (20.84s)

stdout:
```text
.                                                                        [100%]
==================================== PASSES ====================================
=========================== short test summary info ============================
PASSED packages/studyloop/tests/acceptance/test_harness_matrix_live.py::TestHarnessMatrixLive::test_cli_tmux_lane_completes_a_full_scripted_lifecycle[grok]
1 passed, 5 deselected in 20.48s
```

details:
```json
{
  "turn_audit": [
    {
      "turns": 3,
      "turns_with_no_model_marker": 0,
      "turns_over_1s": 1,
      "real_model_reply_plausible": false
    }
  ],
  "real_auth": true,
  "actor_requested": "gateway",
  "note": "The matrix lane drives the LEARNER side with its own 3 scripted prompts and records actor='scripted' in its bundle regardless of STUDYLOOP_ACC_ACTOR; the actor value is validated by the gate but does not add gateway spend to this lane."
}
```

### grok — item 3-export — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Export Evidence: grok --energy 5 --agent grok` → exit `1` (2.63s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.15s)

stdout:
```text
Session ended: Export Evidence: grok
  tmux session closed.
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m agent_session_tools.export_sessions --grok-only -o /tmp/sl-ev-grok-real-i9_6_axd/home/evidence-sessions.db` → exit `0` (0.56s)

stdout:
```text
Exporting to: /tmp/sl-ev-grok-real-i9_6_axd/home/evidence-sessions.db
Applied 48 database migration(s)

Export results:
  added:   8
  updated: 0
  skipped: 0 (unchanged since last export)
  empty:   2 (no supported conversation or native records)

Database stats:
  grok: 8 sessions, 97 messages
semantic index not built: sqlite-vec is not installed; install: uv tool install 'agent-session-tools[semantic]'; run session-maint embed
```

details:
```json
{
  "launch": {
    "state_file_appeared": true,
    "state_after_launch": {
      "session_dir": "/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloop/sessions/study-export-evidence-grok-69ca4791",
      "mode": "study",
      "topic": "Export Evidence: grok",
      "agent": "grok",
      "tmux_session": "study-export-evidence-grok-69ca4791",
      "tmux_main_pane": "%0",
      "persona_file": "/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloop/sessions/study-export-evidence-grok-69ca4791/AGENTS.md",
      "persona_hash": "493a1f…",
      "session_mode": null,
      "energy": 5
    },
    "tmux_session_exists": true,
    "agent_process_in_pane": true,
    "tui_rendered": true,
    "pane_after_settle": "\n  /private/tmp/sl-ev-grok-real-i9_6_axd/home/.config/stu\u2026\n\n\n\n       Do you trust the contents of this directory?\n/private/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloo\n\n Grok Build may run or modify contents in this directory,\n                  posing security risks.\n\n               Yes, proceed                 y\n               No, quit                     n\n\n\n\n\n\n\n\n\n\n                              Grok Build  1.0.30 [stable]\n\n",
    "reply_wait_seconds": 30.1,
    "pane_quiescent": true,
    "pane_after_prompt": "",
    "tmux_session_gone_after_end": true,
    "final_mode": "ended"
  },
  "scratch_harness_dirs_after_session": {
    "(real harness home: not listed)": []
  },
  "export_db": "/tmp/sl-ev-grok-real-i9_6_axd/home/evidence-sessions.db",
  "rows_by_source": {
    "grok": 8
  },
  "session_dir": "/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloop/sessions/study-export-evidence-grok-69ca4791",
  "rows_for_this_run": [
    {
      "id": "grok_01a0a79d-5553-7b53-8b14-9c1e9a26108d",
      "source": "grok",
      "project_path": "/private/tmp/sl-lane-grok-4ucwi8ov/test_cli_tmux_lane_completes_a0/home/.config/studyloop/sessions/study-harness-matrix-live--28e3935b",
      "created_at": "2026-09-16T00:28:21.218004Z",
      "messages": 2
    },
    {
      "id": "grok_01a0a79f-d120-7d51-b536-e6b64bad5c4f",
      "source": "grok",
      "project_path": "/private/tmp/sl-lane-grok-tihya5ya/test_cli_tmux_lane_completes_a0/home/.config/studyloop/sessions/study-harness-matrix-live--8e73ee0c",
      "created_at": "2026-09-16T00:31:03.980961Z",
      "messages": 2
    }
  ]
}
```

### grok — item 5-plan-architect — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Plan Architect Evidence: grok --energy 5 --agent grok --mode plan-architect` → exit `1` (2.71s)

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
    "session_dir": "/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloop/sessions/study-plan-architect-evide-cd789f61",
    "mode": "plan-architect",
    "topic": "Plan Architect Evidence: grok",
    "agent": "grok",
    "tmux_session": "study-plan-architect-evide-cd789f61",
    "tmux_main_pane": "%0",
    "persona_file": "/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloop/sessions/study-plan-architect-evide-cd789f61/AGENTS.md",
    "persona_hash": "37726c…",
    "session_mode": null,
    "energy": 5
  },
  "tmux_session_exists": true,
  "agent_process_in_pane": true,
  "tui_rendered": true,
  "pane_after_settle": "\n  /private/tmp/sl-ev-grok-real-i9_6_axd/home/.config/stu\u2026\n\n\n\n       Do you trust the contents of this directory?\n/private/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloo\n\n Grok Build may run or modify contents in this directory,\n                  posing security risks.\n\n               Yes, proceed                 y\n               No, quit                     n\n\n\n\n\n\n\n\n\n\n                              Grok Build  1.0.30 [stable]\n\n",
  "persona_file": "/tmp/sl-ev-grok-real-i9_6_axd/home/.config/studyloop/sessions/study-plan-architect-evide-cd789f61/AGENTS.md",
  "persona_first_lines": "# Study Session Context\n\n**Topic:** Plan Architect Evidence: grok",
  "persona_mentions_plan_architect": true,
  "persona_bytes": 7246,
  "tmux_session_gone_after_end": true,
  "final_mode": "ended"
}
```
