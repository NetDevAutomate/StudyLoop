## OpenCode (`opencode`) — live items in real-harness-auth mode

- binary: `/opt/homebrew/bin/opencode` — `--version` → `1.18.30`
- recorded: 2026-09-16T00:09:21+00:00 on macOS-27.0-arm64-arm-64bit; repo `fe7534d6` (dirty=True)
- scratch root: `/tmp/sl-ev-opencode-4v1cl8d0` (swept: True)

| # | Item | Verdict | Decisive line |
| --- | --- | --- | --- |
| 2+4-live-lane | live-lane | **PASS** | pytest exit 0: 1 passed, 5 deselected in 9.67s; bundle outcome(s)=['completed']; turn audit=[{'turns': 3, 'turns_with_no_model_marker': 0, 'turns_over_1s': 1, 'real_model_reply_plausible': False}] |
| 3-export | export | **PASS-FIXTURE** | no live transcript under scratch (export exit 0, rows={'opencode': 4}); exporter fixture tests passed: ============================== 34 passed in 1.70s ============================== |
| 5-plan-architect | plan-architect | **PASS** | persona_file=/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-plan-architect-evide-5a74fb57/.opencode/agents/study-mentor.md plan-architect=True agent_in_pane=True final_mode=ended |

### opencode — item 2+4-live-lane — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest -m acceptance packages/studyloop/tests/acceptance/test_harness_matrix_live.py -k [opencode] -q -rA -p no:cacheprovider --basetemp=/tmp/sl-lane-opencode-lkhrbq64` → exit `0` (9.98s)

stdout:
```text
.                                                                        [100%]
==================================== PASSES ====================================
=========================== short test summary info ============================
PASSED packages/studyloop/tests/acceptance/test_harness_matrix_live.py::TestHarnessMatrixLive::test_cli_tmux_lane_completes_a_full_scripted_lifecycle[opencode]
1 passed, 5 deselected in 9.67s
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

### opencode — item 3-export — PASS-FIXTURE

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Export Evidence: opencode --energy 5 --agent opencode` → exit `1` (2.64s)

stderr:
```text
open terminal failed: not a terminal
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study --end` → exit `0` (0.15s)

stdout:
```text
Session ended: Export Evidence: opencode
  tmux session closed.
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m agent_session_tools.export_sessions --opencode-only -o /tmp/sl-ev-opencode-real-gox_3kaw/home/evidence-sessions.db` → exit `0` (0.3s)

stdout:
```text
Exporting to: /tmp/sl-ev-opencode-real-gox_3kaw/home/evidence-sessions.db
Applied 48 database migration(s)

Export results:
  added:   4
  updated: 0
  skipped: 0 (unchanged since last export)
  empty:   0 (no supported conversation or native records)

Database stats:
  opencode: 4 sessions, 31 messages
semantic index not built: sqlite-vec is not installed; install: uv tool install 'agent-session-tools[semantic]'; run session-maint embed
```

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m pytest packages/agent-session-tools/tests/test_exporter_opencode.py packages/agent-session-tools/tests/test_export_cli_sources.py -q -p no:cacheprovider` → exit `0` (1.98s)

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
collected 34 items

packages/agent-session-tools/tests/test_exporter_opencode.py ........... [ 32%]
.........                                                                [ 58%]
packages/agent-session-tools/tests/test_export_cli_sources.py .......... [ 88%]
....                                                                     [100%]

============================== 34 passed in 1.70s ==============================
```

details:
```json
{
  "launch": {
    "state_file_appeared": true,
    "state_after_launch": {
      "session_dir": "/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-export-evidence-open-8316336c",
      "mode": "study",
      "topic": "Export Evidence: opencode",
      "agent": "opencode",
      "tmux_session": "study-export-evidence-open-8316336c",
      "tmux_main_pane": "%0",
      "persona_file": "/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-export-evidence-open-8316336c/.opencode/agents/study-mentor.md",
      "persona_hash": "d76b47…",
      "session_mode": null,
      "energy": 5
    },
    "tmux_session_exists": true,
    "agent_process_in_pane": true,
    "pane_after_settle": "\n                                           \u2584\n          \u2588\u2580\u2580\u2588 \u2588\u2580\u2580\u2588 \u2588\u2580\u2580\u2588 \u2588\u2580\u2580\u2584 \u2588\u2580\u2580\u2580 \u2588\u2580\u2580\u2588 \u2588\u2580\u2580\u2588 \u2588\u2580\u2580\u2588\n          \u2588  \u2588 \u2588  \u2588 \u2588\u2580\u2580\u2580 \u2588  \u2588 \u2588    \u2588  \u2588 \u2588  \u2588 \u2588\u2580\u2580\u2580\n          \u2580\u2580\u2580\u2580 \u2588\u2580\u2580\u2580 \u2580\u2580\u2580\u2580 \u2580\u2580\u2580\u2580 \u2580\u2580\u2580\u2580 \u2580\u2580\u2580\u2580 \u2580\u2580\u2580\u2580 \u2580\u2580\u2580\u2580\n\n  \u2503\n  \u2503  Ask anything\u2026 \"What is the tech stack of this\n  \u2503  project?\"\n  \u2503\n  \u2503  Study-     \u00b7MiniMax-M2.5 MiniMax Token Plan (\n  \u2503  Mentor                   minimax.io)\n  \u2579\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\n                              tab agents  ctrl+p commands\n\n\n\n\n  /private/tmp/sl-ev-          \u2299 9 MCP /status    1.18.30\n  opencode-real-gox_3kaw/\n  home/.config/studyloop/\n  sessions/study-export-\n  evidence-open-8316336c\n\n",
    "reply_wait_seconds": 15.1,
    "pane_quiescent": true,
    "pane_after_prompt": "config/studyloop/sessions.db\n  \u2503  Study-     \u00b7MiniMax-M2.5 MiniMax Token Plan (\nExport results:               minimax.io)\n  added:   4\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\u2580\n  updated: 0tmp/sl-ev-opencode-real-   tab     ctrl+p\n  skipped: 0 (unchanged since last export)nts  commands\n  empty:   0 (no supported conversation or native records)\n   8316336c\nDatabase stats:\n  opencode: 4 sessions, 31 messages\nLoading weights: 100%|\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2588| 199/199 [00:00<00:00, 835\n5.02it/s]\n/Users/ataylor/.local/share/uv/tools/agent-session-tools/li\nb/python3.13/site-packages/agent_session_tools/embeddings.p\ny:267: FutureWarning: The `get_sentence_embedding_dimension\n` method has been renamed to `get_embedding_dimension`.\n  actual_dim = _models[model_name].get_sentence_embedding_d\nimension()\n[transformers] Token indices sequence length is longer than\n the specified maximum sequence length for this model (492\n> 384). Running this sequence through the model will result\n in indexing errors\nsemantic index: embedded 24 messages, 0 remaining (4.6s)\n\n",
    "persona_file": "/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-export-evidence-open-8316336c/.opencode/agents/study-mentor.md",
    "persona_first_lines": "---\ndescription: \"AuDHD-aware Socratic study mentor\"\nmode: primary",
    "persona_mentions_plan_architect": false,
    "persona_bytes": 6215,
    "tmux_session_gone_after_end": true,
    "final_mode": "ended"
  },
  "scratch_harness_dirs_after_session": {
    "(real harness home: not listed)": []
  },
  "export_db": "/tmp/sl-ev-opencode-real-gox_3kaw/home/evidence-sessions.db",
  "rows_by_source": {
    "opencode": 4
  },
  "session_dir": "/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-export-evidence-open-8316336c",
  "rows_for_this_session": [],
  "fixture_tests": "packages/agent-session-tools/tests/test_exporter_opencode.py"
}
```

### opencode — item 5-plan-architect — PASS

`$ /Users/ataylor/code/personal/tools/studyloop-wt/harness-tier/.venv/bin/python3 -m studyloop.cli study Plan Architect Evidence: opencode --energy 5 --agent opencode --mode plan-architect` → exit `1` (2.71s)

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
    "session_dir": "/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-plan-architect-evide-5a74fb57",
    "mode": "plan-architect",
    "topic": "Plan Architect Evidence: opencode",
    "agent": "opencode",
    "tmux_session": "study-plan-architect-evide-5a74fb57",
    "tmux_main_pane": "%0",
    "persona_file": "/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-plan-architect-evide-5a74fb57/.opencode/agents/study-mentor.md",
    "persona_hash": "1704f1…",
    "session_mode": null,
    "energy": 5
  },
  "tmux_session_exists": true,
  "agent_process_in_pane": true,
  "pane_after_settle": "\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n",
  "persona_file": "/tmp/sl-ev-opencode-real-gox_3kaw/home/.config/studyloop/sessions/study-plan-architect-evide-5a74fb57/.opencode/agents/study-mentor.md",
  "persona_first_lines": "---\ndescription: \"AuDHD-aware Socratic study mentor\"\nmode: primary",
  "persona_mentions_plan_architect": true,
  "persona_bytes": 7448,
  "tmux_session_gone_after_end": true,
  "final_mode": "ended"
}
```
