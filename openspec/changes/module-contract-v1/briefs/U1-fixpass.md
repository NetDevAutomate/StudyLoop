# Lane U1 — fix pass after the U1 review (gpt-5.6-sol, do not merge, 10 raised)

Read first: `council/2026-10-05-review-U1-gpt-5.6-sol.md` (every finding verified by the
coordinator against the tree) and `design.md` §6 as amended on `main` (two rulings: the
mentor stand-in question and step 7). `git merge main` in your worktree first.

Same rules as every pass: red-first per item with a transcript pair under `evidence/U1/`
(command on line 1, sha + UTC on line 2); commit after every item; pre-commit at commit time
(re-add and retry when a fixer rewrites a transcript); never `--no-verify`/`SKIP=`; stage
specific paths; never push; never write outside your worktree; no nested sub-agents; env
rules unchanged. Items marked **GRANT** touch files outside your globs: exactly the edit
named, recorded in your U1 ownership row with `# coordinator-granted, U1-review F<n>`.

## Rulings (coordinator)

- **F2 (fake mentor) — RULED, no reclassification.** The module personas' subject is the
  module surface, not the mentor. `design.md` §6 now says: drive the harness
  `STUDYLOOP_ACC_HARNESS` selects when one is selected; the e2e fake agent otherwise; the
  bundle's `harness` field says which. Your code already writes `harness="fake-agent"`
  honestly. Fix = make the selection real (item 2 below), not a tier change.
- **F9 (seven commits) — accepted as is**; the Persona B split-out is a coherent unit.
  No squash.
- **F10 (per-commit gate tails) — record the evidence gap** in one sentence in your report
  and in `evidence/U1/README.md`; do not fabricate retroactive transcripts.
- Everything else is fixed before merge, in this order.

## Order

1. **F1 BLOCKER — `server.log` is gitignored (`.gitignore:77`, `*.log`) so the committed
   bundle lacks the member its manifest names.** Rename the member to `server-log.txt` in
   `write_evidence_bundle` (and the manifest key stays `server_log`), regenerate the
   forced-failure bundle, and prove with `git ls-files` that all nine members are tracked. No
   `git add -f`, no `.gitignore` edit.
2. **F2 — harness selection.** In `personas/world.py` build the world with the e2e fake agent
   ONLY when no harness is selected (`conftest.selected_harnesses()` empty / `""`); when one
   is, start the server with that harness exactly as `test_harness_matrix_live.py` does, and
   write its name into the bundle's `harness`. Red: with `STUDYLOOP_ACC_HARNESS=kiro-cli`
   (or any selected name) the world must not inject `STUDYLOOP_TEST_AGENT_CMD` — assert on
   the server's env/argv, skip (by name) if that binary is absent on the host.
3. **F3 HIGH — redaction detects but does not fail.** In `personas/bundle.py`: redact the
   `outcome`/`reason` before it enters the manifest, and when `verify_redacted` returns
   violations, write `redaction-violations.txt` AND raise (the test fails naming the bundle).
   Red: a forced failure whose reason contains the venv path (the B8 case in
   `persona-b-b8.red.txt:17-19`) now fails on the redaction assertion with the violation
   named, and the regenerated bundle has zero violations.
4. **F4 HIGH — `attempt-envelope.json` is not the production envelope.** Rename the member
   to `labs-binding.json` (what it actually is: the Labs start binding — session, drill
   nonce, attempt ids), and ADD `practice-envelope.json` only when a drill phase actually
   ran in the persona (Persona A runs none by design; Persona B's b4 lifecycle runs none
   either) — so the member is written only by a persona step that calls `studyloop drill
   check`, validated through `session.module_delivery.validate_envelope` before writing.
   If no persona step runs a check, the brief's "attempt envelope" member is documented in
   `evidence/U1/README.md` as "absent by design: no persona executes a phase (proposal §7:
   browser never executes; CLI phases are the kdrill live proof's)". Say which you did.
5. **F5 MEDIUM — six FORCE_FAIL reds prove a 15 s Playwright timeout, not the assertion.**
   For A2, A3, A5, B4, B5, B6: replace `wait_for_selector`-until-timeout with a bounded
   state read (poll up to N seconds, then read the DOM once) followed by an explicit
   assertion with a message naming the expected state; regenerate those six reds so each
   fails on its own assertion line.
6. **F6 MEDIUM — the C7 sweep (`assert_c7_clean`: no overdue counter, hint, solution or
   mentor notes) is not run in every browser phase.** Call it from the phase wrapper
   whenever a page exists (A3, B5 and the budget phases included). Red: a planted
   `data-testid="hint"` element in a fixture page (or a monkeypatched DOM insertion) makes
   every browser phase fail, not just the ones that called it before.
7. **F7 MEDIUM — B9 checks literals/regexes, not the documented output.** Parse the fenced
   output blocks for `module new`, `module check`, `module list` from
   `docs/module-contract.md` and `docs/cli-reference.md` (the drift test's receipt files
   under `docs/` tell you where the receipts live) and compare each command's captured
   output line-shape to the documented one (normalise paths/ids/digests the same way the
   receipt audit does). Red: edit a copy of the doc's fenced block in a tmp fixture and show
   the comparison fails.
8. **F8 MEDIUM — two "reds" are not reds.** `ownership-guard.red.txt` is a skip (relabel it
   `.pin.txt` and say so), and `bundle-members.red.txt`'s positive control never failed —
   relabel as pre-existing-behaviour coverage in the file's header and in
   `evidence/U1/README.md`. Add one genuinely red requirement test for the U1 ownership map
   (e.g. the map must list `personas/**`) and keep its red.
9. **GRANT (small, do it last) — the a4a focus defect.** `web/static/js/components/live-agent-console.js`
   ~259: call `term.focus()` after `term.open(...)` on attach and re-attach (and nothing else
   in that file); `web/static/js/labs.js`: after the post-start reload path, focus the console
   (nothing else). Then flip a4a from `xfail(strict=True)` to a plain assertion and keep the
   old red (`persona-a-a4a-focus-gap.red.txt`) as its red; add the JS files to your ownership
   row as granted. Run `just test-js` (189 must stay green) and the e2e journey file
   `tests/e2e/test_module_labs_journey.py` (W's, 9 passed) to prove no regression.

## Gate before you report

`just testacc "" scripted packages/studyloop/tests/acceptance/test_module_personas.py` (now 23
passed, 0 xfailed); `just e2e packages/studyloop/tests/e2e/test_module_labs_journey.py` (9
passed); `just test-js`; the ownership + docs-drift + contributor-docs suites; `just lint
typecheck`; `just docs`; proof the default tier deselects all 23; `git ls-files` listing the
nine bundle members. Save transcripts as `fixpass-gate-*.txt`. Tree clean.

Report ≤ 600 words: commits; one line per finding with its red/green files; which of F4's two
paths you took; the F10 evidence-gap sentence; every granted file and the exact hunk scope.
