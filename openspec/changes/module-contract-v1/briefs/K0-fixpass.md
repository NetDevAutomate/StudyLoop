# Lane K0 — fix pass after the K0 review (gpt-5.6-sol, do not merge, 11 raised)

Read first: `council/2026-10-05-review-K0-gpt-5.6-sol.md` (every code finding verified by the
coordinator), then the rulings now in the specs: `specs/drill-runner/spec.md` (the amended
"disposable cluster" requirement — its new paragraph and two scenarios are your contract for this
pass) and `specs/optional-modules/spec.md` + `proposal.md` §6 (new rule MC017). They are on `main`
at 0891e5c3: run `git merge main` in your worktree first (no code conflicts expected).

Same rules as every lane pass: red-first per item (red transcript with the command on line 1 and
sha + UTC on line 2, then the fix, then green), commit after every item, pre-commit at commit time
(re-add and retry when a fixer rewrites a transcript), never `--no-verify` or `SKIP=`, stage
specific paths, never push, never write outside your worktree, no nested sub-agents, no real
`kind`/`docker`/`kubectl` in the default tier. Env: `export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"`,
mise shims + `/opt/homebrew/bin` first on PATH, `env -u VIRTUAL_ENV uv run …`.

Items marked **GRANT** touch files outside your globs: the coordinator grants exactly the edit
named, nothing else in that file. Add each granted path to your K0 row in
`tests/fixtures/lane_ownership.yaml` with the comment `# coordinator-granted, K0-review F<n>`.

## Order

1. **F11 first — make the guard police this pass.** GRANT `tests/fixtures/lane_ownership.yaml`
   `branches:` → add `feat/module-cluster: K0`. GRANT `tests/test_lane_ownership.py` — only the
   `_MODULE_CONTRACT_BRANCHES` constant (and whatever that constant is compared against) so
   `test_fixture_branch_map_matches_design_and_points_at_real_lanes` admits the K0 branch; the
   S-owned test's logic stays. Red: the guard currently SKIPS on your branch (`gate-pytest.txt`);
   capture `test_lane_stays_in_its_lane` running and policing after the mapping.

2. **F1 — failed-create rollback** (`cluster.provision` / `_undo_after_failed_create`). Ruling:
   after a `kind create` that did not succeed, delete ONLY when core can prove it created the
   cluster — the attempt's own kubeconfig (`<attempt>/kubeconfig`, which only our kind invocation
   could have written there) exists and names context `kind-<name>`. Otherwise run NO delete:
   re-list read-only and, if the name now exists, report "a cluster named X exists that core
   cannot prove it created" plus the exact by-hand command; if it does not exist, report the
   create failure alone. Red: fake kind whose create fails WITHOUT writing the kubeconfig → zero
   `delete` argv in the log; fake kind whose create fails AFTER writing it (`--wait` timeout
   shape) → exactly one delete.

3. **F3 — a failed delete must not destroy the recovery credential.** In `teardown` and
   `_undo_after_failed_create`: unlink the kubeconfig ONLY when the delete succeeded; on failure
   keep it, and make `_by_hand` take the handle and print
   `kind delete cluster --name <name> --kubeconfig <attempt>/kubeconfig`. Red:
   `FAKE_KIND_FAIL=delete` leaves the kubeconfig in place and the ERROR text contains
   `--kubeconfig <path>`.

4. **F4 — every exception after a successful create tears down.** In `provision`: wrap
   everything after a successful create in `try/except BaseException` (not only `ClusterError`
   from the rewrite — `_one_context` raises `ValueError` on a malformed document, and a
   `KeyboardInterrupt` can land before `_Disposable` exists in `_drill`): run the (now F3-safe)
   teardown and re-raise the ORIGINAL exception with the cluster name attached. In
   `_drill._provision_cluster` / `_attach_cluster`: any `BaseException` between a successful
   provision and the `_Disposable` being registered tears down. Red: a fake kind that writes a
   kubeconfig whose contexts are misnamed (rewrite raises) → one delete and the error still names
   the cause; a `KeyboardInterrupt` injected right after provision (monkeypatch) → one delete.

5. **F2 — canonical records before destructive use.** GRANT
   `src/studyloop/modules/attempt.py` for exactly two things: (a) a public
   `AttemptStore.set_kubeconfig(attempt, path) -> Attempt` that `_drill` calls instead of
   `store._read/_write` (delete `_record_kubeconfig`'s private access); (b) in record loading,
   reject a record whose `attempt_id` is not the file's stem, whose `attempt_dir` is not
   `<store root>/<attempt_id>` (resolved, no symlink), or whose `kubeconfig`, when set, is not
   `<attempt_dir>/kubeconfig` — raise the store's existing error type naming the field; never use
   such a record. In `cluster.handle_for`: refuse (`ClusterError`) a kubeconfig path that is not
   `kubeconfig_path(attempt)`. Red: a hand-edited record pointing `kubeconfig` at a file under
   `tmp_path` and `attempt_id` at another id makes `drill cleanup` refuse BEFORE any kind argv is
   recorded, and that file is untouched.

6. **F5 — every error class on `check` tears down** (spec: exit ≥ 2, timeout, output cap →
   delete + close; exit 1 keeps). In `_drill`'s close logic replace the `result.timed_out`
   special case with the error-class test (use the runner's `ExitClass`/result fields; do not
   re-derive from the raw code). Red: fake check exiting 2 → one delete, attempt closed with the
   reason; exiting 1 → no delete, attempt open.

7. **F9 — a pre-consent refusal opens NO attempt record.** Move both refusals (a `check` with
   nothing open; an unresolvable core tool) BEFORE `store.open`. GRANT
   `tests/test_module_lane_seams.py` — only
   `test_a_kubeconfig_context_module_records_its_target_and_is_refused_before_spawn`
   (~lines 285–306): assert NO attempt record exists after the refusal; keep the refusal text and
   exit-1 assertions; say in its docstring that it pins the K0 behaviour. Your own test G
   docstring changes to match. To keep that seam test independent of kind/docker being installed,
   use an injectable tool resolver or put the fake tools on PATH in the fixture — your call, say
   which.

8. **F7 — allowlisted environment for core's own kind call.** Replace `dict(os.environ)` in
   `_kind_env` with an allowlist: `HOME`, `USER`, `LOGNAME`, `PATH` (kind's dir first, then the
   learner's), `TMPDIR`, `TERM`, `LANG` and every `LC_*`, every `DOCKER_*`, every `KIND_*`,
   `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY`/`ALL_PROXY` in both cases, `SSL_CERT_FILE`,
   `SSL_CERT_DIR`, `REQUESTS_CA_BUNDLE`, `CURL_CA_BUNDLE`, `XDG_CONFIG_HOME`, `XDG_RUNTIME_DIR`;
   never `KUBECONFIG`. Red: with `AWS_SECRET_ACCESS_KEY=probe` and `KUBECONFIG=/x` in the parent
   env, the fake kind's recorded environment contains neither and does contain `DOCKER_HOST`
   when set.

9. **F6 — conformance rule MC017.** GRANT `src/studyloop/modules/check.py` for exactly one new
   rule method + its registration (follow the MC016 pattern near lines 619–635: stable id
   `MC017`, message naming the task and the missing phase command, path/line of the deck task)
   and the docstrings' `MC001-MC016` → `MC001-MC017` (lines 4, 150). GRANT
   `tests/fixtures/modules/mc017/**` — a broken/repaired pair in exactly the shape of `mc016/`
   (read `mc016/` and `tests/fixtures/modules/README.md` first; add the MC017 row to that
   README). GRANT `tests/test_module_check.py` — only the cases that enumerate rule ids or
   iterate the fixture pairs. GRANT the range bump `MC001-MC016` → `MC001-MC017` ONLY in:
   `src/studyloop/cli/_module.py` (lines 33, 67), `docs/module-contract.md` line 4 ("sixteen
   rules" → "seventeen rules"), `docs/cli-reference.md` line 550, `docs/contributor-modules.md`
   line 36; then `just docs` strict and the docs drift tests. Red: `module check` on the broken
   fixture reports MC017; the repaired one, `k8s-offline` and `valid-scaffold` report nothing new.

10. **Not in this pass.** F8 (live output cap on core's kind call) is a recorded FOLLOW-UP: kind's
    output is core's own tool's, not module-controlled. F10 is satisfied by the reds above — each
    of items 2–9 gets its own red/green pair under `evidence/K0/`. Do not change the
    decline-on-check teardown, the exit-1 keep, or the prompt-line position (ruled not defects).

## Gate before you report

In order: the brief's pytest selection PLUS `tests/test_module_check.py`,
`tests/test_module_lifecycle.py`, R's attempt-store tests (`ls tests | grep -i attempt`),
`tests/test_docs_drift.py`, `tests/test_contributor_docs.py`; `just lint typecheck`; `just docs`;
the acceptance test still skips. Save the transcripts under `evidence/K0/` as
`fixpass-gate-*.txt`. Tree clean. `just spec-check` is the coordinator's.

Report ≤ 600 words: commits; one line per finding with its red/green files; every granted file you
touched and the exact hunk scope; any place you judged a ruling wrong against the code (cite
`file:line`).
