# Lane brief — common part (read this first, then your lane file)

You are one lane of the module-contract v1 build in StudyLoop. The spec is
`openspec/changes/module-contract-v1/proposal.md` (council-amended, commit `54d79e88`); the plan is
`design.md` and `tasks.md` beside it. This file plus your lane file is your whole context:
`include_memory=false` was set deliberately. If something you need is not in these files or in
the repository, **report the gap** in your final report; do not guess.

## 0. Where you work — the one rule that protects everyone else

- Your worktree is named in your lane file: `/Users/ataylor/code/personal/tools/studyloop-wt/module-<lane>`.
  **Every** file you read for editing, every shell command (`working_dir`), every test run and
  every commit happens there.
- The main checkout `/Users/ataylor/code/personal/tools/studyloop` is **read-only reference**.
  It holds another session's uncommitted work (contributor docs, `CHANGELOG.md`, `mkdocs.yml`,
  `agents/kiro/*.json`, `openspec/changes/module-registry-v1/`). Never write there, never
  `git add`/`stash`/`checkout` there, never cd there to run tools.
- Prefix every `just`/`uv` command with `env -u VIRTUAL_ENV` (the sandbox may export a
  `VIRTUAL_ENV` that points at the main checkout's venv). Step 1 in a fresh worktree is
  `env -u VIRTUAL_ENV just sync-dev`, then prove the import resolves inside the worktree:
  `env -u VIRTUAL_ENV uv run python -c 'import studyloop, sys; print(studyloop.__file__)'`
  must print a path under your worktree. If it prints the main checkout's path, stop and report.
- **Sandbox facts (verified 2026-10-04, do not re-diagnose):**
  - The default `TMPDIR` in this sandbox cannot host SQLite (`sqlite3.OperationalError: unable
    to open database file`), which turns the suite into ~400 failures and ~1,600 errors. Before
    **every** test or gate command run `export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"`.
  - With that, the baseline at base `f8c68662` is **7445 passed, 16 skipped, 1 failed**; the one
    failure is `test_fresh_install_scope.py::test_studyloop_study_exits_2_with_the_diagnostic_on_a_virgin_home`
    (tmux is a mise shim that cannot resolve under the test's virgin HOME). It is pre-existing;
    report it as such. Any other red is yours.
  - `mkdocs.yml` uses an `exclude_docs` allowlist: a new docs page needs both a `!/page.md`
    un-exclude line and a nav entry, and ADR files are excluded from the built site by design.
    Both edits are docs-lease territory (§4).

## 1. Settled constraints (C1–C8) — flag a violation, do not re-argue

- C1. The amended proposal is the spec. §5.3 identity fields, §5.5 execution model, §5.7
  transient-only recording + mentor delivery, MC001–MC016, local-path `module add`, browser
  checks in v1.1, view-only credential in v2 are closed decisions.
- C2. Branch names are `feat/…` (yours is given). **Never `lane/…`**.
- C3. Every commit passes pre-commit (all hooks; pyright runs at the **commit** stage — there is
  no pre-push stage) and, for implementing commits, `env -u VIRTUAL_ENV just preflight`
  (`lint typecheck test test-js docs release-consistency spec-check`). Docs and `CHANGELOG.md`
  land in the same change as the code — but see the docs lease (§4).
- C4. Default tests are offline: `addopts` deselects `integration`, `e2e`, `live_*`,
  `acceptance`, `uat`. No Docker, kind, model or network in anything the default lane runs.
- C5. You have full local git control in your worktree: branch, commit. **No pushes.** No
  `reset --hard`, `branch -D`, `clean -f`, force-push, `--amend` of a commit you did not make.
- C6. `uv` only. Never pip/poetry. New runtime dependencies are a contract gap → escalate.
- C7. AuDHD + Socratic rules bind every UI decision: one Labs entry, hidden when no module is
  installed, no overdue counters, no hint/solution/mentor-notes surface outside the mentor.
- C8. **Nothing registry-shaped.** `openspec/changes/module-registry-v1/` is parked; do not read
  it for requirements, do not implement anything from it, no `index.json`, no catalogue code.

## 2. Gate G and the red-first rule

- **Gate G** = pre-commit (all hooks) + `env -u VIRTUAL_ENV just preflight`, run **in your
  worktree**, after every implementing commit. Keep the transcript tail (counts, exit status).
- **Red-only commits** (`tasks.md` items without a trailing "G.": C1, R1, W1) may leave
  `just test` red *on your lane branch at that commit* — they must still pass pre-commit. The
  only production files allowed in a red-only commit are **interface stubs**: the public
  types/signatures the tests need, with every function body `raise NotImplementedError`. No
  logic. (Top-level imports of modules that do not exist fail pyright at commit time; stubs
  are how the red commit stays honest *and* commits.)
- **Red-first evidence:** before a behaviour goes green, run its test and save the failing
  transcript to `openspec/changes/module-contract-v1/evidence/<lane>/<short-name>.red.txt`
  (first line: the exact command; then the output tail, ≤ 120 lines). Commit the evidence
  with the test. A test that was never red is not evidence. A red caused only by
  `NotImplementedError` counts for red-only commits; the *meaningful* reds your lane file
  names must fail on their assertion, not on import.
- Never `--no-verify`, never `SKIP=…`, never edit `.pre-commit-config.yaml`, `.secrets.baseline`
  or any hook to get past a gate. If detect-secrets flags a fixture you created, change the
  fixture. If you must update the baseline for a legitimate reason, run the whole-repo scan
  `detect-secrets scan --baseline .secrets.baseline` with **no file arguments** and show in your
  report that `git diff -- .secrets.baseline` touches only your file's entries.
- Scripted edits (sed/python string replacement) must be followed by `ruff format` on the
  touched files before committing.

## 3. Commits

- ≤ 6 commits per lane, each one logical step, each passing its gate. Subject ≤ 70 chars with
  the repo's prefixes (`feat(modules): …`, `test(modules): …`, `docs(adr): …`); body says *why*.
- Stage specific paths. Never `git add .` / `-A`.
- Your **first** commit body records `Base: <sha>` (the `git rev-parse HEAD` you started from).
- Numbers in commit bodies and reports come from the artifact (test output, `git diff --stat`),
  never from memory.

## 4. Ownership, hotspots, the docs lease

- Your lane file lists **owned** globs (you may create/edit) and **forbidden** globs (never).
  Anything not listed: do not touch without escalating. Until the schema lane's re-keyed guard
  reaches your branch, the brief is the only enforcement — treat it as the guard.
- Hotspots are owned by exactly one lane: `content/schemas.py` (S), `cli/__init__.py` (W),
  `cli/_doctor.py` (C, one line), `web/routes/session/_options.py` (W), `modules/__init__.py` (C).
- **Docs lease:** `docs/`, `mkdocs.yml`, `CHANGELOG.md` have one writer at a time and the lease
  is currently **held by another session** (its edits are uncommitted in the main checkout).
  Do not edit `mkdocs.yml` or `CHANGELOG.md`. The one exception is in the T lane file (a new ADR
  file and one index row — new content, no conflict). Everything else docs-shaped waits.

## 5. Stop and escalate (report, do not improvise) when

- a file you need is not in your owned globs;
- the proposal lacks something you need (a field, a rule, a target kind, a dependency) — that
  is a **contract gap**; describe it precisely and stop that task;
- the gate fails twice for the same reason after one root-cause attempt;
- a test you were told to make red is already green, or cannot be made red for the stated
  reason — say so with the transcript;
- anything would require Docker, kind, a network call, a model call or a push.
Escalation is non-blocking for the rest of your lane: park the item, continue the others.

## 6. Final report (this is what the coordinator reads)

1. Commits: `sha  subject` list, in order, with `git diff --stat` totals.
2. Evidence files written (paths) and what each proves red.
3. Gate transcript tails: pre-commit result per commit; `just preflight` result (counts) for
   implementing commits; for red-only commits, the exact failing-test summary line.
4. Files touched outside your owned globs: must be "none" or an explanation.
5. Deviations from the lane file, contract gaps, open questions, stubs left for the next wave.
6. Verification the coordinator can repeat: the exact commands, with `working_dir`.
Do not claim "tests pass" without the line that says so. Do not summarise the diff; the
coordinator reads the diff.
