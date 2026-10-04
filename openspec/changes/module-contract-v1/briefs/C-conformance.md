# Lane C — conformance (`module check`) + lifecycle (`module new/add/list/remove`) + doctor probes

Read `00-common.md` first. Then `proposal.md` §5.2 (manifest), §5.4 (prerequisite enum),
§6 (MC001–MC016 — the rule table), §7 (CLI surface), and `design.md` §2–§5.

| | |
| --- | --- |
| Branch | `feat/module-conformance` |
| Worktree | `/Users/ataylor/code/personal/tools/studyloop-wt/module-conformance` |
| Base | `git rev-parse HEAD` at start — record as `Base: <sha>` in your first commit body |
| Merge position | after S has merged (rebase onto `main` then); independent of R unless R imports your manifest types, in which case you merge first |
| DoD items | 2 (`module check`), 4-CLI (`module add`), §5.4 probes |
| Wave-0 scope | **C1 only** — fixtures, interface stubs and red tests. No engine. Stop after C1 and report. |

## Owned globs (repo-relative)

- `packages/studyloop/src/studyloop/modules/__init__.py` (you create it — one docstring line)
- `packages/studyloop/src/studyloop/modules/{manifest,check,scaffold,store}.py`
- `packages/studyloop/src/studyloop/cli/_module.py`
- `packages/studyloop/src/studyloop/doctor/modules.py`
- `packages/studyloop/src/studyloop/cli/_doctor.py` — **one registration line only, C5, not this wave**
- `packages/studyloop/tests/test_module_check.py`, `test_module_lifecycle.py`, `test_module_cli.py`
- `packages/studyloop/tests/fixtures/modules/**`
- `openspec/changes/module-contract-v1/evidence/C/**`

## Forbidden

`modules/{runner,consent,attempt}.py` (R), `content/schemas.py` (S), anything under `session/`,
`web/`, `cli/__init__.py` (W), `learning/`, all `docs/`, `mkdocs.yml`, `CHANGELOG.md`.

## C1 — fixtures + interface stubs + red tests (one commit; pre-commit passes; `just test` may be red on this branch)

1. **Fixtures** under `tests/fixtures/modules/`: `valid-scaffold/` — a complete, minimal, offline
   module (`module.yaml`, `decks/*.json` with one `echo`-based drill whose check is
   `scripts/check.sh` exiting 0, `README.md` with the four required headings from proposal
   §5/§6 MC011, `LICENSE`, `CHANGELOG.md`, `mentor/brief.md`); then `mc001/` … `mc016/`, each a
   copy of the valid module **breaking exactly one rule**, each with a `repaired/` twin that
   passes. Keep fixtures tiny. Nothing in a fixture may look like a secret except `mc009/`,
   whose fake secret must be an obviously synthetic pattern that **detect-secrets does not
   flag at commit** — if the hook flags it, change the fixture, never the baseline.
2. **Interface stubs** (the only production code allowed): `modules/__init__.py`;
   `modules/manifest.py` with the Pydantic `ModuleManifest` (`extra: forbid`) **as proposal
   §5.2 specifies** — this one may be real, it is a schema not an engine; `modules/check.py`
   with `Finding(rule_id: str, message: str, path: str)`, `CheckReport(ok: bool, findings: list[Finding])`
   and `check_module(path: Path) -> CheckReport: raise NotImplementedError`. Decide the exact
   shapes by what your tests need and write them down in the module docstrings.
3. **Red tests** `tests/test_module_check.py`: one parametrised test per fixture asserting the
   report is not ok and names **exactly one** rule id `MCnnn`; one per `repaired/` twin
   asserting ok; one for `valid-scaffold`. Run the file; all red (NotImplementedError). Save
   `evidence/C/check-16-rules.red.txt`. The meaningful red for this lane arrives at C2 when the
   twins prove the engine distinguishes; record that in the evidence then.
4. Verification for the report: `env -u VIRTUAL_ENV uv run pytest
   packages/studyloop/tests/test_module_check.py -q` summary line showing 33 failed
   (16 + 16 + 1), pre-commit green on the commit.

## Not in this wave (for orientation only)

C2 engine + `--json`; C3 `scaffold` + `module new`; C4 `store` + `add/list/remove` with
`modules.lock.json` written only after `check` passes and git provenance read locally (no
fetch); C5 `doctor/modules.py` probes `docker`/`kind`/`kubectl` via fake binaries on `PATH`,
`--version` only; C6 Typer group **exported, not registered** (W registers it). Each of those is
a gate-G commit with its own red evidence.

## Contract gaps to watch for (escalate, do not resolve)

A rule in §6 that cannot be checked from the module directory alone; a required README heading
list that §6 does not actually state; a prerequisite id the enum lacks; any temptation to add
a dependency (YAML parsing: check what the repo already uses before assuming).
