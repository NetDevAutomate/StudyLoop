# StudyLoop Operational Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the next operational polish wave: cleaner CI setup, self-test smoke coverage, stronger semantic/release gates, CI documentation, ownership mapping, and optional commit-history cleanup.

**Architecture:** Keep the implementation in small, reviewable slices. CI/setup concerns live in workflow and Justfile changes; install smoke concerns live in scripts and contract tests; release consistency remains in one script with focused tests; documentation is split between workflow guidance and ownership mapping.

**Tech Stack:** Git, GitHub Actions, Just, uv, pytest, Python 3.12+, MkDocs.

---

## Scope

This plan covers these recommended improvements:

1. Collapse the formatting follow-up commit before pushing, if branch history is still local.
2. Replace repeated CI `apt-get install just` with a reusable setup pattern.
3. Add `studyloop self-test --json` to installed smoke checks.
4. Strengthen semantic-profile CI so it proves semantic dependencies are present.
5. Add `docs/ci.md`.
6. Make release consistency stricter.
7. Add `docs/ownership.md`.

---

## Subagent Workflow

Use four implementation workers plus one coordinator.

### Coordinator

Owns:
- Git history cleanup decision and any rebase/squash.
- Final integration, conflict resolution, and final verification.
- Keeping subagent edits out of each other's scopes.

Coordinator sequence:

1. Decide whether commit `c311c87 style: format quality improvement files` is safe to squash.
2. Dispatch Worker A, B, C, and D in parallel only if their ownership remains disjoint.
3. Review and commit each worker slice.
4. Run final verification.

### Worker A — CI Setup And Semantic Assertion

Owns:
- `.github/workflows/ci.yml`
- `Justfile`
- Optional helper script if needed: `scripts/check-semantic-profile.py`
- Tests for helper script if created.

Does not edit install scripts, release consistency script, or docs.

### Worker B — Install Smoke Self-Test

Owns:
- `scripts/smoke-installed-cli.sh`
- `scripts/install.sh`
- `packages/studyloop/tests/test_install_script_contract.py`
- Create: `packages/studyloop/tests/test_smoke_installed_cli_contract.py`

Does not edit CI, Justfile, release consistency script, or docs.

### Worker C — Release Consistency Hardening

Owns:
- `scripts/check-release-consistency.py`
- `packages/studyloop/tests/test_release_consistency_script.py`
- `Justfile` only for recipe wording if strictly needed.

Does not edit CI setup, smoke scripts, or docs.

### Worker D — CI And Ownership Docs

Owns:
- Create: `docs/ci.md`
- Create: `docs/ownership.md`
- Modify: `mkdocs.yml`
- Modify: `README.md` only if adding a short docs link is useful.

Does not edit scripts, CI workflow, or tests.

---

## Commit Workflow

Recommended commits:

```text
chore(git): squash formatting follow-up
ci: reuse just setup and assert semantic deps
test(install): include self-test in smoke checks
chore(release): tighten release consistency checks
docs: document ci workflows and ownership
```

If the formatting commit has already been pushed/shared, skip the squash and leave history intact.

---

## Task 0: Optional Commit History Cleanup

**Files:**
- Git history only.

- [ ] **Step 1: Confirm branch is safe to rewrite**

Run:

```bash
git status --short
git log --oneline -8
git branch --show-current
```

Expected:

```text
git status --short
```

prints nothing before rewriting history.

- [ ] **Step 2: Decide whether to squash**

Only squash if all are true:

- Branch has not been pushed to a shared remote.
- No other user is basing work on the current commit SHAs.
- The formatting commit only formats files introduced by earlier commits.

If any condition is false, skip this task.

- [ ] **Step 3: Squash formatting commit**

Use a non-interactive fixup when possible:

```bash
git rebase -i --autosquash <base-before-quality-wave>
```

Recommended mapping:

- Move formatting changes for `web/services/*` into `refactor(web): extract route services`.
- Move formatting changes for `test_web_smoke_browser.py` into `test(web): add browser smoke coverage`.

- [ ] **Step 4: Verify history and tests**

Run:

```bash
git log --oneline -8
just lint
just typecheck
```

Expected:

```text
All checks passed
0 errors
```

---

## Task 1: Reuse CI `just` Setup And Assert Semantic Dependencies

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Justfile`
- Create if useful: `scripts/check-semantic-profile.py`
- Create if useful: `packages/agent-session-tools/tests/test_semantic_profile_contract.py`

- [ ] **Step 1: Add semantic profile assertion script**

Create `scripts/check-semantic-profile.py`:

```python
#!/usr/bin/env python3
"""Verify semantic profile dependencies are importable."""

from __future__ import annotations

import importlib.util
import sys

REQUIRED_MODULES = {
    "numpy": "numpy",
    "sentence_transformers": "sentence-transformers",
}


def main() -> int:
    missing = [
        package_name
        for module_name, package_name in REQUIRED_MODULES.items()
        if importlib.util.find_spec(module_name) is None
    ]
    if missing:
        print("missing semantic dependencies: " + ", ".join(missing))
        return 1
    print("semantic dependencies available")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Add local recipe**

In `Justfile`, add:

```just
check-semantic-profile:
    uv run python scripts/check-semantic-profile.py
```

Change `test-semantic` to:

```just
test-semantic:
    uv run python scripts/check-semantic-profile.py
    uv run --group dev pytest \
        packages/agent-session-tools/tests/test_embeddings.py \
        packages/agent-session-tools/tests/test_semantic_search.py
```

- [ ] **Step 3: Reduce repeated `just` install in CI**

In `.github/workflows/ci.yml`, replace each repeated:

```yaml
      - name: Install just
        run: sudo apt-get update && sudo apt-get install -y just
```

with a pinned setup action or a reusable shell step. Recommended low-risk option:

```yaml
      - uses: extractions/setup-just@v3
```

Use the same line in jobs that call `just`:

- `web-profile`
- `browser-smoke`
- `content-profile`
- `semantic-profile`

- [ ] **Step 4: Validate CI workflow**

Run:

```bash
python - <<'PY'
from pathlib import Path
import yaml
data = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
jobs = data["jobs"]
for job_name in ["web-profile", "browser-smoke", "content-profile", "semantic-profile"]:
    steps = jobs[job_name]["steps"]
    assert any("setup-just" in str(step) for step in steps), job_name
print("ci just setup verified")
PY
```

Expected:

```text
ci just setup verified
```

- [ ] **Step 5: Run local checks**

Run:

```bash
just --list
just test-web
just test-content
just test-semantic
```

Expected:

```text
passed
```

If local semantic dependencies are absent, run:

```bash
just sync-semantic
just test-semantic
```

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/ci.yml Justfile scripts/check-semantic-profile.py
git commit -m "ci: reuse just setup and assert semantic deps"
```

---

## Task 2: Add Self-Test To Installed Smoke Checks

**Files:**
- Modify: `scripts/smoke-installed-cli.sh`
- Modify: `scripts/install.sh`
- Create: `packages/studyloop/tests/test_smoke_installed_cli_contract.py`
- Modify: `packages/studyloop/tests/test_install_script_contract.py`

- [ ] **Step 1: Add contract tests**

Create `packages/studyloop/tests/test_smoke_installed_cli_contract.py`:

```python
"""Contract checks for installed CLI smoke script."""

from __future__ import annotations

from pathlib import Path


def test_smoke_script_runs_self_test_json_and_accepts_warning_exit() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "smoke-installed-cli.sh"
    text = script.read_text(encoding="utf-8")

    assert "studyloop self-test --json" in text
    assert "self_test_status" in text
    assert "0|1)" in text
    assert "python -m json.tool" in text
```

Extend `packages/studyloop/tests/test_install_script_contract.py`:

```python
def test_install_script_smoke_runs_self_test() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "install.sh"
    text = script.read_text(encoding="utf-8")

    assert "studyloop self-test --json" in text
    assert "self_test_status" in text
```

- [ ] **Step 2: Update installed smoke script**

In `scripts/smoke-installed-cli.sh`, after basic help checks, add:

```bash
self_test_output="$(mktemp)"
self_test_status=0
studyloop self-test --json >"$self_test_output" || self_test_status=$?

case "$self_test_status" in
  0|1) ;;
  *)
    cat "$self_test_output" >&2
    exit "$self_test_status"
    ;;
esac

python -m json.tool "$self_test_output" >/dev/null
```

- [ ] **Step 3: Update install script smoke function**

In `scripts/install.sh`, inside `run_smoke_checks()`, add:

```bash
set +e
self_test_json=$(studyloop self-test --json)
self_test_status=$?
set -e

case "$self_test_status" in
  0|1) ;;
  *)
    err "studyloop self-test --json failed with unexpected status ${self_test_status}"
    exit "$self_test_status"
    ;;
esac

if ! printf '%s' "$self_test_json" | python3 -m json.tool >/dev/null; then
  err "studyloop self-test --json did not emit valid JSON"
  exit 1
fi
```

Place it before `studyloop doctor --json` so self-test failures are surfaced first.

- [ ] **Step 4: Run tests and shell checks**

Run:

```bash
uv run --group dev pytest \
  packages/studyloop/tests/test_smoke_installed_cli_contract.py \
  packages/studyloop/tests/test_install_script_contract.py \
  -q
bash -n scripts/install.sh
bash -n scripts/smoke-installed-cli.sh
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit**

```bash
git add scripts/smoke-installed-cli.sh scripts/install.sh \
  packages/studyloop/tests/test_smoke_installed_cli_contract.py \
  packages/studyloop/tests/test_install_script_contract.py
git commit -m "test(install): include self-test in smoke checks"
```

---

## Task 3: Tighten Release Consistency Checks

**Files:**
- Modify: `scripts/check-release-consistency.py`
- Modify: `packages/studyloop/tests/test_release_consistency_script.py`

- [ ] **Step 1: Add failing tests for stricter checks**

Append to `packages/studyloop/tests/test_release_consistency_script.py`:

```python
def test_release_consistency_fails_when_title_version_mismatches(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo, version="2.5.0")
    (repo / "releases/v2.5.0.md").write_text("# v2.4.0\n", encoding="utf-8")
    script = Path(__file__).resolve().parents[3] / "scripts/check-release-consistency.py"

    result = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo), "--skip-wheel"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "release note title" in result.stderr


def test_release_consistency_requires_sdist_when_not_skipping_artifacts(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_minimal_repo(repo, version="2.5.0")
    script = Path(__file__).resolve().parents[3] / "scripts/check-release-consistency.py"

    result = subprocess.run(
        [sys.executable, str(script), "--repo-root", str(repo)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "missing source distribution" in result.stderr
```

- [ ] **Step 2: Implement release-note title check**

In `scripts/check-release-consistency.py`, update `validate_release_note()`:

```python
def validate_release_note(repo_root: Path, version: str) -> None:
    release_note_path = repo_root / "releases" / f"v{version}.md"
    if not release_note_path.is_file():
        raise ValueError(f"missing release note: releases/v{version}.md")
    first_heading = ""
    for line in release_note_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            first_heading = line.strip()
            break
    if f"v{version}" not in first_heading:
        raise ValueError(
            f"release note title must mention v{version}; got {first_heading or '<none>'}"
        )
```

- [ ] **Step 3: Implement sdist check**

Add:

```python
def validate_sdist(repo_root: Path, version: str) -> None:
    sdist_path = repo_root / "dist" / f"studyloop-{version}.tar.gz"
    if not sdist_path.is_file():
        raise ValueError(f"missing source distribution: dist/studyloop-{version}.tar.gz")
```

Call it before `validate_wheel_metadata()` when `--skip-wheel` is not set:

```python
if not args.skip_wheel:
    validate_sdist(repo_root, version)
    validate_wheel_metadata(repo_root, version)
```

- [ ] **Step 4: Run checks**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_release_consistency_script.py -q
just release-consistency
./scripts/build-release.sh
uv run python scripts/check-release-consistency.py
```

Expected:

```text
passed
release consistency passed
Successfully built
release consistency passed
```

- [ ] **Step 5: Commit**

```bash
git add scripts/check-release-consistency.py packages/studyloop/tests/test_release_consistency_script.py
git commit -m "chore(release): tighten release consistency checks"
```

---

## Task 4: Add CI Workflow Documentation

**Files:**
- Create: `docs/ci.md`
- Modify: `mkdocs.yml`
- Modify: `README.md` if useful.

- [ ] **Step 1: Create CI docs**

Create `docs/ci.md`:

```markdown
# CI Workflows

StudyLoop uses a lean default development profile plus explicit optional
profile jobs.

## Local Gates

```bash
just lint
just typecheck
just test
just docs
just audit
```

## Optional Profiles

Run the focused profile when a change touches that surface:

```bash
just test-web
just test-content
just test-semantic
just test-browser-smoke
```

Use `just sync-semantic` before `just test-semantic` when semantic dependencies
are not installed locally.

## Release Gates

```bash
just release-consistency
just smoke-installed
just release-check
```

`audit-full` validates the optional dependency surface. It keeps the torch
advisory ignore explicit until a fixed torch release is available.
```

- [ ] **Step 2: Add docs nav**

In `mkdocs.yml`, under `Reference`, add:

```yaml
    - CI Workflows: ci.md
```

- [ ] **Step 3: Optionally link from README**

Add near documentation links:

```markdown
- [CI Workflows](docs/ci.md) — local and GitHub Actions quality gates
```

- [ ] **Step 4: Verify docs**

Run:

```bash
uv run --extra docs mkdocs build --strict
```

Expected:

```text
Documentation built
```

- [ ] **Step 5: Commit**

```bash
git add docs/ci.md mkdocs.yml README.md
git commit -m "docs: document ci workflows"
```

---

## Task 5: Add Ownership Map

**Files:**
- Create: `docs/ownership.md`
- Modify: `mkdocs.yml`

- [ ] **Step 1: Create ownership map**

Create `docs/ownership.md`:

```markdown
# Ownership Map

This map keeps code review and subagent fanout scoped.

## CLI And Install

- `packages/studyloop/src/studyloop/cli/`
- `packages/studyloop/src/studyloop/installers.py`
- `scripts/install.sh`
- `scripts/smoke-installed-cli.sh`

Primary checks:

```bash
uv run --group dev pytest packages/studyloop/tests/test_cli*.py packages/studyloop/tests/test_install*.py -q
```

## Web UI And Web API

- `packages/studyloop/src/studyloop/web/`
- `packages/studyloop/tests/test_web_*.py`

Primary checks:

```bash
just test-web
just test-browser-smoke
```

## Content Pipeline

- `packages/studyloop/src/studyloop/content/`
- `packages/studyloop/tests/test_content_*.py`

Primary checks:

```bash
just test-content
```

## Session Export And Search

- `packages/agent-session-tools/src/agent_session_tools/`
- `packages/agent-session-tools/tests/`

Primary checks:

```bash
uv run --group dev pytest packages/agent-session-tools/tests -q
just test-semantic
```

## Release And CI

- `.github/workflows/`
- `Justfile`
- `scripts/build-release.sh`
- `scripts/check-release-consistency.py`
- `docs/release-process.md`

Primary checks:

```bash
just release-check
```
```

- [ ] **Step 2: Add docs nav**

In `mkdocs.yml`, under `Reference`, add:

```yaml
    - Ownership Map: ownership.md
```

- [ ] **Step 3: Verify docs**

Run:

```bash
uv run --extra docs mkdocs build --strict
```

Expected:

```text
Documentation built
```

- [ ] **Step 4: Commit**

```bash
git add docs/ownership.md mkdocs.yml
git commit -m "docs: add ownership map"
```

---

## Final Verification

Run:

```bash
just lint
just typecheck
just test
just test-web
just test-content
just test-semantic
just test-browser-smoke
just docs
just audit
just audit-full
just release-consistency
just smoke-installed
git status --short
```

Expected:

```text
git status --short
```

prints no project changes.

---

## Plan Self-Review

Spec coverage:

- Formatting commit cleanup: Task 0.
- Repeated CI `just` setup: Task 1.
- Install smoke self-test: Task 2.
- Semantic profile confidence: Task 1.
- CI docs: Task 4.
- Stricter release consistency: Task 3.
- Ownership map: Task 5.
- Multi-subagent workflow: Subagent Workflow section.

Placeholder scan:

- No open placeholder markers or incomplete implementation steps.

Type consistency:

- New script names and test names are consistent across tasks.
- `self_test_status` and `release-consistency` names match the existing shell/Just conventions.
