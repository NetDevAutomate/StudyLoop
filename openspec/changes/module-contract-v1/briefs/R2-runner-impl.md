# Lane R — wave 1: secure runner, consent, exit classes and caps, transient recording, drill CLI (R2–R6)

Read `00-common.md` first (its rules still bind), then `R-runner.md` (globs, forbidden list, your
R1), then this file. Spec you implement:
`openspec/changes/module-contract-v1/specs/drill-runner/spec.md` (amended `4704fd3d` — read it in
full; every scenario maps to a test you turn green). Proposal §5.5, §5.7, §8. The M0 arbitration
`council/2026-10-04-m0-arbitration.md` §4 binds what R6 sends to the mentor hop.

| | |
| --- | --- |
| Branch · worktree | `feat/module-runner` · `/Users/ataylor/code/personal/tools/studyloop-wt/module-runner` |
| Start | `git merge --no-edit main` first (main is at `4704fd3d`+). Stop and report on any conflict. |
| Inherits | your R1: declaration-only `modules/{attempt,consent,runner}.py`, `test_module_runner.py` (24 reds: 2 on today's `practice.py`, 22 on `NotImplementedError`) |
| Done when | R2–R6 ticked in `tasks.md`, every R1 red green, the new scenarios below green red-first, gate G green end to end (the one allowed red is the virgin-HOME tmux test), report filed |
| Merge | after the **M1 adversarial council** reviews R2–R5; the coordinator merges |

## Rulings on the gaps you reported (binding; each is now in the spec)

1. **MC013 at runtime:** a regular file inside the snapshot but outside `scripts/` is refused before
   spawn (you deleted that red as unspecified — restore it, red first).
2. **Caps have values:** 64 KiB stdout, 16 KiB stderr, 2,000 lines total; enforced while streaming.
3. **Flood semantics:** the spec wins over the proposal's wording — on a cap the process is
   **terminated**, `truncated=True` recorded, and the phase classed `ERROR` naming the cap. A
   flooding check is not a trustworthy pass. (Your red asserts "truncation recorded, process not
   left running" — keep both assertions and add the exit class.)
4. **Non-zero `setup`/`cleanup`:** classed `ERROR`, logged and surfaced; a failed cleanup still
   closes the attempt (new scenario in the spec — red first).
5. **Shell tokens:** `;` `|` `&` `&&` `||` `$(` backtick `>` `<` newline; plus an argv length cap of
   64. Add `&` and `||` cases to your red suite.
6. **`practice_check` store:** one row per phase completion in a new `practice_check_events` table of
   the sessions database (identity, attempt id, phase, exit class, code, duration, truncation
   flags, `delivery_status`, `delivery_reason`), owned by `modules/attempt.py`; NOTHING to
   `study_progress`, observations, learning records or review items. Migration follows the repo's
   existing schema-version pattern (read `agent_session_tools` / sessions schema code first; cite
   it in your report).
7. **Consent expiry:** a CLI confirmation is single-use and expires 10 minutes after it is given.
8. **Non-zero cleanup exit class:** see 4.

## M0 decisions that bind R6 (the CLI side of mentor delivery)

- `studyloop drill <phase> <module>/<deck>/<task>` prints the phase result itself first, then
  **one** line: `Mentor told.` or `Mentor not told: <reason>` (reasons: `no_active_session`,
  `transport_closed`, `timed_out`, `unsupported_framing`, `error`).
- R6 sends **typed fields** to the loopback hop — never rendered text: identity (module id, module
  digest, deck id, task id), attempt id, phase, exit class and code, duration, bounded stdout and
  stderr tails (apply your caps; the server re-bounds to 8 KiB and renders). The hop's route is
  lane W's (wave 2) and T2 defines the field schema (`session/module_delivery.py`,
  `PracticeCheckEnvelope`). Until those land, R6 implements the client behind a small
  `modules/hop.py` with a `post_check_result(fields) -> DeliveryOutcome` that reads `web_port` and
  the capability token from the session state file (`session_state.py` — read `write_session_state`
  and `_write_file_secure`), posts to `http://127.0.0.1:<port>/api/modules/practice-check`, and maps
  "no state file / connection refused" → `no_active_session`, non-2xx → `error`. Write it against a
  fake server in tests; the real route arrives in wave 2 and must match the field names you
  document in `hop.py`'s docstring — coordinate through the coordinator, not by importing W.
- The CLI never bypasses consent (`--yes` does not exist).

## Tasks (one commit each minimum; red-first for every new scenario; `Base:` in the first body)

- **R2** `modules/runner.py::run_phase`: one `scripts/` executable + literal args as argv,
  `shell=False`, regular-file-under-`scripts/` check (symlink/hardlink/absolute/directory/outside
  refused), environment from scratch (scratch `HOME` + XDG dirs, minimal `PATH`, `STUDYLOOP_DRILL_ID`,
  `STUDYLOOP_ATTEMPT_DIR`, `STUDYLOOP_MODULE_ID`, `KUBECONFIG` when the target is `kubeconfig-context`),
  `cwd` = the attempt dir, spawn via `subprocess.Popen` looked up on the module (your tests spy on
  it). Your R1 boundary cases turn green.
- **R3** `modules/consent.py`: show phase, target, exact argv, script sha256; confirm; re-hash
  immediately before spawn and abort on mismatch; fresh consent per phase; 10-minute single-use.
  Digest-race and replay reds green.
- **R4** exit classes per phase (ruling 4), per-phase `timeoutSeconds` (timeout → `ERROR`,
  `timed_out=True`, process terminated then killed), streamed caps with termination (rulings 2–3),
  redaction through the existing secret detector **before** anything is persisted or shown.
- **R5** `modules/attempt.py`: `practice_check_events` (ruling 6); `test_drill_writes_no_observation`
  green against **your** path; a second test proves the row exists with the right fields.
- **R6** `cli/_drill.py` exported group (W registers it), `modules/hop.py` client, the outcome
  line; `test_module_drill_cli.py` runs the C3 scaffold's offline drill end to end with no Docker —
  if lane C's scaffold has not merged when you reach R6, build an equivalent fixture module under
  `tests/fixtures/modules/runner-offline/` (your glob) and say so.

## Cross-lane facts

- Lane C exports `load_lockfile()`, `LockEntry`, `snapshot_dir(entry)` from `modules/store.py`
  (wave 1, in flight). If C has merged when you reach R6, import those; if not, define a minimal
  `Protocol` for what you need in `modules/attempt.py` and let the coordinator reconcile at merge.
  Never edit C's files.
- Never run `just e2e`. While any red remains run gate G recipe-by-recipe; once green run
  `just preflight` end to end.

## Report (common §6 plus)

The argv/env of one real spawn as the spy saw it; the `practice_check_events` DDL; the exact
outcome line for a run with no server; the field list `hop.py` documents (W and T build to it);
gate summary lines; gaps.
