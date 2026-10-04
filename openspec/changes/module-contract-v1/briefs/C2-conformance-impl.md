# Lane C — wave 1: conformance engine, scaffold, lifecycle, doctor probes, CLI group (C2–C6)

Read `00-common.md` first (its rules still bind), then `C-conformance.md` (your globs, forbidden
list, the C1 you already did), then this file. Spec you implement:
`openspec/changes/module-contract-v1/specs/optional-modules/spec.md` (amended `4704fd3d` — read it
in full; every one of its scenarios maps to a test you turn green). Proposal §5.1–5.4, §6, §7.

| | |
| --- | --- |
| Branch · worktree | `feat/module-conformance` · `/Users/ataylor/code/personal/tools/studyloop-wt/module-conformance` |
| Start | `git merge --no-edit main` first (main is at `4704fd3d`+; S is merged; spec deltas amended). Stop and report on any conflict. |
| Inherits | your C1: 16 fixture pairs, `valid-scaffold/`, `test_module_check.py` (33 engine reds on the stub, 5 fixture-integrity greens), `modules/check.py` interface stub |
| Done when | C2–C6 ticked in `tasks.md` as written there, every C1 red green, gate G green **end to end** (`just preflight` now runs through because your reds are green — the one allowed red is the virgin-HOME tmux test), report filed |
| Merge | after C-review (one seat); the coordinator merges |

## Rulings on the five gaps you reported (binding; each is now in the spec)

1. **MC009 vs detect-secrets filters:** the engine runs the KeywordDetector with heuristic filters
   disabled, so `export PASSWORD="0123456789abcdef"` in `mc009/broken` IS flagged. Do not change
   the fixture.
2. **MC016 and `terminal`:** `terminal` names the learner's session and is always in use —
   declaring it never fails MC016; `setup`/`check`/`cleanup` declared-but-unused does.
3. **Overlaps:** most specific rule wins — bad `contract` → MC002, bad `prerequisites[].id` →
   MC005, never MC001; anything `PracticeDeck` rejects → MC004; MC010 fires only for `solution`
   without `scaffolding`. Keep `contract: int`, `id: str` in the manifest model and map
   validation errors to rule ids explicitly.
4. **`Finding` gains `line: int | None`** (`None` for file-level faults); `--json` emits it.
5. **MC011 headings** are the `##` headings proposal §5.1 lists, in any order.

Fixture layout stays `mcNNN/broken` + `mcNNN/repaired` (your reasoning holds); update the spec
scenario wording in `specs/optional-modules/spec.md` to `tests/fixtures/modules/mc0NN/broken/` in
your first commit (one-line edit, your lane's spec, say so in the report).

## Tasks (one commit each minimum; red-first where a behaviour is new; `Base:` line in the first body)

- **C2** `modules/manifest.py` (Pydantic, `extra: forbid`, the §5.2 fields; `prerequisites[].id`
  from the closed enum `docker | kind | kubectl`, `capabilities` from the closed set) and
  `modules/check.py`: all sixteen rules with stable ids, `Finding(rule_id, message, path, line)`,
  `check_module(path) -> list[Finding]`, `--json` shape documented in the module docstring. Verify:
  every `mc0NN/broken` fails naming exactly `MC0NN` and nothing else; every `repaired` and
  `valid-scaffold` pass with zero findings; the 33 reds are green.
- **C3** `modules/scaffold.py` + `module new <id>`: writes a module that passes `check` and carries
  one offline `echo`-based drill (`scripts/check.sh` exits 0 with no network, Docker or kind).
  Red first: a test that scaffolds into `tmp_path` and runs `check_module` on it.
- **C4** `modules/store.py` + `module add <path>` / `list` / `remove`: `add` runs `check` first and
  refuses on any finding leaving `modules.lock.json` byte-identical (red first:
  `test_module_lifecycle.py`); copies into an immutable snapshot under the StudyLoop data dir
  keyed by content digest (sha256 over sorted relative paths + bytes); lockfile entry = id,
  version, digest, snapshot path, and when `<path>` is inside a git checkout the remote URL and
  `HEAD` sha read with `git -C <path> rev-parse HEAD` / `git -C <path> remote get-url origin`
  **only** (no fetch, no network; absent remote → fields null); `remove` is idempotent. Snapshot
  files are read-only (0o444; scripts 0o555).
- **C5** `doctor/modules.py`: probes `docker`, `kind`, `kubectl` by running `<bin> --version`
  only, with fake binaries on `PATH` in tests; reports for installed modules' prerequisites only
  (no module installed → no probe runs, no cluster/context touched). One registration line in
  `cli/_doctor.py` (your one allowed edit there).
- **C6** `cli/_module.py`: a Click group (`click.Group` — the CLI is Click with `LazyGroup` mounting in `cli/__init__.py`, NOT Typer; `click.testing.CliRunner` drives it) with `check`, `new`, `add`, `list`, `remove` — **exported,
  not registered** in `cli/__init__.py` (W registers it in wave 2). `test_module_cli.py` drives the
  group object with `CliRunner`. `--help` text is documentation: the docs-drift test will resolve
  fenced `studyloop module …` examples against it once registered, so make the help accurate.

## Cross-lane facts

- R6 (`cli/_drill.py`, lane R) will read your lockfile and snapshot layout: export
  `load_lockfile()`, `LockEntry`, and `snapshot_dir(entry)` from `modules/store.py` with
  docstrings; do not import anything from R's modules.
- The `practice_check` store and the mentor hop are R's and T's/W's — not yours.
- Never run `just e2e`. Run gate G as `just preflight` once your reds are green; while any red
  remains, run the recipes individually and say so.

## Report (common §6 plus)

Per rule: fixture → finding emitted (one line each, 16 lines). The `--json` sample for one broken
fixture. The lockfile sample after `module add` of the C3 scaffold. Gate summary lines. Gaps.
