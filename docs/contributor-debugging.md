# Debugging

<!-- facts: F7 F16 -->

When something in StudyLoop misbehaves, work the same five steps every time — reproduce, isolate,
read the error, check your assumptions, trace — and let one loud test run do the talking. This page
gives you the commands for each step, the paths where state actually lives, and how to read the two
failure messages new contributors hit first: a pre-commit hook and the `just e2e` lock.

## 1. The five-step frame

1. **Reproduce.** Make it fail on demand before you change anything. For a product bug that means
   one command or one Web UI action with synthetic data; for a test that means the single test id
   (step 2). A bug you cannot trigger twice is a hypothesis, not a bug.
2. **Isolate.** Shrink to the smallest input, file or test that still fails. In pytest, `-x` stops at
   the first failure and `-k <expr>` narrows by name; in the product, a fresh `HOME` or a
   `STUDYLOOP_SESSION_DIR` pointed at an empty directory removes your real configuration from the picture.
3. **Read the error — all of it.** Pytest prints the assertion, the captured output and the locals;
   the first line of the traceback is rarely the cause. Doctor and the CLI print a *Fix* column:
   read it before searching.
4. **Check assumptions.** Print or assert the value you "know". The commonest wrong assumption here
   is which `studyloop` is running: `uv run python -c 'import studyloop; print(studyloop.__file__)'`
   must print a path under your checkout ([Development Environment](contributor-environment.md)).
5. **Trace.** Follow the request through the layer that owns it — the
   [code map](contributor-code-map.md) names the layers — with `-vv`, a breakpoint, or a
   `logging` call you remove before committing.

## 2. Run one test, loudly

Name the test by its node id, stop at the first failure, and ask for everything pytest knows:

```bash
uv run --group dev pytest packages/studyloop/tests/test_session_state.py::test_read_session_state_corrupt_json -x -vv -p no:cacheprovider
```

- `-x` stops at the first failure; `-vv` prints the full diff of the failing assertion;
  `-p no:cacheprovider` keeps pytest from writing a `.pytest_cache` next to the tests.
- Drop the `::test_…` suffix to run the whole file; add `-k corrupt` to run the tests whose name
  matches. Run the file in its natural order before you call something a regression — some suites
  build state across tests and fail alone for reasons unrelated to your change.
- The default run deselects `integration`, `e2e`, `acceptance`, `uat` and the live markers (F7). A
  test with one of those markers does not run until you pass `-m integration` (and so on) yourself.

## 3. Where state and logs live

StudyLoop writes no log file of its own: CLI commands print to the terminal, and `studyloop web`
runs uvicorn at log level *warning*, so server errors appear in the terminal that started it. State
is on disk, in two places:

| What | Path | Source |
| --- | --- | --- |
| Configuration | `~/.config/studyloop/config.yaml` | `packages/studyloop/src/studyloop/settings.py` (`CONFIG_DIR`) |
| Sessions and review database | `~/.config/studyloop/sessions.db` | `settings.py` (`DEFAULT_DB`) |
| Live session state | `~/.config/studyloop/session-state.json`, `session-topics.md`, `session-parking.md` | `packages/studyloop/src/studyloop/session_state.py` |
| One study session's files | `~/.config/studyloop/sessions/study-<slug>-<id>/` | `packages/studyloop/src/studyloop/session/start.py` |
| Engine state | `~/.local/share/studyloop/state.json` (`DEFAULT_STATE_DIR`) | `settings.py` |
| The one log file | `~/.config/studyloop/export-hook.log` (the harness session-export hook) | `packages/studyloop/src/studyloop/installers.py` |

`STUDYLOOP_SESSION_DIR` relocates the session-state files; tests set it, together with `HOME` and
`XDG_*`, to a `tmp_path`, and the suite **fails the run** if a test touches your real
`~/.config/studyloop`. If that guard fires, the test is wrong, not the guard.

The quickest read of the whole installation is `uv run studyloop doctor` — it names the paths it
checked in its *Details* column and exits 1 while a check has failed or a warning is auto-fixable
(2 for a core failure it cannot fix; plain warnings exit 0). `--json` gives the same table
as data for an issue report (remove private paths first).

## 4. Read a pre-commit failure

The hooks run at commit time; to run them on one file first:

```bash
uv run --group dev pre-commit run --files docs/contributor-debugging.md
```

A failing hook looks like this (a deliberate trailing space, run in a scratch clone):

```text
trim trailing whitespace..........................................................Failed
- hook id: trailing-whitespace
- exit code: 1
- files were modified by this hook
```

Read it in three lines: the **hook id** tells you which rule; **exit code 1** means the commit was
refused; **files were modified** means the hook already fixed the file — `git add` it and commit
again. Two kinds of hook: the **fixers** (`trailing-whitespace`, `end-of-file-fixer`,
`ruff-format`) rewrite the file and refuse once so you can re-stage; the **reporters**
(`ruff`, `detect-secrets`, `bandit`, `pyright`, `trufflehog`, the AWS-token and commit-author
checks) cannot fix and print the file and line instead; fix the finding, never bypass the hook (`--no-verify` and `SKIP=` are not
used in this repository). The hook list is `.pre-commit-config.yaml`.

## 5. `just e2e` says another run holds the lock

The browser suite takes a machine-wide lock, a directory at `/tmp/studyloop-e2e.lock`, because
two concurrent runs refuse each other's fixed ports (F7). While another run holds it you see:

```text
e2e: another e2e run holds /tmp/studyloop-e2e.lock (pid 12345); waiting 20s
```

Wait for the other run, or check the pid: when the process is gone the recipe prints
`e2e: removing stale lock left by dead pid 12345` and continues on its own. The recipe is `e2e` in
`Justfile`; do not delete the lock while the pid is alive.

## 6. When the sandbox is the bug

Hundreds of `sqlite3.OperationalError: unable to open database file` errors with no code change,
or pyright reporting every import unresolved, are environment faults — a `TMPDIR` SQLite cannot
use, or a worktree with no venv. The fixes are on the
[Development Environment](contributor-environment.md#5-if-you-run-agents-or-work-in-a-git-worktree)
page (F16); apply them, rerun step 2, and only then look at the code.
