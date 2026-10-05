# Module contract (v1)

A module is a directory of data -- a manifest, practice decks and the scripts they name --
that StudyLoop validates against seventeen rules (`MC001`-`MC017`), installs as an immutable
snapshot, lists under the Web UI's **Labs** entry and runs one drill phase at a time through
`studyloop drill`, with your consent typed before anything executes. Core never imports or
executes module code as a library. This page is the shipped contract; the design history is in
[Optional Modules (Proposal)](contributor-modules.md).

## Adding a module

1. Scaffold a conforming module with one offline drill. The scaffold passes `module check` as
   written and its check script (`check.sh` under the module's `scripts/`) prints `ready` and exits 0:

```bash
studyloop module new my-drills
```

2. Edit `module.yaml`, the deck under `decks/` and `mentor/brief.md`; keep every phase command as
   one executable under `scripts/` plus literal arguments (no shell operators, see MC015).
3. Run the conformance check from the repository root or in CI. Exit 0 means conforming; exit 1
   lists each finding as `MCnnn <file>:<line>: <message>`:

```bash
studyloop module check ./my-drills
```

4. Install it. The check runs again and nothing is written unless it passes; the snapshot lands
   under the config directory's `modules/snapshots/<digest>` and `modules.lock.json` records the
   id, version and content digest (plus the git remote and sha when the path is a checkout):

```bash
studyloop module add ./my-drills
```

5. Confirm the install and reload the Web UI: the **Labs** entry appears in the sidebar as soon
   as the lockfile lists one module, and disappears when it lists none:

```bash
studyloop module list
```

6. Start the drill from Labs, then run its phases in your own terminal. Each phase shows the
   exact argv and the script's sha256 and asks `Run this phase now?`; there is no `--yes`:

```bash
studyloop drill check my-drills/getting-started/ready-01
```

7. Read the two lines after the result: `Mentor told.` means the check reached the mentor in
   your running session; `Mentor not told: <reason>` names why it did not (for example
   `no_active_session` when no session is live).
8. Remove it when done. The lockfile entry and the snapshot go together:

```bash
studyloop module remove my-drills
```

## Layout

| Path | Required | Rule |
| --- | --- | --- |
| `module.yaml` | yes | manifest, `extra: forbid` (MC001, MC002) |
| `decks/*.json` | at least one | a `PracticeDeck` with deck and task `id`s (MC004, MC014) |
| the module's `scripts/` | when a deck declares a phase | one executable per phase, regular files only (MC007, MC013, MC015) |
| `mentor/brief.md` | yes | the module's only channel into coaching; advisory, labelled as data |
| `README.md` | yes | the headings *Prerequisites*, *What runs*, *Data collected*, *Limits* (MC011) |
| `LICENSE`, `CHANGELOG.md` | yes | MC003 |
| `tests/check.sh` | recommended | the module's own offline test; the scaffold writes one |

No `pyproject.toml`, `package.json`, `setup.py`, entry points or `*.py` anywhere (MC012).

## The manifest

`module.yaml` is read by `packages/studyloop/src/studyloop/modules/manifest.py`:

| Field | Meaning |
| --- | --- |
| `id` | slug, the module id (`module/deck/task` in every command) |
| `contract` | `1` -- the contract version this StudyLoop speaks (MC002) |
| `version`, `title`, `topic`, `license`, `maintainers[]` | required metadata |
| `prerequisites[].id` | one of core's enum `docker`, `kind`, `kubectl` (MC005); `studyloop doctor` probes them, `drill` resolves them on your PATH before asking for consent |
| `capabilities[]` | `terminal`, `setup`, `check`, `cleanup` -- each phase a deck uses must be declared, and every declared one used (MC006, MC016) |
| `target.kind` | `workdir` or `kubeconfig-context` (a core-created disposable cluster; `--context`, `--kubeconfig` and `use-context` in a command fail MC008) |

## Drills

Decks are StudyLoop's existing `PracticeDeck` JSON with six added fields: deck `id`, task `id`,
`solution`, `scaffolding`, `mentorNotes` and `verification.cleanupCommand`. The learner sees a
task's `prompt` and `successCriteria` -- in Labs and in the CLI -- and nothing else; `hint`,
`solution` and `mentorNotes` reach them only through the mentor. A task with a `solution` needs
a `scaffolding` level, and every task needs `expectedLearningOutcome` and at least one success
criterion (MC010). Secret-looking strings anywhere in the module fail MC009.

## How a phase runs

- `setup`, `check` and `cleanup` are each one argv, run with `shell=False` in a per-attempt
  directory with an environment built from scratch: a scratch `HOME`, a minimal `PATH` plus the
  declared prerequisites, `STUDYLOOP_MODULE_ID`, `STUDYLOOP_DRILL_ID`, `STUDYLOOP_ATTEMPT_ID`
  and -- for a cluster target -- `KUBECONFIG` naming exactly one context. The attempt records
  the manifest's `target.kind`; creating that disposable cluster is not wired yet, so a
  `kubeconfig-context` drill is refused after consent and before anything runs.
- Exit codes: `check` 0 passed, 1 failed (task not complete), 2 or more could not run; a non-zero
  `setup` is an error; a failing `cleanup` is shown and the attempt still closes. A timeout is
  an error, never a fail; `timeoutSeconds` applies per phase.
- Output is capped, redacted and kept for the attempt only. A check records a transient
  `practice_check` event -- never a learning record, mastery claim or review item.
- The result is delivered to the mentor as one bounded, labelled `practice_check` block
  (at most 8 KiB, every output line prefixed `| `) through the running session's transport,
  on both the browser terminal and the ACP path. Delivery failure is always shown, never silent.

## Labs

Labs is one generic sidebar entry, visible only while a module is installed. It lists drills
grouped by module, by id and prompt. **Start drill** starts your study session for that drill --
or binds the drill to the session already running -- and shows the exact commands to run in your
terminal; **Cancel drill** drops the drill and leaves the session as it was. Nothing executes
from the browser in v1: checks are triggered from the CLI, and a browser **Check progress**
button is deferred to v1.1 with its own consent surface.

## Not in v1

Installing from a git URL or the Web UI; a module registry or index; automatic checks after
each command; a view-only check credential or standing per-attempt grants; a third `target.kind`.
The conformance engine is `packages/studyloop/src/studyloop/modules/check.py`; the runner is
`packages/studyloop/src/studyloop/modules/runner.py`; the fixture modules the tests use are under
`packages/studyloop/tests/fixtures/modules/`.
