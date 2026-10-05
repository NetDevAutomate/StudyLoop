# Lane U1 — Persona A and Persona B scripted acceptance journeys

Read first: `briefs/00-common.md`; `design.md` §6 (the two personas, every step and assertion
is a test you write; the budgets are 6 and 8 minutes; the failure bundle gains server log, CLI
transcript, `modules.lock.json` diff and the attempt envelope); `docs/acceptance-testing.md`
(tiers: acceptance = scripted actor through the real surface under `STUDYLOOP_ACC=1`;
`just testacc TESTS=<file>` is the runner — read the recipe in the root `justfile`, ~line 121:
it runs `pytest -m acceptance` and IGNORES `tests/acceptance/uat`); and the code you build on:

- `packages/studyloop/tests/e2e/test_module_labs_journey.py` — lane W's nine-phase browser
  journey (no module → `module add` → one Labs entry → start inside the one claimed session →
  Tab/Shift-Tab → reload re-attaches → Escape cancels → `drill check` reaches the mentor pane →
  `module remove` → Labs gone). Persona A is this journey re-expressed at the acceptance tier
  with the §6 additions; REUSE its helpers by import where they are importable, copy only what
  the e2e module keeps private, never edit it.
- `packages/studyloop/tests/e2e/_env.py` — the test world (`launch_env`, `start_server(world,
  extra_args=…)`, `ConsoleWatch`, `diag`); Persona A runs the server with `--lan` (check
  `_web.py` for the flag and bind the test to 127.0.0.1 regardless — never a real LAN address).
- `packages/studyloop/tests/acceptance/conftest.py` (`_acceptance_gate`, `scratch_env`,
  `learner_actor_factory`), `acceptance/evidence.py` (`EvidenceBundle`,
  `write_evidence_bundle`), `acceptance/actors/budget.py` (`BudgetGuard`) — the tier's
  conventions; `acceptance/test_module_kdrill_live.py` for the CLI-through-scratch pattern.
- Fixtures: `tests/fixtures/modules/valid-scaffold` (what `module new` produces),
  `tests/fixtures/modules/k8s-offline` (a kubeconfig-context module that declares `kind`).

Worktree `/Users/ataylor/code/personal/tools/studyloop-wt/module-personas`, branch
`feat/module-personas` from `main` (K0 merged, d997a4d0 or later). Red-first: every test is
red before the thing it asserts exists or before the fixture flips it, with a transcript under
`evidence/U1/` (command on line 1, sha + UTC on line 2); commit after every unit; pre-commit at
commit time; never `--no-verify`/`SKIP=`; stage specific paths; never push; nothing written to
the main checkout; no nested sub-agents. Env: `export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"`,
mise shims + `/opt/homebrew/bin` first on PATH, `env -u VIRTUAL_ENV uv run …`. Playwright and
ttyd are installed; the browser runs headless.

## Owned globs

- `packages/studyloop/tests/acceptance/test_module_personas.py` (new)
- `packages/studyloop/tests/acceptance/evidence.py` — ADD the four bundle members (server log,
  CLI transcript, `modules.lock.json` before/after diff, attempt envelope JSON) as optional
  inputs; existing callers must not change
- `packages/studyloop/tests/acceptance/personas/**` (new; helpers, the "missing kind" fixture
  module built from `valid-scaffold` with `prerequisites: [kind]` and a workdir target)
- `openspec/changes/module-contract-v1/evidence/U1/**`; a `U1` row in
  `tests/fixtures/lane_ownership.yaml` with exactly these paths and `feat/module-personas: U1`
  in its `branches:` map plus the `_MODULE_CONTRACT_BRANCHES` entry in
  `tests/test_lane_ownership.py` (coordinator-granted; comment both)
- `docs/acceptance-testing.md` — ONE new subsection naming the two persona journeys and the
  command that runs them (no other edits; the drift tests pin that page's commands — run them)

Forbidden: everything under `src/`, the e2e journey, `uat/**`, specs, tasks.md (except the U1
tick, last commit). No real `kind`/`docker`/network. If a persona step cannot be asserted
without a product change, write the test, mark it `xfail(strict=True)` with the reason naming
the gap, and list it in your report — do not weaken the assertion.

## Persona A — AuDHD learner on a tablet over `--lan` (viewport 820×1180, budget 6 min)

One module-scoped server, phases as separate ordered tests sharing facts (W4's pattern):
(1) load: no Labs entry and no prerequisite text anywhere in the DOM; (2) `module add
<valid-scaffold>` via the CLI through the scratch env, reload, exactly one Labs entry listing
drill ids and prompts only; (3) start one drill: it runs inside the single claimed session (no
second session, no `module-attempts` directory appears — Labs never executes a phase); (4) focus
lands in the terminal; Tab / Shift-Tab / Escape remain usable (keyboard-only traversal); (5)
cancel: clear recovery copy (quote the string you assert); (6) reload: re-attach, still one
session; (7) `module add` the missing-`kind` fixture: a concise prerequisite report naming
`kind`, exit non-zero, no snapshot published, no Labs change; (8) `module remove`, reload, Labs
gone. Throughout every phase: no overdue counter, no hint, no solution, no mentor notes in the
DOM (assert on the rendered text, not on CSS classes). Wall-clock: `BudgetGuard`-style timing —
the whole persona must finish under 6 minutes and the test fails if it does not.

## Persona B — new contributor on a clean machine (viewport 1440×900, budget 8 min)

(1) the documented `uv` setup commands from `docs/contributor-environment.md` succeed in the
scratch env (the ones that do not need network — say which you skipped and why); (2)
`studyloop module new` scaffolds; (3) `studyloop module check` passes it; (4) the Persona-A
lifecycle (add → Labs → start → cancel → remove) at this viewport; (5) break one fixture (remove
`cleanupCommand` from a kubeconfig-context copy → MC017; or any single rule), read the `--json`
failure (rule id, file, line), repair it, re-check green; (6) assert the docs' commands and the
observed output agree for `module new`, `module check`, `module list` (compare the fenced
output in `docs/module-contract.md` / `docs/cli-reference.md` with what you observed — the
structural half is `test_docs_drift.py`'s; yours is the observed half).

## Failure bundle

On any phase failure the bundle under the run's evidence directory must contain, in addition
to what `write_evidence_bundle` writes today: the subprocess server's log, the CLI transcripts
of every `studyloop` call the persona made, a before/after diff of `modules.lock.json`, and
the attempt envelope JSON when a drill was started. Prove it with ONE forced failure
(`STUDYLOOP_ACC_FORCE_FAIL=<phase>` or a monkeypatched assertion — your call, say which) whose
bundle you commit under `evidence/U1/forced-failure-bundle/` with secrets redacted by the
existing `uat/redaction.py` rules (import it; do not copy it).

## Gate before you report

`just testacc TESTS=packages/studyloop/tests/acceptance/test_module_personas.py` green with
both personas under budget (save the transcript with timings); `uv run pytest
packages/studyloop/tests/test_lane_ownership.py packages/studyloop/tests/test_docs_drift.py
packages/studyloop/tests/test_contributor_docs.py -q -p no:cacheprovider`; `just lint typecheck`;
`just docs`; the default `just test` selection must not collect your acceptance tests (the
marker gate) — prove it with `uv run pytest packages/studyloop/tests/acceptance/test_module_personas.py
-q -p no:cacheprovider` showing them skipped/deselected without `STUDYLOOP_ACC=1`.

Report ≤ 600 words: commits; per persona the step list with pass/xfail and the measured
wall-clock; the forced-failure bundle's file list; every gap you xfailed with the product
change it needs; anything in `design.md` §6 you judged wrong against the shipped UI (cite
file:line).
