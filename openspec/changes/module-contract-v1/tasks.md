# Tasks — module contract v1 (MVP)

Checklist form of `design.md`. Every task ends with its verification; a task without a green
verification is not done. Gate **G** = pre-commit (all hooks) + `env -u VIRTUAL_ENV just
preflight`. "Red kept" = the failing-test transcript is in the commit body or under
`openspec/changes/module-contract-v1/evidence/<lane>/`.

## 0. Setup (coordinator)

- [x] 0.1 Create five worktrees under `../studyloop-wt/module-<lane>`, one per lane branch
      (`feat/module-schema`, `feat/module-conformance`, `feat/module-runner`,
      `feat/module-mentor-delivery`, `feat/module-web-labs`) from the same base sha; run
      `env -u VIRTUAL_ENV just sync-dev` then `env -u VIRTUAL_ENV just test` in **one** of them
      (the recipe is proven once); every other lane runs `just sync-dev` as its own step 1.
- [x] 0.2 Write the five lane briefs per `design.md` §11 and store them under
      `openspec/changes/module-contract-v1/briefs/`; verify each names its owned/forbidden
      globs, DoD tests, red-first obligation and merge position.
- [x] 0.3 Confirm the docs lease: `docs/`, `mkdocs.yml`, `CHANGELOG.md` have no uncommitted
      edits from the other session before S3 is scheduled; verify with `git status` on `main`.
- [x] 0.4 Open `council/catch-rate.md` (design.md §7 review cadence) with one row per planned
      review: S-review, M0, C-review, M1, T-review, W-review, M2.

## 1. Wave 0 — S lands; C and R go red; T spikes

### S — schema + guard (`feat/module-schema`)

- [x] S1 Re-key `tests/_lane_ownership.py` to an explicit branch→lane map in
      `tests/fixtures/lane_ownership.yaml` (`feat/module-schema`→S, …), keep legacy `lane/m<n>-`
      entries and fnmatch/`shared`/unmapped semantics; verify new branch-parsing tests pass and
      the existing `test_lane_ownership.py` still passes. G.
- [x] S2 Add the six §5.3 fields (`id` on deck and task; `solution`, `scaffolding`,
      `mentorNotes`; `verification.cleanupCommand`) with `extra: forbid` kept; verify
      `test_module_schema.py`: the proposal's example validates, each field round-trips,
      missing/duplicate/malformed `id` rejected, a pre-existing deck still validates.
      Red kept: the example failing before this commit. G.
- [x] S-review One independent seat reviews S1–S2 (design.md §7 cadence); coordinator
      verifies each finding against the tree; verify the row in `council/catch-rate.md` is filled.
- [x] S-merge (local) Merged to `main` as `d2671ce8`, the first and only early merge; sha filled
      into `comms/2026-10-04-issue-53-reply.md`.
- [ ] S-merge (owner) push `main`; post the #53 reply (owner's account, owner's call); verify the
      comment is up and its proposal link resolves.
- [ ] S3 (docs lease RELEASED 2026-10-04 21:40 — contributor guide merged at 6a3f45d2; lane S may take it) `docs/module-contract.md` with the "Adding a module" checklist,
      `.github/PULL_REQUEST_TEMPLATE/module.md`, `mkdocs.yml` nav entry, changelog entry;
      verify `test_docs_drift.py` extension (checklist, four README headings, PR template,
      MC001–MC016 linked) is red before and green after; `just docs` strict. G.

### C — red tests only (`feat/module-conformance`)

- [x] C1 Fixtures under `tests/fixtures/modules/`: `valid-scaffold/` plus `mc001/` … `mc016/`,
      each breaking exactly one rule, each with a `repaired/` twin; `test_module_check.py`
      asserting one named rule per fixture; verify all 16 fail (no engine yet). Red kept.

### R — adversarial red tests only (`feat/module-runner`)

- [x] R1 `test_module_runner.py` adversarial cases: shell token in argv, symlink/hardlink
      script, inherited environment variable visible, script changed after consent, consent
      replay, per-phase timeout, output flood; plus `test_drill_writes_no_observation` and
      `test_runner_never_shell`; verify all fail — the last two against today's
      `learning/practice.py` path (`:179-188`, `:282-290`). Red kept.

### T — spike (`feat/module-mentor-delivery`)

- [x] T1 Read `session/active.py`, `session/transport.py`, `session/transports/pty.py`,
      `session/transports/acp.py`, `web/routes/session/_transport.py`; draft
      `docs/adr/0012-practice-check-delivery.md` answering: PTY framing, ACP serialisation
      against an in-flight turn, envelope size bound, learner-visible failure; write test
      doubles only; verify no production code changed (`git diff --stat` shows ADR + tests).
- [x] **M0 council** — four seats review the ADR draft and traces; coordinator arbitrates into
      the ADR; verify the ADR records the decision and the rejected options.

## 2. Wave 1 — C, R, T implement; W writes tests

### C — conformance + lifecycle

- [x] C2 `modules/manifest.py` (Pydantic, `extra: forbid`), `modules/check.py` with rule ids and
      `--json`; verify the 16 fixtures each fail naming exactly one `MCnnn`, 16 repaired twins
      pass, `valid-scaffold` passes. G.
- [x] C3 `modules/scaffold.py` + `module new <id>`; verify scaffold output passes `check` and
      contains one `echo`-based offline drill. G.
- [x] C4 `modules/store.py` + `module add <path>` / `list` / `remove`: immutable snapshot,
      content digest, lockfile written only after `check` passes, git remote + `HEAD` sha read
      locally when present, `remove` idempotent; verify `test_module_lifecycle.py`: failed check
      leaves `modules.lock.json` byte-identical (red kept). G.
- [x] C5 `doctor/modules.py` probes `docker`, `kind`, `kubectl` with fake binaries on `PATH`;
      one registration in `cli/_doctor.py`; verify probes report version/missing and never
      execute anything but `--version`. G.
- [x] C6 `cli/_module.py` Click group (`click.Group`, mounted lazily like every other `cli/_*.py`) exported, not registered; verify `test_module_cli.py`
      via `CliRunner` on the group object. G.
- [x] C-review One independent seat reviews C2–C6 before C merges; verify the catch-rate row.

### R — secure runner + drill CLI

- [x] R2 `modules/runner.py`: single `scripts/` executable + literal args as argv,
      `shell=False`, regular-file check (MC013 at runtime too), environment built from scratch
      (scratch `HOME`/XDG, minimal `PATH`, the four `STUDYLOOP_*`/`KUBECONFIG` variables);
      verify R1 boundary cases turn green. G.
- [x] R3 `modules/consent.py`: argv + script content digest + phase + target shown, confirmed,
      re-checked immediately before spawn; fresh consent per `setup`/`cleanup`; verify the
      digest-race and replay tests turn green. G.
- [x] R4 Exit classes per phase, per-phase `timeoutSeconds`, streamed byte/time caps with
      truncation recorded, redaction before persistence; verify timeout → error and flood →
      truncated tests green. G.
- [x] R5 `modules/attempt.py` transient `practice_check` recording; verify
      `test_drill_writes_no_observation` green with the observations table row count unchanged
      (red kept from R1). G.
- [x] R6 `cli/_drill.py`: `studyloop drill <setup|check|cleanup> <module>/<deck>/<task>` exported
      group; verify `test_module_drill_cli.py` runs the C3 scaffold's offline drill end to end
      with no Docker. G.
- [x] **M1 council** — adversarial review of R2–R5 before merge; coordinator arbitrates;
      verify every M1 finding is either fixed with a test or recorded as accepted risk in
      `design.md` §9.

### T — mentor delivery (after M0)

- [ ] T-owner Probe each PTY harness (claude, codex, kiro-cli, pi) for `ESC[?2004h` at start-up with
      the real binaries; record which enable bracketed paste (M0 Q3: confirms, does not gate T3).

- [x] T2 `session/module_delivery.py`: typed, size-bounded `PracticeCheckEnvelope`; adapter
      resolving `ActiveSession.transport`; verify unit tests for bound, labelling and the
      "no active session" path. G.
- [x] T3 PTY delivery per the ADR's framing; verify
      `integration/test_module_delivery_transports.py::test_pty` shows one labelled envelope
      reaching a fake mentor, identity + exit class present, output redacted (red kept). G.
- [x] T4 ACP delivery per the ADR's serialisation; verify `::test_acp` green and
      `::test_acp_no_overlap_with_learner_turn` green; verify delivery failure is surfaced to
      the learner by a third test. G.
  - Coordinator-approved ownership exception (T-review finding 5): lane T's +10-line hunk in
    `packages/studyloop/tests/fixtures/lane_ownership.yaml` adding `session/transport.py`, `transports/pty.py`
    and `transports/acp.py` to T's row is accepted as the transcription of council M0 §2 Q1 (4/4).
- [x] T-review One independent seat reviews T2–T4 before T merges; verify the catch-rate row.

### W — tests only

- [x] W1 `test_web_modules.py` (`TestClient`): Labs absent with empty lockfile, present after
      install, start payload shape; `js/module-labs.test.js`; verify all red (no routes yet).
      Red kept.

## 3. Wave 2 — W implements and assembles

- [x] W2 `web/routes/modules.py` + `_options.py` entry; Labs in `index.html`/`components.js`/
      `style.css` + `static/js/labs.js`, hidden when the lockfile is empty; verify W1 tests
      green and `just test-js` green. G.
- [x] W3 Register `module` and `drill` groups in `cli/__init__.py`; include the router in
      `web/app.py`; verify `studyloop module --help` and `studyloop drill --help` and the API
      route table. G.
- [x] W4 `e2e/test_module_labs_journey.py`: list → start inside the one claimed session →
      cancel → reload re-attaches → keyboard (Tab/Shift-Tab/Escape) → module removed → Labs
      gone; explicit module timeout; verify green under `just e2e` (machine lock; run alone).
      Red kept.
- [x] W5 Docs/changelog reconciliation (docs lease — free since 6a3f45d2; serialise after S3); acceptance test
      `acceptance/test_module_kdrill_live.py` gated `STUDYLOOP_ACC=1 STUDYLOOP_LIVE=1` with a
      sentinel-cluster assertion; UAT rubric for Personas A and B under `acceptance/uat/`;
      verify `just docs` strict and the acceptance test skips cleanly without the env vars. G.
- [x] W-review One independent seat reviews W2–W5 before W merges; verify the catch-rate row.
      gpt-5.6-sol 3fb086ee (do not merge, 10 raised); all ten fixed red-first in b8f0d7b5;
      gate `evidence/W/merge-gate.txt` (7935 passed, 0 failed); merged to local main 989b1867.

## 4. Wave 3 — representative user testing, live proof, release proof

- [ ] U1 `just testacc` Persona A and Persona B scripted journeys (design.md §6), budgets 6 and
      8 minutes; verify artifacts (screenshot, HTML, console, server log, CLI transcript,
      lockfile diff, envelope) are produced on a forced failure.
- [ ] U2 `just testuat` — owner runs both personas twice against the rubric; verify sign-off
      recorded under `evidence/uat/`.
- [x] K0 `modules/cluster.py`: core-created disposable kind cluster for `target.kind: kubeconfig-context`
      (provision before `setup`, one-context kubeconfig 0600 in the attempt dir, teardown after `cleanup`
      and on every failure path, never touch a cluster it did not create); offline tests with a fake
      `kind`; verify the live acceptance test still skips cleanly. Gap found by lane W (W gap 7).
      Brief `briefs/K0-cluster-provisioning.md`. G.
- [ ] K1 Bruno's converted `studyloop-module-kubernetes-drills` at a frozen sha passes
      `studyloop module check`; verify the `--json` report is stored under `evidence/kdrill/`.
- [ ] K2 Owner runs `acceptance/test_module_kdrill_live.py` with Docker + kind: setup, check,
      cleanup complete; the `studyloop-*` cluster is gone; the sentinel cluster remains;
      verify the log is stored under `evidence/kdrill/`.
- [ ] **M2 council** — four seats audit the seven DoD items against evidence, the UAT
      artifacts and the scope exclusions; coordinator arbitrates; verify each DoD item is
      marked held/not-held with a pointer to its evidence.
- [ ] 4.1 Archive this change to `openspec/changes/archive/2026-xx-xx-module-contract-v1/`
      once M2 holds; verify `CHANGELOG.md` names the contract version and the deferrals
      (browser Check progress → v1.1; view-only credential + grants → v2).

## 5. Deferred (not tasks here)

v1.1 browser **Check progress** (HTTP consent endpoint, one-use challenge, CSRF/same-origin,
active-session binding); v2 view-only credential + attempt-scoped grant; stage-2 SQL lab and
its `duckdb-database` target kind; stage-3 `studyloop-module-index`.
