# Council record — Stage 3 (the red R-10 security test on `main`)

**Date:** 2026-09-10 · **Commits:** `d1981f8a` (capture fix), `83ceafee` (council-driven strengthening),
both on `main`, parent `00ff7c86`. **Cadence:** full three seats per the plan council's ruling for
Stage 3. Returned: `openai.gpt-6-astra` (ACCEPT-WITH-CORRECTIONS, 3 MINOR, 58 s), `qwen3-coder` (ACCEPT,
1 MINOR, 7 s). `grok-4.6`: attempt 1 produced no output in 20 minutes and was stopped (the runner then
held the two finished seats until the slowest returned — fixed in the runner template so each seat
writes on completion); attempt 2 was still generating when this record was written. Its review, if it
lands, is arbitrated in the next stage's record. No seat raised BLOCKING or MAJOR.

## What the plan said vs what the artefact said

The plan (and all three plan-council seats, Q6) hypothesised the launcher was putting a literal
`env:<secret>` token on the child's command line. That hypothesis was marked UNVERIFIED and the
instruction was to read the test and the spawn site first. Reading them:

- **The launcher was already correct.** `start_web_background` (`orchestrator.py:227`) builds `cmd`
  without the password and passes `STUDYLOOP_WEB_PASSWORD` in the child's `env`. Unchanged by this stage.
- **The red was a test-capture defect exposed by the sandbox.** The fake child recorded its argv via
  `ps -p $$ -o command=`. In this environment `/bin/ps` is denied. Reproduced **inside a pytest run**
  with a throwaway copy of the old fake child that also recorded `ps`'s exit status:
  `MARKER_LINES= ['ps_exit:126', 'env:s3cr3t-pw', 'done']`,
  `PS_STDERR= .../fakebin/studyloop: line 2: /bin/ps: Operation not permitted`.
  So the argv line was empty, the env echo became `lines[0]`, and `"s3cr3t-pw" not in argv_line`
  fired on the env line — the observed `'s3cr3t-pw' not in 'env:s3cr3t-pw'`. A false positive
  indistinguishable in a log from the leak the test exists to catch.
- The other two `ps` call sites in the package (`orchestrator._kill_port_occupant`, `session/cleanup.py`)
  are inside `try/except (TimeoutExpired, ValueError, OSError)` and degrade safely; no other test
  depends on `ps`.

The earlier `env:<secret>`-in-argv hypothesis is recorded here as **UNVERIFIED and now superseded by
evidence**, not as a leak that was fixed.

## The fix (test only)

`d1981f8a`: the child records `printf 'argv:%s\n' "$0 $*"` — its own parameters — instead of
shelling out to `ps`; a positive assertion proves the captured line is the tagged capture before the
negative assertion is trusted.

`83ceafee` (council): a delegating spy on `subprocess.Popen` records the exact argv list the launcher
submits and asserts the secret is absent from **every element** — this covers wrapper shapes (an outer
`sh -c '<secret> …'`) that the child's `$@` cannot see. The child-side capture stays as a second,
independent witness; its positive assertion is reduced to "starts with `argv:` and has a payload",
decoupled from the launcher's option shape.

## Discrimination probes (pytest output retained, launcher restored hash-identical)

```
### clean (launcher at HEAD)
1 passed in 0.49s
### probe A: --password <value> appended to argv
E   AssertionError: password leaked into argv: ['…/fakebin/studyloop', 'web', '--port', '8567', '--lan', '--password', 's3…
1 failed in 0.35s
### probe B: outer sh -c wrapper string carries the secret (child $@ is clean)
E   AssertionError: password leaked into argv: ['/bin/sh', '-c', 'STUDYLOOP_WEB_PASSWORD=s3cr3t-pw exec "$@"', 'sh', '…
1 failed in 0.34s
### restore
orchestrator.py == HEAD (a0773098627c == a0773098627c)
### restored
1 passed in 0.47s
```

Probe B is the shape astra's F1 named; the `d1981f8a` test alone would have **passed** it (the child's
parameters are clean), which is why `83ceafee` exists.

## Pinned baseline (studyloop package, `-p no:cacheprovider`, same machine, ~3 min each)

| | red node ids | of which |
|---|---|---|
| before (`00ff7c86`) | **31** | this test + 16 second-brain/vault (`test_cli_brain` 7, `test_obsidian_vault_isolation` 3, `test_second_brain_cli_core` 2, `test_config_init_second_brain`, `test_context_consumer_scope`, `test_doctor_second_brain`, `test_graph_context_scope`) + 14 journey errors (`test_journey_world_guards` 9, `test_xtiles_learners_week` 3, `test_obsidian_learners_week`, `test_xtiles_prompt_inputs`) |
| after (`d1981f8a`) | **30** | the same set minus this test; **0 added** (node-id set comparison) |

The remaining 30 are asserted environment-dependent (second-brain vault isolation and xTiles/Obsidian
journeys on the owner's machine) — **that classification is still by name, not by root cause**; the
plan council's F6/F10 leave it for Stage 10 to account for individually. This stage touched one test
file (`git diff --name-only 00ff7c86 83ceafee` = `packages/studyloop/tests/test_session_start.py`,
`.secrets.baseline` line-number renumbering only), so it cannot have introduced a product regression.

## Dispositions

| seat / id | severity | finding | disposition |
|---|---|---|---|
| astra F1 | MINOR | `"$0 $*"` is shell parameters, not kernel argv; a wrapper `-c` string carrying the secret would satisfy the positive assertion | **ACCEPT — fixed in `83ceafee`** with the Popen spy (probe B proves it) and an honest comment. |
| astra F2 | MINOR | positive assertion over-couples to `" web "` and `--lan` | **ACCEPT — fixed in `83ceafee`**: `startswith("argv:") and payload`. |
| astra F3 | MINOR | probe execution, restoration and target pass UNVERIFIED from the brief | **ACCEPT — evidence attached above** (probe transcript, blob hash equality, `1 passed`). |
| astra Q1 | — | attribution of the failure to `ps` denial inside *pytest* UNVERIFIED | **ACCEPT — closed**: in-pytest reproduction shows `ps_exit:126` and the env line as `lines[0]`. |
| astra Q3 | — | `env=None` when password is empty inherits a possibly-set parent `STUDYLOOP_WEB_PASSWORD` — separate contract question | **NOTED, not changed.** Correct observation; inheriting the parent's env is the existing contract for an unauthenticated launch and is not a leak into argv. Recorded for the Stage 10 hand-off list as a product question, not a Stage 3 defect. |
| astra Q6 | — | do not rewrite the earlier hypothesis as an established leak | **ACCEPT** — worded above. |
| qwen F1 | MINOR | show the full probe output | **ACCEPT — attached above.** |
| qwen Q4 | — | `--lan` coupling could cause a false negative | Partly wrong: extra conjuncts cannot cause a false *negative* (they only reject more), as astra noted; they cause spurious failures. Coupling removed regardless. |

## Stage 3 finish line

Target test green on the correct launcher; discriminates against two leak shapes; pinned red set
31 → 30 with the target the only id removed and none added; gates (ruff check, ruff format, pyright)
green on the touched file. Full-suite gates on both packages are Stage 10's job and were not re-run here.
