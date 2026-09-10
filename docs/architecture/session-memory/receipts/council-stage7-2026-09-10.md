# Council record — Stage 7 (Grok Build automatic session-end export)

**Date:** 2026-09-11 (work began 2026-09-10 23:59) · **Cadence:** single seat, `openai.gpt-6-astra`
(plan council F9) · **Verdict:** **ACCEPT-WITH-CORRECTIONS** — 4 findings, all MINOR, all closed below
(F1/F2/F4 by code in `2e15ee7c`, F3 by measurement). Brief 38 KB — over the 30 KB cap, which existed for
the grok-4.6 seat's context limit; that seat is retired, and astra returned in 36 s. Noted, not repeated.

## What was built

Commits on `main`: `1588fd6a` (feature, 13 files +283/−88), `2b9d2fb1` (test hygiene), `2e15ee7c`
(corrections). Primary source for every Grok claim: `~/.grok/docs/user-guide/10-hooks.md` and
`12-project-rules.md` (Grok CLI's own user guide, the adapter-scope ruling's required source).

| piece | what | source line |
|---|---|---|
| hook file | `$GROK_HOME/hooks/studyloop.json` — merged, StudyLoop-owned by name | "Global · `~/.grok/hooks/*.json` · Always" (10-hooks.md:65) |
| event | `SessionEnd` | "Carries `subagentType` for a child session, so a host can tell a child's teardown from its own" (:104) |
| command | `grep -q '"subagentType" *:' \|\| session-export --grok-only >/dev/null 2>&1 \|\| true` | payload "as JSON on stdin" (:239); "Exit early when `subagentType` is present" (:384) |
| timeout | 8 | default 5 (:165); "the session's ten-second exit budget bounds the `SessionEnd` hooks" (:388) |
| mandate | `_HARNESS_EXPORT["grok"]` → `$GROK_HOME/rules/session-db.md`, flag `grok-only` | "`$GROK_HOME/rules/` (default `~/.grok/rules/`) — Always scanned; applies to all projects" (12-project-rules.md:42) |
| `GROK_HOME` | honoured by installer *and* detection | the GrokExporter already reads sessions from it |
| doctor | `session_export_hook_grok` via the JSON-hook check now shared with codex; `doctor --fix` reaches the installer through the existing top-level path | |
| contract | `strategies == set(RELEASE_HARNESSES)`; the `no_export_hook_yet = {"grok"}` exception set is gone | |
| docs | skill, agent-install, session-memory, setup-guide, shared `AGENTS.md` (Grok reads the Codex file: the wind-down step now names both flags), CHANGELOG, manifest | |

## Dispositions

| id | severity | finding | disposition | evidence |
|---|---|---|---|---|
| F1 | MINOR | `grep -q '"subagentType"'` matches a quoted *token*, so a main-session string value equal to `subagentType` (e.g. a `sessionId`) causes a false skip | **ACCEPT → fixed.** Pattern is now the quoted key followed by a colon, `'"subagentType" *:'`; a JSON string value cannot contain an unescaped `"subagentType":`. The `/bin/sh` test gains the seat's negative control (`"sessionId": "subagentType"` must still export). | old pattern fails the new control: `['--grok-only'] == ['--grok-only', '--grok-only']`; new passes |
| F2 | MINOR | installer honours `GROK_HOME`, `detect_available_agent_tools` checked `~/.grok` — they could disagree | **ACCEPT → fixed.** Detection uses the same `_grok_home()`. Test: alternate `GROK_HOME` only → detected; unset and no `~/.grok` → not. | `test_detection_follows_grok_home` |
| F3 | MINOR | verification showed idempotency on unchanged sessions, not ingestion of a *new* session within budget | **ACCEPT → measured.** A real 1,079,858-byte / 210-line session copied under a fresh id into a scratch `GROK_HOME`; the exact hook line under `/bin/sh` → **0.21 s cold**, scratch DB 1 session / 42 messages; second run `skipped: 1`; subagent payload left the DB mtime unchanged; live DB never opened (grok rows 53 → 53). Cold end-to-end *through Grok itself* remains UNVERIFIED here — see "What is and is not claimed". | command outputs in transcript |
| F4 | MINOR | stubbing one leaking test leaves suite-wide isolation unproven | **ACCEPT → guard added.** Autouse `_fail_on_real_home_harness_writes` in `conftest.py` snapshots all 11 real-home hook/steering files (six harnesses, `GROK_HOME`-aware) before each test and fails the test on any create/change/remove; quiet when the test already failed (same shape as the server-error guard). | restoring the pre-fix `test_config_init_defaults` → guard names `~/.grok/hooks/studyloop.json` and `~/.grok/rules/session-db.md`; fixed test → 38 passed |
| Q2 | — | SIGPIPE if `grep -q` exits before Grok finishes writing | Only the *subagent* (match) path can exit early; a SessionEnd payload is a few hundred bytes, under the pipe buffer, so the writer completes before the reader can close. UNVERIFIED against Grok's runner; fail-open by Grok's contract (:165). | |
| Q3/Q5 | — | 8 s is provisional; large-history cost unmeasured | Agreed: 8 is "above default, below budget", not a guarantee. Incremental scan of 7 sessions 0.12–0.18 s warm; one new 1 MB session 0.21 s cold. The seat's proposed measurement (real Grok teardown at maximum history) is the owner's to take after installation. | |

## Test-hygiene finding (not raised by the seat; found during verification)

During the first full-suite run two files appeared in the **real** `~/.grok` (`hooks/studyloop.json`,
`rules/session-db.md`, born 00:11:17). Bisected to `test_cli.py::test_config_init_defaults`: it answers
Enter to every prompt, and "Install agent definitions now? [Y/n]" defaults to **Yes**, so it ran the real
installer against the developer's home on every suite run — invisible for as long as every file it writes
already existed (each installer is an idempotent no-op then). Both files were removed; the test now stubs
the installer and asserts the stub was reached (`2b9d2fb1`); the F4 guard makes any recurrence a failure.
The real `~/.grok` was **not** written by the feature work itself (sandboxed via `GROK_HOME`).

## Verification

- Gates both packages: ruff 0 / format 0 / pyright 0. Targeted files 120 passed.
- studyloop suite (pre-corrections): 3,955 passed, 31 red = Stage 3 pinned 30 + known `virgin_home`
  mise-tmux red; zero new, zero pinned-turned-green. Post-corrections re-run: see addendum.
- Real sessions: 7 `chat_history.jsonl` under `~/.grok/sessions/`; `session-export --grok-only` twice →
  `added 0 / updated 0 / skipped 6 / empty 1` both times; 0.17 s / 0.18 s.
- Sandboxed install (`GROK_HOME` → scratch copy of the real hooks dir): written once, then 0; the
  pre-existing `herdr.json` byte-identical; doctor → pass.

## What is and is not claimed

**Claimed:** Grok Build now has the same *implemented* export strategy as the other five harnesses — an
installed, doctor-checked, `doctor --fix`-repairable session-end hook whose command has been executed under
`/bin/sh` with real-shaped payloads and shown to export a new real session in 0.21 s, skip a subagent's
teardown, and never fail the hook. **Not claimed (UNVERIFIED here):** that Grok's runner has fired it — no
Grok session was ended during this stage and the real `~/.grok` was deliberately left for the owner's
`studyloop doctor --fix`. The first real session end after that install is the observation that closes it
(`studyloop doctor` → `session_export_hook_grok`; `session-query search … --source grok`).

## Addendum — after the corrections (2026-09-11 00:5x)

- **Suite with the guard active:** first run flagged **36 tests** (33 + 3) as writing into the real home —
  all pre-existing, none from the Grok work: `session.orchestrator._ensure_claude_trust` adds each session
  directory to Claude Code's trusted projects in the developer's own settings file at every session start
  (33 session-start tests → temp `pytest-of-…` paths appended to the real trust list on every suite run
  until now), and the Kiro adapter rewrites the real `study-mentor.json` (3 `studyloop study` tests;
  `KIRO_AGENTS_DIR` is import-time-bound in two modules and only some tests patched it). Fixed in
  `31994b36`: a one-line path seam `_claude_settings_path()` plus an autouse fixture retargeting it and
  both `KIRO_AGENTS_DIR` bindings to a temp home, following conftest's existing session-dir isolation note.
- **Final studyloop suite:** 3,956 passed, 31 red = pinned 30 + `virgin_home`; **guard fired 0 times**.
  The unit suite now provably does not write hook, steering, trust or agent files into the developer's home.
- **Owner note (cannot be done by the agent — credential-path policy):** the real Claude settings file has
  accumulated trust entries for temp pytest paths (`…/pytest-of-ataylor/…`) from every past suite run.
  Harmless, but prunable by hand: remove `projects` keys whose path no longer exists.
- Commits for Stage 7 on `main`: `1588fd6a` feature · `2b9d2fb1` config-init leak · `2e15ee7c` council
  corrections + guard · `31994b36` session-start isolation · this record.
