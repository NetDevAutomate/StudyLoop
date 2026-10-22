# Development Environment

<!-- facts: F7 F16 -->

Five tools, one sync, two smoke checks: install uv, just, tmux, Node and Playwright's Chromium,
run `just sync-dev`, then prove that `studyloop` imports from *your* checkout and answers
`--version`. Every command on this page was run on 2026-10-04 and its output is receipted in
`openspec/changes/contributor-guide-v1/evidence/W-A/commands.txt`.

## 1. Install the tools

StudyLoop pins its Python in `.python-version` (3.12; CI also runs 3.13). uv installs that
interpreter for you, so Python itself is not on the list.

| Tool | Needed for | Install |
| --- | --- | --- |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | the workspace venv, every `uv run` | the installer on that page, or `brew install uv` |
| [just](https://github.com/casey/just#installation) | every recipe in `Justfile` | `brew install just`, or your package manager |
| [tmux](https://github.com/tmux/tmux/wiki/Installing) 3.1+ | CLI study sessions, the integration suite | `brew install tmux` / `apt install tmux` |
| [Node.js](https://nodejs.org/en/download) | `just test-js` (CI uses Node 24) | the installer on that page, or `brew install node` |
| Playwright Chromium | the browser suite (`just e2e`) | step 3 below; it is a Python package, not a system install |

Verify each one answers before you go on (`just --version` for just; the others below):

```bash
uv --version
tmux -V
node --version
```

## 2. Sync the workspace venv

Clone the repository (fork first if you will open a pull request — the
[start page](contributing.md#your-first-contribution) shows the fork commands), then:

```bash
just sync-dev
```

`just sync-dev` runs `uv sync --inexact --all-packages --group dev`: both packages in the
workspace plus the dev group (pytest, ruff, pyright, pre-commit). `--inexact` keeps whatever is
already installed, so a later `just sync-*` adds to the same venv instead of removing the extras an
earlier one installed. MkDocs is not in that group: it lives in the `docs` extra, and `just docs`
adds it on demand (`uv run --extra docs mkdocs build --strict`).
Choose a wider sync when you need the other optional extras:

1. `just sync-dev` — enough for the default test suite, lint, typecheck and docs.
2. `just sync-web`, `just sync-content`, `just sync-semantic` — the dev group plus one extra
   (the FastAPI web UI; flashcard/quiz generation; embeddings).
3. `just sync-full` — the dev group plus **every** extra. Slowest; use it when you touch more
   than one surface or want `just preflight` to exercise everything.

A fresh checkout or a fresh git worktree has no venv until one of these runs; before that,
pyright reports hundreds of unresolved imports and `uv run studyloop` builds the venv silently
on first use, which looks like a hang.

## 3. Prove the import and install the hooks

Three checks, in this order. The first one matters most: it proves the `studyloop` you run is
the one in your checkout, not a globally installed copy.

```bash
uv run python -c 'import studyloop; print(studyloop.__file__)'
uv run --group dev playwright install chromium
uv run --group dev pre-commit install
```

1. The import line must print a path **under your checkout** ending in
   `packages/studyloop/src/studyloop/__init__.py`. Any other path means a different install is
   shadowing the workspace: stop and fix the venv (`uv sync --reinstall`) before testing anything.
2. `playwright install chromium` downloads the browser the e2e suite drives. It prints nothing
   when the browser is already present.
3. `pre-commit install` writes the git hook that runs ruff, bandit, detect-secrets, trufflehog
   and pyright at commit time (`.pre-commit-config.yaml`). Install it once per clone; a worktree
   shares its parent's hooks.

## 4. Smoke checks

```bash
uv run studyloop --version
uv run studyloop setup
uv run studyloop doctor
```

`--version` prints `studyloop, version 0.5.0` (the version in `packages/studyloop/pyproject.toml`).
`setup` writes the baseline configuration a session needs; without it, `studyloop study` on a
fresh machine exits 2 with *No context scope configured* (`test_fresh_install_scope.py` pins
this). `doctor` then checks the installation (interpreter, tmux, databases, agent definitions, MCP
registrations). Its exit code: **0** when nothing failed (plain warnings and information still exit
0), **1** when a check failed or a warning is auto-fixable (`--fix` applies the safe fixes), **2**
when a core check failed and cannot be fixed automatically. On a machine with no StudyLoop
configuration expect 1 and a *Fix* column listing what is missing — that is the tool working, not
the command failing. `uv run studyloop doctor --quiet` prints the one-line summary.

You are ready when the import path is yours, `--version` answers, and `just test-js` is green
(a one-second Node run; the Python suites are on the [testing cookbook](contributor-testing.md)).

## 5. If you run agents, or work in a git worktree

Two sandbox facts, verified for this repository (F16):

- **Worktrees.** Prefix `just` and `uv run` with `env -u VIRTUAL_ENV` when a shell has another
  project's venv exported, so the worktree's own `.venv` is used. Run `just sync-dev` in every new
  worktree; the import proof above tells you whether it worked.
- **TMPDIR.** Some agent sandboxes set `TMPDIR` to a directory SQLite cannot open; the symptom is
  hundreds of `unable to open database file` test errors with no code change. Before any test or
  gate run `export TMPDIR="$(getconf DARWIN_USER_TEMP_DIR)"` (macOS) so fixtures land where SQLite
  works. The failures are the sandbox, not a regression.

## 6. Next

- Make a first change: [Start Contributing](contributing.md#your-first-contribution).
- Something refuses to start: [Debugging](contributor-debugging.md), then the
  [troubleshooting page](troubleshooting.md).
- The recipes behind the gates: `just preflight` = lint, typecheck, test, test-js, docs,
  release-consistency, spec-check (F7).
