# Lane C independent conformance review — gpt-5.6-sol

## 1. Red first

- C2 conformance/JSON/finding shape: `test_module_check.py`; reds are `check-16-rules.red.txt`, `check-engine-always-fail.red.txt`, and `schema-fixture-integrity.red.txt`.
- C3 scaffold: `test_module_lifecycle.py:41-113`; `scaffold-passes-check.red.txt` proves only three of six tests red.
- C4 store/lifecycle: `test_module_lifecycle.py:140-318`; `add-refuses-unconforming.red.txt` proves only the unchanged-lockfile test red. The remaining ten store tests have no red transcript.
- C5 doctor: `test_module_lifecycle.py:375-454`; `doctor-probes-installed-only.red.txt` proves two tests red and records five already passing.
- C6 CLI/help: `test_module_cli.py`; `cli-help-examples.red.txt` proves two help tests red. The other 17 operational CLI tests have no red transcript.
- Current verification: the three changed suites pass, 86 passed. Untested added/required behaviours are the mutable-tree/symlink snapshot boundary, multiple secrets on one line, importable bytecode/interpreter shebangs, and a real kubectl version probe.

1. `openspec/changes/module-contract-v1/evidence/C/add-refuses-unconforming.red.txt:9` -- red evidence is absent for 35 tests: C3 has 3 already-green tests, C4 has 10, C5 has 5, and the operational CLI has 17 -- add focused adversarial tests and capture genuine failing transcripts before their fixes; record the historical evidence gap explicitly.

## 2. Ownership

`git diff --stat main...HEAD` contains 261 files: 259 owned (13 C evidence files, 235 module fixtures, and 11 owned production/test files, including the allowed `_doctor.py` registration); 2 shared (`specs/optional-modules/spec.md`, `tasks.md`); 0 outside. The task ticks are bookkeeping and the fixture-path spec correction is explicitly directed; the other spec edits are not.

2. `packages/studyloop/src/studyloop/modules/store.py:261` -- `add` checks a live tree, then rereads it for manifest, digest, and copy; a `module.yaml` symlink was verified to pass source conformance, be omitted by copying, and produce an installed snapshot failing MC003, while concurrent mutation can bind digest A to bytes B -- copy once into a private staging directory while rejecting links/special files, then check and digest that staged tree before atomic publication; revalidate any existing digest target.
3. `packages/studyloop/src/studyloop/modules/check.py:621` -- MC009 examines only the first regex match on each line, so `PASSWORD=true API_TOKEN=definitely-secret` passes because the placeholder causes the whole line to be skipped -- run the specified keyword detector, or iterate every match and suppress only the individual placeholder match.
4. `packages/studyloop/src/studyloop/modules/check.py:655` -- MC012 rejects only four filenames and `.py`; a `.pyc` file and a referenced executable with `#!/usr/bin/env python3` both pass, preserving importable/interpreter-executed Python -- reject bytecode/importable artefacts and interpreter shebangs, with repaired-twin tests.
5. `packages/studyloop/src/studyloop/doctor/modules.py:68` -- every tool receives `--version`, but real kubectl has no such flag, so an installed prerequisite can never report its version or enforce `min` -- use a core-owned per-tool argv, e.g. `kubectl version --client --output=json`, and test the real output shape.

## 3. Scope

No registry/index/catalogue code, runtime dependency, allowlist pragma, `--no-verify`, `SKIP=`, hook, `.pre-commit-config.yaml`, or `.secrets.baseline` change appears.

6. `openspec/changes/module-contract-v1/specs/optional-modules/spec.md:29` -- this lane added an MC005 scenario and corrected the MC006 scenario although its brief authorized only the fixture-path wording edit in this shared file -- have the coordinator approve/land those spec corrections separately or remove them from Lane C.
7. `packages/studyloop/tests/test_module_lifecycle.py:287` -- re-adding an id replaces the entry and deletes the old snapshot, behaviour not defined by the proposal -- specify replacement/garbage-collection semantics in the contract before retaining this implementation, or remove the extra behaviour.

## 4. The next lane

1. W depends on `studyloop.cli._module.module_group` and must register it in `cli/__init__.py`; command name/help/exit shapes are its assembly boundary.
2. R (then W) depends on `studyloop.modules.store.LockEntry`, `load_lockfile()`, and `snapshot_dir()`; the digest-to-bytes failure above would invalidate R's execution and consent identity.

Environment note: configured server `@mochi:mochi` was unavailable; it was not needed.

Verdict: do not merge
Findings: 7 raised
