# Lane R — secure runner, consent, transient attempt recording, `studyloop drill`

Read `00-common.md` first. Then `proposal.md` §5.5 (the execution model — your spec), §5.7
(transient-only recording), §6 MC013 and MC015 (the static halves you enforce at runtime),
§7 (`studyloop drill <phase> <module>/<deck>/<task>`), and `design.md` §2–§5, §7 (M1), §9.

| | |
| --- | --- |
| Branch | `feat/module-runner` |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/module-runner` |
| Base | `git rev-parse HEAD` at start — record as `Base: <sha>` in your first commit body |
| Merge position | after S; after the **M1 adversarial council** has reviewed R2–R5; independent of C unless you import C's manifest types |
| DoD item | 3 |
| Wave-0 scope | **R1 only** — the adversarial red suite. No runner. Stop after R1 and report. |

## Owned globs (repo-relative)

- `packages/studyloop/src/studyloop/modules/{runner,consent,attempt}.py`
- `packages/studyloop/src/studyloop/cli/_drill.py`
- `packages/studyloop/tests/test_module_runner.py`, `test_module_drill_cli.py`
- `packages/studyloop/tests/fixtures/runner/**`
- `openspec/changes/module-contract-v1/evidence/R/**`

**Do not create `modules/__init__.py`** — C owns it. In your worktree `studyloop.modules` is an
implicit namespace package until C merges; imports of `studyloop.modules.runner` work without it.

## Forbidden

`content/schemas.py` (S), `modules/{manifest,check,scaffold,store}.py` (C), `learning/practice.py`
(**untouched** — your path is separate; you only *read* it to prove the reds), `session/**`,
`web/**`, `cli/__init__.py`, all `docs/`, `mkdocs.yml`, `CHANGELOG.md`.

## R1 — adversarial red suite (one commit; pre-commit passes; `just test` may be red on this branch)

Two kinds of red, and the distinction matters:

**(a) Meaningful reds against today's code** — these must fail on their *assertion*:

- `test_drill_writes_no_observation`: drive today's CLI verification path
  (`learning/practice.py:179-188` records a `confident`/`struggling` observation after a check)
  with a trivially passing command against a temporary database/vault, then assert the
  observations table row count is **unchanged**. It fails today because a row *is* written.
  Find the existing test helpers for a temp vault/DB (grep `tests/` for how `practice verify`
  is tested) and reuse them; do not invent a second world.
- `test_runner_never_shell`: spy on `subprocess.run`/`Popen` while today's path runs a
  verification command (`practice.py:282-290`), assert `shell is False`/absent and that argv
  is a list. It fails today because `shell=True` is used.
Save both transcripts: `evidence/R/no-observation.red.txt`, `evidence/R/never-shell.red.txt`.

**(b) Boundary reds against the future runner** — import the stubs you create in
`modules/runner.py`, `modules/consent.py`, `modules/attempt.py` (bodies `raise
NotImplementedError`; signatures and the `ExitClass`/`Attempt`/`Consent` types decided by what
these tests need, documented in docstrings). One test each, named for the attack:

1. shell token in a literal argument (`;`, `|`, `$(`, backticks, `>`): refused before spawn;
2. script path is a symlink / hardlink / outside the snapshot / not a regular file: refused
   (MC013 at runtime);
3. an inherited environment variable (set a canary in `os.environ`) is **not** visible to the
   child; only the documented variables plus a minimal `PATH`, scratch `HOME`/XDG are;
4. script content changed between consent and spawn: the digest re-check refuses;
5. consent replay: a consent object used twice is refused the second time;
6. per-phase `timeoutSeconds` elapses: exit class is *error*, child is terminated;
7. output flood (child writes more than the byte cap): output is truncated, truncation
   recorded, process not left running;
8. exit code `1` maps to "task not complete", `0` to passed, `≥ 2` to error;
9. `cleanup` and `setup` each require a fresh consent — a `check` consent does not cover them.
Save `evidence/R/adversarial-suite.red.txt` (summary line: all failing with NotImplementedError).

Use real subprocesses only for tiny `sh -c`-free scripts you write into a tmp dir in the test
(`#!/bin/sh` files are fine as *targets*; the runner under test must never pass a string to a
shell). No Docker, no network.

Verification for the report: the two pytest summary lines (file-level), pre-commit green.

## Not in this wave (orientation)

R2 argv-without-shell + regular-file + clean environment; R3 consent bound to argv + script
digest + phase + target, re-checked immediately before spawn; R4 exit classes, per-phase
timeouts, streamed caps, redaction before persistence; R5 transient `practice_check` recording
(`test_drill_writes_no_observation` turns green against **your** path); R6 `studyloop drill`.
Then M1: an adversarial council reads R1's suite and your code before anything merges.

## Contract gaps to watch for

The proposal's exact list of environment variables the child receives; what "redaction before
persistence" reuses (the pre-commit detector family or a core helper — check what exists);
where attempts are stored (which database/table the sessions store exposes). Report, do not decide.
