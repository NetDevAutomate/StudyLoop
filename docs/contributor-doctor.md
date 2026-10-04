# A Doctor Check

<!-- facts: F7 F11 -->

A doctor check is a function in `packages/studyloop/src/studyloop/doctor/` that takes no arguments,
touches nothing, and returns a list of `CheckResult` rows. It is wired into the one registry built
by `_get_registry()` in `packages/studyloop/src/studyloop/cli/_doctor.py`, and its proof is a unit
test that fakes the thing being checked — a missing import, an absent binary — not the real
machine.

1. Write `check_<thing>() -> list[CheckResult]` in the `doctor/` module for its category.
2. Register it in `_get_registry()` under one of the categories `CheckResult` accepts.
3. Say what is true and what to do; set `fix_auto=True` only if `--fix` can actually do it.
4. Test the check with the lookup faked, and the command with the registry faked.
5. Run `studyloop doctor --help` and the doctor test files; the rows are the JSON contract.

## 1. Where it lives

- `packages/studyloop/src/studyloop/doctor/models.py` — `CheckResult(category, name, status,
  message, fix_hint, fix_auto)`, a frozen dataclass. `status` must be one of `pass warn fail
  info`; `category` one of `core database config agents deps voice updates harness`
  (`VALID_STATUSES`, `VALID_CATEGORIES`); anything else raises at construction. `to_dict()` is
  the shape `studyloop doctor --json` prints, so renaming a field is a contract change.
- `packages/studyloop/src/studyloop/doctor/__init__.py` — `CheckerRegistry`: `register(category)`
  and `run_all()` / `run_category()`. A checker that raises becomes a `fail` row named after the
  function with the message `Checker crashed: …`, so one bad check never hides the others.
- One module per category: `core.py`, `database.py`, `config.py`, `agents.py`, `deps.py`,
  `harness.py`, `voice.py`, `updates.py`, `exporter.py`, `query_encoder.py`, all under
  `packages/studyloop/src/studyloop/doctor/`.
- `packages/studyloop/src/studyloop/cli/_doctor.py` — `_get_registry()` imports every check and
  registers it; `_compute_exit_code()` maps rows to `0`, `1` (any `fail`, or a `warn` with
  `fix_auto=True`) or `2` (a `core` `fail` that cannot be auto-fixed); `_apply_fixes()` is the
  only code `--fix` runs, dispatched by category and name. `updates` is a valid category but
  hidden from `--category` until a release exists.

## 2. The smallest complete example

Read `check_optional_deps()` in `packages/studyloop/src/studyloop/doctor/deps.py` (40 lines).
It walks a dict of optional imports, asks `importlib.util.find_spec()` and emits one row per
dependency: `pass` with an empty `fix_hint` when present, `info` with the exact install command
when absent, `fix_auto=False` both ways because installing is the learner's decision. It reads
no file, runs no process and has no branch that cannot be reached by faking one function.

```bash
uv run studyloop doctor --help
```

## 3. Its test

Three layers, each faking exactly what it needs and nothing more. The pattern is the cookbook's
[unit template](contributor-testing.md#unit-and-cli-template-refusal-means-nothing-executed):
arrange the fake, call the function, assert the rows.

1. The check: `packages/studyloop/tests/test_doctor_deps.py` patches `importlib.util.find_spec`
   three ways (all present, none, one) and asserts statuses by `name`.
   `packages/studyloop/tests/test_doctor_models.py` pins the dataclass contract.
2. The lookup seam: a check that needs a binary is tested by patching the lookup where the check
   calls it — `patch("studyloop.doctor.harness.shutil.which", …)` in
   `packages/studyloop/tests/test_harness_export.py`, `is_tmux_available` in
   `packages/studyloop/tests/test_doctor_core.py` — or by writing an executable shim under
   `tmp_path` and handing the check its path, as `_fake_exporter()` does in
   `packages/studyloop/tests/test_doctor_exporter.py`. Never rely on what is on the developer's
   `PATH`.
3. The command: `packages/studyloop/tests/test_cli_doctor.py` invokes `doctor` with
   `CliRunner` while `_get_registry` is patched to return canned rows, so the exit-code and
   `--json` contracts are tested without running a single real check;
   `packages/studyloop/tests/test_doctor_exit_code.py` pins `_compute_exit_code` and the
   exit-code row in `docs/cli-reference.md`.

```bash
uv run --group dev pytest packages/studyloop/tests/test_doctor_deps.py packages/studyloop/tests/test_doctor_models.py -q
uv run --group dev pytest packages/studyloop/tests/test_cli_doctor.py packages/studyloop/tests/test_doctor_exit_code.py -q
```

`packages/studyloop/tests/test_doctor_integration.py` runs the whole registry through the CLI
with `STUDYLOOP_CONFIG` pointed at a temp file and `urllib.request.urlopen` patched to fail, so
nothing reaches the network or the real configuration.

## 4. The gate that proves it

```bash
uv run --group dev pytest packages/studyloop/tests/test_doctor_*.py -q
```

Every doctor test runs in the default selection, so `just test` and `just preflight` include them
(F7). `uv run studyloop doctor --help` is executed by
`packages/studyloop/tests/test_contributor_guide_drift.py`, and every fenced `studyloop doctor …`
line on the site is resolved against the Click tree by `packages/studyloop/tests/test_docs_drift.py`
(F11), so a new `--category` value or option must be real before it is documented.

## 5. What reviewers look for

- No side effects: the check reads, probes and returns. Repairs live in `_apply_fixes()` behind
  `--fix`, and a row with `fix_auto=True` has a matching branch there — otherwise the summary line
  promises a fix that does not exist.
- Honest wording: `message` states what was observed (`session-export: not found on PATH`), and
  `fix_hint` is a command or a sentence the learner can act on; `warn` is for degraded, `fail`
  for broken, `info` for optional-and-absent — never `fail` for a missing optional extra.
- One row per fact, named stably (`dep_fastapi`, `session_memory_executable_session-export`):
  tests and the JSON consumers key on `name`.
- The unit test fakes the lookup at the seam the check uses and covers present, absent and
  broken; the CLI test fakes the registry, not the world.
- The exit-code table in `docs/cli-reference.md` still matches `_compute_exit_code()` if you
  changed when a row is `fail` or `fix_auto`.
