## pi (`pi`)

- binary: `/opt/homebrew/bin/pi` — `--version` → `0.65.0`
- recorded: 2026-09-15T23:52:30+00:00 on macOS-27.0-arm64-arm-64bit; repo `37862de9` (dirty=True)
- scratch root: `/tmp/sl-ev-pi-g32vww82` (swept: True)

| # | Item | Verdict | Decisive line |
| --- | --- | --- | --- |
| 1-install-doctor | install-doctor | **PASS** | install exit 0; 5 entries now under scratch harness dirs |
| 2+4-live-lane | live-lane | **PASS** | pytest exit 0: 1 passed, 5 deselected in 1.61s; bundle outcome(s)=['completed'] |
| 3-export | export | **PASS-FIXTURE** | no live transcript under scratch (export exit 0, rows={}); exporter fixture tests passed: ============================== 40 passed in 1.75s ============================== |
| 5-plan-architect | plan-architect | **PASS** | persona_file=/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessions/study-plan-architect-evide-df07c5d0/AGENTS.md plan-architect=True agent_in_pane=True final_mode=ended |

### pi — item 1-install-doctor — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli install agents --repo-root /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier --tool pi` → exit `0` (0.09s)

stdout:
```text
Updated agent definitions.
  shared: 3
  pi: 3
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli doctor --json` → exit `1` (0.84s)

stdout:
```text
<58 checks; parsed>
```

details:
```json
{
  "scratch_harness_dirs_after_install": {
    ".pi": [
      "D agent",
      "L agent/AGENTS.md",
      "D agent/extensions",
      "L agent/extensions/studyloop-session-export.ts",
      "F agent/session-db.md"
    ]
  },
  "doctor_parsed": true,
  "doctor_status_totals": {
    "pass": 32,
    "warn": 20,
    "info": 5,
    "fail": 1
  },
  "doctor_checks_naming_harness": [
    {
      "category": "core",
      "name": "config_file",
      "status": "pass",
      "message": "Config valid: /tmp/sl-ev-pi-g32vww82/home/.config/studyloop/config.yaml",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "database",
      "name": "review_db",
      "status": "warn",
      "message": "Review DB not found: /tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessions.db",
      "fix_hint": "studyloop review will create it on first use",
      "fix_auto": false
    },
    {
      "category": "database",
      "name": "sessions_db",
      "status": "warn",
      "message": "Sessions DB not found: /tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessions.db",
      "fix_hint": "Run any agent session tool to create it",
      "fix_auto": false
    },
    {
      "category": "config",
      "name": "review_directories",
      "status": "info",
      "message": "No review topics configured",
      "fix_hint": "studyloop config init",
      "fix_auto": false
    },
    {
      "category": "deps",
      "name": "dep_fastapi",
      "status": "pass",
      "message": "FastAPI (web) installed",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "deps",
      "name": "query_encoder_artefact",
      "status": "info",
      "message": "query encoder backend is 'auto'; the pinned ONNX artefact is not required",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "agent_pi",
      "status": "pass",
      "message": "pi agent definition current",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "agent_pi_studyloop-session-export",
      "status": "pass",
      "message": "pi studyloop-session-export agent definition current",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "agents",
      "name": "smoke_pi",
      "status": "pass",
      "message": "pi responds (ok)",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "exporter_schema",
      "status": "fail",
      "message": "pinned exporter /tmp/sl-ev-pi-g32vww82/home/.local/bin/session-export is missing; every export hook fails",
      "fix_hint": "studyloop install tools",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "export_mandate_opencode",
      "status": "warn",
      "message": "opencode: no session-export mandate in /tmp/sl-ev-pi-g32vww82/home/.config/opencode/session-db.md \u2014 sessions/struggles won't be persisted to the session DB at session end",
      "fix_hint": "studyloop doctor --fix  (writes the session-export steering mandate)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "session_export_hook_opencode",
      "status": "warn",
      "message": "opencode: missing automatic session-export hook at /tmp/sl-ev-pi-g32vww82/home/.config/opencode/plugins/studyloop-session-export.js",
      "fix_hint": "studyloop doctor --fix  (installs session-end hook)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "session_export_hook_codex",
      "status": "warn",
      "message": "codex: missing SessionEnd export hook in /tmp/sl-ev-pi-g32vww82/home/.codex/hooks.json",
      "fix_hint": "studyloop doctor --fix  (merges Codex SessionEnd hook)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "session_memory_skill_pi",
      "status": "pass",
      "message": "pi: session-memory query skill installed",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "export_mandate_pi",
      "status": "pass",
      "message": "pi: session-export mandate present in session-db.md",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "session_export_hook_pi",
      "status": "pass",
      "message": "pi: automatic session-export hook installed",
      "fix_hint": "",
      "fix_auto": false
    },
    {
      "category": "harness",
      "name": "export_mandate_grok",
      "status": "warn",
      "message": "grok: no session-export mandate in /tmp/sl-ev-pi-g32vww82/home/.grok/rules/session-db.md \u2014 sessions/struggles won't be persisted to the session DB at session end",
      "fix_hint": "studyloop doctor --fix  (writes the session-export steering mandate)",
      "fix_auto": true
    },
    {
      "category": "harness",
      "name": "session_export_hook_grok",
      "status": "warn",
      "message": "grok: missing SessionEnd export hook in /tmp/sl-ev-pi-g32vww82/home/.grok/hooks/studyloop.json",
      "fix_hint": "studyloop doctor --fix  (writes Grok SessionEnd hook)",
      "fix_auto": true
    }
  ]
}
```

### pi — item 2+4-live-lane — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest -m acceptance packages/studyloop/tests/acceptance/test_harness_matrix_live.py -k [pi] -q -rA -p no:cacheprovider --basetemp=/tmp/sl-lane-pi-k_7q5583` → exit `0` (1.92s)

stdout:
```text
.                                                                        [100%]
==================================== PASSES ====================================
=========================== short test summary info ============================
PASSED packages/studyloop/tests/acceptance/test_harness_matrix_live.py::TestHarnessMatrixLive::test_cli_tmux_lane_completes_a_full_scripted_lifecycle[pi]
1 passed, 5 deselected in 1.61s
```

details:
```json
{
  "actor_requested": "gateway",
  "note": "The matrix lane drives the LEARNER side with its own 3 scripted prompts and records actor='scripted' in its bundle regardless of STUDYLOOP_ACC_ACTOR; the actor value is validated by the gate but does not add gateway spend to this lane."
}
```

### pi — item 3-export — PASS-FIXTURE

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Export Evidence: pi --energy 5 --agent pi` → exit `1` (0.2s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.14s)

stdout:
```text
Session ended: Export Evidence: pi
  tmux session closed.
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m agent_session_tools.export_sessions --pi-only -o /tmp/sl-ev-pi-g32vww82/home/evidence-sessions.db` → exit `0` (0.27s)

stdout:
```text
Exporting to: /tmp/sl-ev-pi-g32vww82/home/evidence-sessions.db
Applied 48 database migration(s)

Export results:
  added:   0
  updated: 0
  skipped: 0 (unchanged since last export)
  empty:   0 (no supported conversation or native records)

Database stats:
semantic index not built: sqlite-vec is not installed; install: uv tool install 'agent-session-tools[semantic]'; model all-mpnet-base-v2 (sentence-transformers/all-mpnet-base-v2) is not in the local Hugging Face cache; run 'session-maint embed' once interactively to fetch it; run session-maint embed
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest packages/agent-session-tools/tests/test_pi_exporter.py packages/agent-session-tools/tests/test_export_cli_sources.py -q -p no:cacheprovider` → exit `0` (2.03s)

stdout:
```text
============================= test session starts ==============================
platform darwin -- Python 3.12.8, pytest-9.0.3, pluggy-1.6.0
rootdir: /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/packages/agent-session-tools
configfile: pyproject.toml
plugins: anyio-4.12.1, playwright-0.7.2, timeout-2.4.0, asyncio-1.3.0, base-url-2.1.0, respx-0.23.1, cov-7.0.0
timeout: 60.0s
timeout method: signal
timeout func_only: False
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 40 items

packages/agent-session-tools/tests/test_pi_exporter.py ................. [ 42%]
.........                                                                [ 65%]
packages/agent-session-tools/tests/test_export_cli_sources.py .......... [ 90%]
....                                                                     [100%]

============================== 40 passed in 1.75s ==============================
```

details:
```json
{
  "launch": {
    "state_file_appeared": true,
    "state_after_launch": {
      "mode": "study",
      "topic": "Export Evidence: pi",
      "agent": "pi",
      "tmux_session": "study-export-evidence-pi-88ba14c4",
      "tmux_main_pane": "%0",
      "persona_file": "/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessions/study-export-evidence-pi-88ba14c4/AGENTS.md",
      "persona_hash": "7a4f7f…",
      "session_mode": null,
      "energy": 5
    },
    "tmux_session_exists": true,
    "agent_process_in_pane": true,
    "pane_after_settle": " alt+up to edit all queued messages\n ctrl+v to paste image\n drop files to attach\n\n Pi can explain its own features and look up its docs. Ask\n it how to use or extend Pi.\n\n\n[Context]\n  ~/.pi/agent/AGENTS.md\n\n/private/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessi\nons/study-export-evidence-pi-88ba14c4/AGENTS.md\n\n[Skills]\n  project\n\n/private/tmp/sl-ev-pi-g32vww82/home/.agents/skills/studyloo\np-session-memory/SKILL.md\n\n[Skill conflicts]\n\n/private/tmp/sl-ev-pi-g32vww82/home/.agents/skills/studyloo\np-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n  ~/.agents/skills/studyloop-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n\n\n Warning: No models available. Use /login or set an API\n key environment variable. See\n /opt/homebrew/lib/node_modules/@mariozechner/pi-coding-ag\n ent/docs/providers.md. Then use /model to select a model.\n\n Warning: tmux extended-keys is off. Modified Enter keys\n may not work. Add `set -g extended-keys on` to\n ~/.tmux.conf and restart tmux.\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Update Available\n New version 0.73.1 is available. Run: npm install -g\n @mariozechner/pi-coding-agent\n Changelog:\n https://github.com/badlogic/pi-mono/blob/main/packages/co\n ding-agent/CHANGELOG.md\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n/private/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/se...\n0.0%/0 (auto)                                       unknown\n",
    "pane_after_prompt": "\n\n[Context]\n  ~/.pi/agent/AGENTS.md\n\n/private/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessi\nons/study-export-evidence-pi-88ba14c4/AGENTS.md\n\n[Skills]\n  project\n\n/private/tmp/sl-ev-pi-g32vww82/home/.agents/skills/studyloo\np-session-memory/SKILL.md\n\n[Skill conflicts]\n\n/private/tmp/sl-ev-pi-g32vww82/home/.agents/skills/studyloo\np-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n  ~/.agents/skills/studyloop-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n\n\n Warning: No models available. Use /login or set an API\n key environment variable. See\n /opt/homebrew/lib/node_modules/@mariozechner/pi-coding-ag\n ent/docs/providers.md. Then use /model to select a model.\n\n Warning: tmux extended-keys is off. Modified Enter keys\n may not work. Add `set -g extended-keys on` to\n ~/.tmux.conf and restart tmux.\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Update Available\n New version 0.73.1 is available. Run: npm install -g\n @mariozechner/pi-coding-agent\n Changelog:\n https://github.com/badlogic/pi-mono/blob/main/packages/co\n ding-agent/CHANGELOG.md\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n Error: No API key found for unknown.\n\n Use /login or set an API key environment variable. See\n /opt/homebrew/lib/node_modules/@mariozechner/pi-coding-ag\n ent/docs/providers.md\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500
```

### pi — item 5-plan-architect — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Plan Architect Evidence: pi --energy 5 --agent pi --mode plan-architect` → exit `1` (0.27s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.14s)

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
    "mode": "plan-architect",
    "topic": "Plan Architect Evidence: pi",
    "agent": "pi",
    "tmux_session": "study-plan-architect-evide-df07c5d0",
    "tmux_main_pane": "%0",
    "persona_file": "/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessions/study-plan-architect-evide-df07c5d0/AGENTS.md",
    "persona_hash": "76a318…",
    "session_mode": null,
    "energy": 5
  },
  "tmux_session_exists": true,
  "agent_process_in_pane": true,
  "pane_after_settle": " alt+up to edit all queued messages\n ctrl+v to paste image\n drop files to attach\n\n Pi can explain its own features and look up its docs. Ask\n it how to use or extend Pi.\n\n\n[Context]\n  ~/.pi/agent/AGENTS.md\n\n/private/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessi\nons/study-plan-architect-evide-df07c5d0/AGENTS.md\n\n[Skills]\n  project\n\n/private/tmp/sl-ev-pi-g32vww82/home/.agents/skills/studyloo\np-session-memory/SKILL.md\n\n[Skill conflicts]\n\n/private/tmp/sl-ev-pi-g32vww82/home/.agents/skills/studyloo\np-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n  ~/.agents/skills/studyloop-xtiles-wind-down/SKILL.md\n    Nested mappings are not allowed in compact mappings at\nline 2, column 14:\n\ndescription: At the end of a StudyLoop study session\n(wind-down phase), when `s\u2026\n             ^\n\n\n\n Warning: No models available. Use /login or set an API\n key environment variable. See\n /opt/homebrew/lib/node_modules/@mariozechner/pi-coding-ag\n ent/docs/providers.md. Then use /model to select a model.\n\n Warning: tmux extended-keys is off. Modified Enter keys\n may not work. Add `set -g extended-keys on` to\n ~/.tmux.conf and restart tmux.\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n Update Available\n New version 0.73.1 is available. Run: npm install -g\n @mariozechner/pi-coding-agent\n Changelog:\n https://github.com/badlogic/pi-mono/blob/main/packages/co\n ding-agent/CHANGELOG.md\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n\n\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\n/private/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/se...\n0.0%/0 (auto)                                       unknown\n",
  "persona_file": "/tmp/sl-ev-pi-g32vww82/home/.config/studyloop/sessions/study-plan-architect-evide-df07c5d0/AGENTS.md",
  "persona_first_lines": "# Study Session Context\n\n**Topic:** Plan Architect Evidence: pi",
  "persona_mentions_plan_architect": true,
  "persona_bytes": 7223,
  "tmux_session_gone_after_end": true,
  "final_mode": "ended"
}
```
