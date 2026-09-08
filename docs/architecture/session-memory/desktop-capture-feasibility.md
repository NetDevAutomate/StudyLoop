# Desktop capture feasibility

Status: evidence-backed B5 spike, 2026-09-08. This artefact records feasibility;
it does not claim that an unverified desktop export has occurred.

| Application | Feasible now? | Evidence | Ruling |
| --- | --- | --- | --- |
| Claude Desktop | **No** | `agent_session_tools/exporters/claude.py` reads Claude Code's `~/.claude/projects` transcript tree; `packages/studyloop/tests/test_harness_export.py` installs a Claude Code `Stop` hook only. No desktop transcript store or desktop lifecycle-hook contract exists in this repository. | Do not claim coverage. A future desktop exporter needs a discovered local store and its own fixture/live acceptance. |
| Codex Desktop | **Yes, via the shared SessionEnd hook**, subject to the application's normal hook trust prompt | `studyloop.installers.install_codex_session_end_hook` writes the global `~/.codex/hooks.json` `SessionEnd` command; `packages/studyloop/tests/test_harness_export.py::TestCodexSessionEndHook` proves preservation and idempotence. The installer contract explicitly covers CLI and app sessions. | Run synchronously with `session-export --codex-only --verify`; doctor checks the resulting per-source receipt lag. |

## Supervision and sweep

One-shot Claude Code and Codex hooks run synchronously and invoke
`session-export --<source>-only --verify`. The command records a
`session_export_runs` receipt only after the database contains the source's
post-export session/message counts. `studyloop doctor --category harness`
reports the last verified export lag per detected source.

A periodic launchd or equivalent sweep uses the same product command rather
than a second capture path:

```sh
session-export --verify
studyloop doctor --category harness
```

The sweep is belt-and-braces recovery for a missed lifecycle hook. Hook commands
remain fail-open (`|| true`) so a capture problem cannot trap the host harness;
the durable receipt and doctor warning make that failure visible afterward.
