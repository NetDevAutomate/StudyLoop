# Lane K0 — the disposable cluster for `target.kind: kubeconfig-context`

Read first: `briefs/00-common.md`, `proposal.md` §5.5 (the "Kubernetes identity" row: *the attempt's
target is a core-created disposable cluster; core writes a kubeconfig containing exactly that one
context and exports `KUBECONFIG`; learner-owned contexts are never used; the disposable cluster is
the blast-radius boundary*), `council/2026-10-04-m1-arbitration.md` §2 Q2 (prerequisites resolve
to a per-attempt `bin/`), `specs/drill-runner/spec.md`, and `tests/acceptance/test_module_kdrill_live.py`
(the owner's live proof: the **sentinel cluster** `studyloop-sentinel-<hex>` must survive and the
cluster set must be exactly what it was plus the sentinel).

**Why this lane exists.** Lane W found that nothing in core provisions the cluster: `_drill` records
the target honestly since W-review F8, and `runner.build_environment` (runner.py:353-359) already
**refuses** a `kubeconfig-context` attempt without a core-written kubeconfig — so today every
Kubernetes drill is refused before spawn. The owner's live proof (K2) cannot pass without this lane.

Worktree: `/Users/ataylor/code/personal/tools/studyloop-wt/module-cluster`, branch `feat/module-cluster`
(created from `main` after lane W merged). Prove the import path first. Red-first as every lane:
failing test → `evidence/K0/<name>.red.txt` (command line 1, sha + UTC) → implementation →
`.green.txt`; pre-commit through `git commit`; nothing pushed; nothing written to the main checkout;
no edits to `specs/**` (the coordinator amends the drill-runner spec) or `tasks.md` beyond ticking K0.

## Owned globs

- `packages/studyloop/src/studyloop/modules/cluster.py` (new)
- `packages/studyloop/src/studyloop/cli/_drill.py` — the `_open_attempt` / `run_drill_phase` block
  that opens and closes the attempt (W's `target=` wiring and R's prerequisites wiring stay)
- `packages/studyloop/tests/test_module_cluster.py` (new), one case in `tests/test_module_drill_cli.py`
- `packages/studyloop/tests/fixtures/modules/k8s-offline/**` (new fixture module with
  `target.kind: kubeconfig-context`, prerequisites `kind`, `kubectl`, `docker`; scripts that only
  echo `$KUBECONFIG` and `kubectl config current-context`)
- `openspec/changes/module-contract-v1/evidence/K0/**`; `tests/fixtures/lane_ownership.yaml` — add a
  `K0` row with exactly these paths (coordinator-granted; comment it)

Forbidden: everything else under `modules/`, `session/`, `web/`; the acceptance test (it describes
the blast radius you must respect — read it, do not edit it); any network access; any real `kind`
or `docker` invocation in the default test tier.

## Behaviour (`modules/cluster.py`)

1. `provision(attempt, *, tools) -> ClusterHandle`: run `kind create cluster --name studyloop-<attempt-id-prefix>
   --kubeconfig <attempt>/kubeconfig --wait 120s` through the resolved `kind` binary from the
   per-attempt `bin/` (reuse `runner.resolve_prerequisites`; never a bare name, never the learner's
   PATH at spawn), argv as a list, `shell=False`, stdin DEVNULL, stdout/stderr captured and capped,
   a hard timeout (default 300 s), `start_new_session=True`. The kubeconfig is written by kind into
   the attempt directory; `provision` then **rewrites it to exactly one context** (the new
   cluster's), mode `0o600`, and returns the path. `Attempt.kubeconfig` is set from it (the attempt
   store already persists `kubeconfig`).
2. The cluster name is derived from the attempt id, prefixed `studyloop-`, never from module text;
   a name that already exists is a refusal (`ClusterError`), never a reuse.
3. `teardown(handle)`: `kind delete cluster --name <name>` with the same discipline; runs after
   `cleanup` **and** on every failure path after a successful create (setup error, check timeout,
   consent refused on a later phase, `KeyboardInterrupt`); the kubeconfig file is removed; a
   teardown failure is reported as `ERROR` naming the cluster so the learner can delete it by hand —
   never silently.
4. Never touch any cluster the attempt did not create: no `kind get clusters` filtering by prefix to
   delete "stale" ones (the sentinel test exists to catch exactly that). Listing is read-only and
   used only to refuse a name collision.
5. Where in the flow: `run_drill_phase` for `setup` on a `kubeconfig-context` attempt provisions
   BEFORE the consent prompt text is shown (the prompt names the cluster and the kubeconfig path),
   `check` reuses the attempt's recorded kubeconfig, `cleanup` tears down after the phase. The
   runner's env then carries `KUBECONFIG` via the existing runner.py:353-359 branch — do not touch it.
6. Prerequisites: `kind`, `kubectl`, `docker` are resolved up front for this target kind; an
   unresolvable one refuses before any consent (ERROR naming the tool), matching M1 Q2.

## Tests (default tier, offline)

A fake `kind` shell script on a scratch PATH that records its argv to a log, writes a two-context
kubeconfig at `--kubeconfig`, and honours a `FAKE_KIND_FAIL=create|delete` env var; a fake `kubectl`
that prints its `KUBECONFIG`. Reds: provision argv exactly as specified (list, resolved path, no
shell); the kubeconfig is rewritten to one context and `0o600`; name collision refused; teardown on
each failure path; teardown failure surfaces as ERROR naming the cluster; the end-to-end
`studyloop drill setup k8s-offline/…` (CliRunner, consent `y`) shows the cluster name in the prompt
and the child sees `KUBECONFIG=<attempt>/kubeconfig`; `cleanup` deletes; a `workdir` module never
calls `kind`. Mark anything needing a real kind `integration` and skip without it — but there
should be none.

## Gate before you report

`uv run pytest packages/studyloop/tests/test_module_cluster.py packages/studyloop/tests/test_module_drill_cli.py
packages/studyloop/tests/test_module_runner.py packages/studyloop/tests/test_module_lane_seams.py
packages/studyloop/tests/test_lane_ownership.py -q -p no:cacheprovider`; `just lint && just typecheck`;
the acceptance test still skips cleanly: `STUDYLOOP_ACC= STUDYLOOP_LIVE= uv run pytest
packages/studyloop/tests/acceptance/test_module_kdrill_live.py -q -p no:cacheprovider`. The coordinator
runs the full preflight at merge. Report ≤ 700 words: commits, red/green list, the exact `kind`
argv for create and delete, the one-context kubeconfig rewrite in five lines, every gap you decided.
