# StudyLoop Hardening Wave 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the next ten repo-quality improvements across CI supply-chain hardening, shell validation, install smoke coverage, release automation, dependency-profile documentation, and database migration resilience.

**Architecture:** Keep each improvement in a small ownership lane. CI policy and workflow contract tests live together; shell and install smoke behavior live together; release automation gets its own script and tests; documentation updates follow the command changes; migration safety stays inside `agent-session-tools` migration tests.

**Tech Stack:** GitHub Actions, Just, uv, pytest, ruff, pyright, ShellCheck, SQLite migrations, MkDocs.

---

## Scope

This plan implements all ten recommended improvements:

1. Pin `extractions/setup-just@v3` to a commit SHA.
2. Add ShellCheck for install and release scripts.
3. Add CI workflow contract tests.
4. Replace string-only install smoke coverage with executable mocked smoke tests.
5. Add GitHub Actions permissions and job timeouts.
6. Add a local `just preflight` gate.
7. Add release preparation automation.
8. Add isolated `uv tool install` smoke coverage.
9. Document dependency-profile interactions more explicitly.
10. Add database migration/backward-compat smoke tests.

## Subagent Fanout

Use one coordinator and five workers. The active-agent limit in this environment may be two workers at a time; if that limit appears, run Worker A and Worker B first, then Worker C and Worker D, then Worker E.

### Coordinator

Owns:
- Starting from a clean worktree.
- Resolving the `extractions/setup-just` `v3` tag to a commit SHA before Worker A edits CI.
- Reviewing each worker slice for scope creep.
- Creating logical commits.
- Running final verification.

Coordinator setup:

```bash
git status --short
git log --oneline -8
SETUP_JUST_SHA="$(git ls-remote https://github.com/extractions/setup-just.git refs/tags/v3 | awk '{print $1}')"
test "${#SETUP_JUST_SHA}" = 40
printf '%s\n' "$SETUP_JUST_SHA"
```

Expected:

```text
git status --short
```

prints nothing, and `SETUP_JUST_SHA` prints a 40-character SHA.

### Worker A — CI Security And Contract Tests

Owns:
- `.github/workflows/ci.yml`
- `packages/studyloop/tests/test_ci_workflow_contract.py`

Implements:
- Suggestions 1, 3, and 5.

Does not edit:
- `Justfile`
- shell scripts
- release scripts
- docs
- migration tests

### Worker B — ShellCheck And Install Smoke Integration

Owns:
- `Justfile`
- `scripts/install.sh`
- `scripts/smoke-installed-cli.sh`
- `scripts/build-release.sh`
- create `scripts/smoke-uv-tool-install.sh`
- `packages/studyloop/tests/test_install_script_contract.py`
- `packages/studyloop/tests/test_smoke_installed_cli_contract.py`
- create `packages/studyloop/tests/test_smoke_installed_cli_integration.py`

Implements:
- Suggestions 2, 4, and 8.

Does not edit:
- `.github/workflows/ci.yml`
- release preparation script
- docs
- migration tests

### Worker C — Release Preparation Automation

Owns:
- create `scripts/prepare-release.py`
- create `packages/studyloop/tests/test_prepare_release_script.py`
- `scripts/check-release-consistency.py` only if a small helper is worth sharing
- `Justfile` only for the `prepare-release` recipe

Implements:
- Suggestion 7.

Does not edit:
- CI workflow
- install smoke scripts
- docs
- migration tests

### Worker D — Local Gates And Documentation

Owns:
- `Justfile`
- `docs/ci.md`
- `docs/ownership.md`
- `README.md`

Implements:
- Suggestions 6 and 9.

Does not edit:
- CI workflow
- shell scripts
- release scripts
- migration tests

### Worker E — Migration Backward Compatibility

Owns:
- `packages/agent-session-tools/tests/test_migrations.py`
- create `packages/agent-session-tools/tests/fixtures/legacy_sessions_v0.sql` if useful

Implements:
- Suggestion 10.

Does not edit:
- migration implementation unless a failing compatibility test reveals a real bug
- CI workflow
- install/release scripts
- docs

## Commit Workflow

Recommended commits:

```text
ci: harden workflow permissions and contracts
chore(shell): add shellcheck and install smoke integration
chore(release): add release preparation helper
docs: document local gates and dependency profiles
test(db): add migration compatibility smoke coverage
```

If Worker B and Worker D both need `Justfile`, stage path hunks carefully:

```bash
git add -p Justfile
```

---

## Task 1: Harden CI Permissions, Timeouts, Action Pinning, And Contracts

**Files:**
- Modify: `.github/workflows/ci.yml`
- Create: `packages/studyloop/tests/test_ci_workflow_contract.py`

- [ ] **Step 1: Resolve the setup-just commit SHA**

Run:

```bash
SETUP_JUST_SHA="$(git ls-remote https://github.com/extractions/setup-just.git refs/tags/v3 | awk '{print $1}')"
test "${#SETUP_JUST_SHA}" = 40
printf '%s\n' "$SETUP_JUST_SHA"
```

Expected:

```text
<40-character-sha>
```

- [ ] **Step 2: Add CI workflow contract tests**

Create `packages/studyloop/tests/test_ci_workflow_contract.py`:

```python
"""Contract tests for GitHub Actions workflow hardening."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_ci_has_read_only_default_permissions() -> None:
    data = _workflow()
    assert data["permissions"] == {"contents": "read"}


def test_all_jobs_have_timeout_minutes() -> None:
    jobs = _workflow()["jobs"]
    missing = [name for name, job in jobs.items() if "timeout-minutes" not in job]
    assert missing == []


def test_setup_just_is_pinned_to_commit_sha() -> None:
    jobs = _workflow()["jobs"]
    for job_name in ["web-profile", "browser-smoke", "content-profile", "semantic-profile"]:
        steps = jobs[job_name]["steps"]
        setup_steps = [
            step["uses"]
            for step in steps
            if isinstance(step, dict) and "setup-just" in str(step.get("uses", ""))
        ]
        assert len(setup_steps) == 1
        assert PINNED_ACTION.match(setup_steps[0])


def test_profile_jobs_call_expected_just_recipes() -> None:
    jobs = _workflow()["jobs"]
    expected = {
        "web-profile": "just test-web",
        "browser-smoke": "just test-browser-smoke",
        "content-profile": "just test-content",
        "semantic-profile": "just test-semantic",
    }
    for job_name, command in expected.items():
        steps = jobs[job_name]["steps"]
        assert any(step.get("run") == command for step in steps if isinstance(step, dict))


def test_build_job_runs_full_artifact_release_consistency() -> None:
    steps = _workflow()["jobs"]["build"]["steps"]
    commands = [step.get("run") for step in steps if isinstance(step, dict)]
    assert "./scripts/build-release.sh" in commands
    assert "uv run python scripts/check-release-consistency.py" in commands
```

- [ ] **Step 3: Verify the new tests fail before CI changes**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_ci_workflow_contract.py -q
```

Expected:

```text
failed
```

The failures should mention missing top-level `permissions`, missing `timeout-minutes`, and tag-based `setup-just`.

- [ ] **Step 4: Add workflow permissions and timeouts**

In `.github/workflows/ci.yml`, add after the `on:` block:

```yaml
permissions:
  contents: read
```

Add `timeout-minutes` to every job:

```yaml
  lint:
    runs-on: ubuntu-latest
    timeout-minutes: 10
```

Use this timeout map:

```text
lint: 10
typecheck: 10
sast: 10
audit: 10
audit-full: 15
test: 25
web-profile: 15
browser-smoke: 20
content-profile: 15
semantic-profile: 20
build: 10
install-smoke: 15
```

- [ ] **Step 5: Pin setup-just uses**

Replace all four `extractions/setup-just@v3` entries with:

```yaml
      - uses: extractions/setup-just@<SETUP_JUST_SHA>
```

Use the actual SHA from Step 1. Keep the action owner and repo unchanged.

- [ ] **Step 6: Run focused verification**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_ci_workflow_contract.py -q
python - <<'PY'
from pathlib import Path
import yaml

data = yaml.safe_load(Path(".github/workflows/ci.yml").read_text())
assert data["permissions"] == {"contents": "read"}
assert all("timeout-minutes" in job for job in data["jobs"].values())
print("ci workflow contract verified")
PY
```

Expected:

```text
5 passed
ci workflow contract verified
```

- [ ] **Step 7: Commit**

```bash
git add .github/workflows/ci.yml packages/studyloop/tests/test_ci_workflow_contract.py
git commit -m "ci: harden workflow permissions and contracts"
```

---

## Task 2: Add ShellCheck And Executable Install Smoke Tests

**Files:**
- Modify: `Justfile`
- Modify: `scripts/install.sh`
- Modify: `scripts/smoke-installed-cli.sh`
- Modify: `scripts/build-release.sh`
- Create: `scripts/smoke-uv-tool-install.sh`
- Modify: `packages/studyloop/tests/test_install_script_contract.py`
- Modify: `packages/studyloop/tests/test_smoke_installed_cli_contract.py`
- Create: `packages/studyloop/tests/test_smoke_installed_cli_integration.py`

- [ ] **Step 1: Add ShellCheck recipe contract tests**

Append to `packages/studyloop/tests/test_install_script_contract.py`:

```python
def test_justfile_defines_shellcheck_recipe() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    justfile = repo_root / "Justfile"
    text = justfile.read_text(encoding="utf-8")

    assert "\nshellcheck:\n" in text
    assert "shellcheck scripts/install.sh scripts/smoke-installed-cli.sh scripts/build-release.sh scripts/smoke-uv-tool-install.sh" in text
```

- [ ] **Step 2: Add executable smoke script integration tests**

Create `packages/studyloop/tests/test_smoke_installed_cli_integration.py`:

```python
"""Executable integration tests for the installed CLI smoke script."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def _write_fake_studyloop(bin_dir: Path, *, self_status: int, self_output: str) -> None:
    script = bin_dir / "studyloop"
    script.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
case "${{1:-}}" in
  --help|--version) exit 0 ;;
  config|content|review)
    if [ "${{2:-}}" = "--help" ]; then
      exit 0
    fi
    ;;
  self-test)
    if [ "${{2:-}}" = "--json" ]; then
      printf '%s\\n' {self_output!r}
      exit {self_status}
    fi
    ;;
  doctor)
    if [ "${{2:-}}" = "--json" ]; then
      printf '%s\\n' '{{"status":"ok"}}'
      exit 0
    fi
    ;;
esac
exit 64
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def _run_smoke(tmp_path: Path, *, self_status: int, self_output: str) -> subprocess.CompletedProcess[str]:
    repo_root = Path(__file__).resolve().parents[3]
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_fake_studyloop(bin_dir, self_status=self_status, self_output=self_output)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["STUDYLOOP_CONFIG"] = str(tmp_path / "config.yaml")

    return subprocess.run(
        ["bash", str(repo_root / "scripts" / "smoke-installed-cli.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_smoke_accepts_self_test_exit_zero(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, self_status=0, self_output='{"status":"ok"}')

    assert result.returncode == 0


def test_smoke_accepts_self_test_exit_one(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, self_status=1, self_output='{"status":"warning"}')

    assert result.returncode == 0


def test_smoke_rejects_unexpected_self_test_status(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, self_status=2, self_output='{"status":"failed"}')

    assert result.returncode == 2
    assert '{"status":"failed"}' in result.stderr


def test_smoke_rejects_invalid_self_test_json(tmp_path: Path) -> None:
    result = _run_smoke(tmp_path, self_status=0, self_output="not-json")

    assert result.returncode != 0
```

- [ ] **Step 3: Verify tests fail before implementation**

Run:

```bash
uv run --group dev pytest \
  packages/studyloop/tests/test_install_script_contract.py::test_justfile_defines_shellcheck_recipe \
  packages/studyloop/tests/test_smoke_installed_cli_integration.py \
  -q
```

Expected:

```text
failed
```

The ShellCheck recipe test should fail until the recipe exists. The executable tests should pass if the current smoke script already has correct behavior; if they pass, keep them as regression coverage.

- [ ] **Step 4: Add the ShellCheck recipe**

In `Justfile`, add after `typecheck`:

```just
shellcheck:
    shellcheck scripts/install.sh scripts/smoke-installed-cli.sh scripts/build-release.sh scripts/smoke-uv-tool-install.sh
```

Update `release-check` later only after `shellcheck` passes locally.

- [ ] **Step 5: Add isolated uv tool install smoke script**

Create `scripts/smoke-uv-tool-install.sh`:

```bash
#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

export HOME="$tmp/home"
export XDG_CACHE_HOME="$tmp/cache"
export XDG_DATA_HOME="$tmp/data"
mkdir -p "$HOME" "$XDG_CACHE_HOME" "$XDG_DATA_HOME"

uv tool install \
  --force \
  --editable "$ROOT_DIR/packages/studyloop[sessions,web,content]" \
  --with-editable "$ROOT_DIR/packages/agent-session-tools"

tool_bin="$HOME/.local/bin"
PATH="$tool_bin:$PATH" "$ROOT_DIR/scripts/smoke-installed-cli.sh"
```

Make it executable:

```bash
chmod +x scripts/smoke-uv-tool-install.sh
```

- [ ] **Step 6: Add contract coverage for uv tool smoke script**

Append to `packages/studyloop/tests/test_smoke_installed_cli_contract.py`:

```python
def test_uv_tool_smoke_uses_isolated_home_and_smoke_script() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "smoke-uv-tool-install.sh"
    script_text = script.read_text(encoding="utf-8")

    assert 'export HOME="$tmp/home"' in script_text
    assert "uv tool install" in script_text
    assert '--editable "$ROOT_DIR/packages/studyloop[sessions,web,content]"' in script_text
    assert '--with-editable "$ROOT_DIR/packages/agent-session-tools"' in script_text
    assert '"$ROOT_DIR/scripts/smoke-installed-cli.sh"' in script_text
```

- [ ] **Step 7: Run shell syntax and ShellCheck**

Run:

```bash
bash -n scripts/install.sh
bash -n scripts/smoke-installed-cli.sh
bash -n scripts/build-release.sh
bash -n scripts/smoke-uv-tool-install.sh
just shellcheck
```

Expected:

```text
no output from bash -n
no output from shellcheck
```

If `shellcheck` is not installed locally, install it with Homebrew on macOS:

```bash
brew install shellcheck
just shellcheck
```

- [ ] **Step 8: Run focused tests**

Run:

```bash
uv run --group dev pytest \
  packages/studyloop/tests/test_install_script_contract.py \
  packages/studyloop/tests/test_smoke_installed_cli_contract.py \
  packages/studyloop/tests/test_smoke_installed_cli_integration.py \
  -q
```

Expected:

```text
passed
```

- [ ] **Step 9: Run isolated uv tool smoke**

Run:

```bash
./scripts/smoke-uv-tool-install.sh
```

Expected:

```text
studyloop, session-export, self-test, and doctor smoke checks pass
```

- [ ] **Step 10: Commit**

```bash
git add Justfile scripts/install.sh scripts/smoke-installed-cli.sh scripts/build-release.sh scripts/smoke-uv-tool-install.sh \
  packages/studyloop/tests/test_install_script_contract.py \
  packages/studyloop/tests/test_smoke_installed_cli_contract.py \
  packages/studyloop/tests/test_smoke_installed_cli_integration.py
git commit -m "chore(shell): add shellcheck and install smoke integration"
```

---

## Task 3: Add Release Preparation Automation

**Files:**
- Create: `scripts/prepare-release.py`
- Create: `packages/studyloop/tests/test_prepare_release_script.py`
- Modify: `Justfile`
- Modify: `docs/release-process.md` if it already documents manual release steps

- [ ] **Step 1: Add tests for release preparation**

Create `packages/studyloop/tests/test_prepare_release_script.py`:

```python
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "prepare-release.py"


def _write_repo(repo: Path, version: str = "1.2.3") -> None:
    package_dir = repo / "packages" / "studyloop"
    package_dir.mkdir(parents=True)
    (package_dir / "pyproject.toml").write_text(
        f'[project]\nname = "studyloop"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (repo / "releases").mkdir()


def test_prepare_release_updates_version_and_creates_release_note(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "1.2.4", "--repo-root", str(repo)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    pyproject = repo / "packages" / "studyloop" / "pyproject.toml"
    assert 'version = "1.2.4"' in pyproject.read_text(encoding="utf-8")
    release_note = repo / "releases" / "v1.2.4.md"
    assert release_note.is_file()
    assert release_note.read_text(encoding="utf-8").startswith("# v1.2.4\n")


def test_prepare_release_refuses_existing_release_note_without_force(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)
    (repo / "releases" / "v1.2.4.md").write_text("# v1.2.4\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "1.2.4", "--repo-root", str(repo)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "already exists" in result.stderr


def test_prepare_release_dry_run_does_not_write_files(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _write_repo(repo)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "1.2.4", "--repo-root", str(repo), "--dry-run"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert 'version = "1.2.3"' in (
        repo / "packages" / "studyloop" / "pyproject.toml"
    ).read_text(encoding="utf-8")
    assert not (repo / "releases" / "v1.2.4.md").exists()
    assert "would update" in result.stdout
```

- [ ] **Step 2: Verify tests fail before the script exists**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_prepare_release_script.py -q
```

Expected:

```text
failed
```

The failure should show that `scripts/prepare-release.py` does not exist.

- [ ] **Step 3: Add the release preparation script**

Create `scripts/prepare-release.py`:

```python
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

VERSION_RE = re.compile(r"^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare a StudyLoop release.")
    parser.add_argument("version", help="New version, for example 2.6.0")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository root. Defaults to the parent of scripts/.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned writes.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow updating an existing release note.",
    )
    return parser.parse_args(argv)


def replace_version(pyproject_text: str, version: str) -> str:
    return re.sub(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        pyproject_text,
        count=1,
    )


def release_note_text(version: str) -> str:
    return (
        f"# v{version}\n\n"
        "## Changes\n\n"
        "- Release summary.\n\n"
        "## Verification\n\n"
        "- `just release-check`\n"
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    version = args.version
    if not VERSION_RE.match(version):
        print(f"invalid version: {version}", file=sys.stderr)
        return 1

    repo_root = args.repo_root.resolve()
    pyproject_path = repo_root / "packages" / "studyloop" / "pyproject.toml"
    release_note_path = repo_root / "releases" / f"v{version}.md"

    pyproject_text = pyproject_path.read_text(encoding="utf-8")
    new_pyproject_text = replace_version(pyproject_text, version)
    if new_pyproject_text == pyproject_text:
        print(f"could not find project version in {pyproject_path}", file=sys.stderr)
        return 1

    if release_note_path.exists() and not args.force:
        print(f"release note already exists: {release_note_path}", file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"would update {pyproject_path}")
        print(f"would write {release_note_path}")
        return 0

    pyproject_path.write_text(new_pyproject_text, encoding="utf-8")
    release_note_path.write_text(release_note_text(version), encoding="utf-8")
    print(f"prepared StudyLoop {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Make it executable:

```bash
chmod +x scripts/prepare-release.py
```

- [ ] **Step 4: Add Justfile recipe**

Add to `Justfile`:

```just
prepare-release version:
    uv run python scripts/prepare-release.py {{version}}
```

- [ ] **Step 5: Update release docs**

If `docs/release-process.md` contains manual version bump instructions, add:

```markdown
Use the helper to update the package version and create the release note:

```bash
just prepare-release 2.6.0
just release-check
```
```

- [ ] **Step 6: Run focused verification**

Run:

```bash
uv run --group dev pytest packages/studyloop/tests/test_prepare_release_script.py -q
uv run --group dev ruff check scripts/prepare-release.py packages/studyloop/tests/test_prepare_release_script.py
uv run --group dev ruff format --check scripts/prepare-release.py packages/studyloop/tests/test_prepare_release_script.py
just --list
```

Expected:

```text
3 passed
All checks passed
already formatted
prepare-release appears in just --list
```

- [ ] **Step 7: Commit**

```bash
git add scripts/prepare-release.py packages/studyloop/tests/test_prepare_release_script.py Justfile docs/release-process.md
git commit -m "chore(release): add release preparation helper"
```

---

## Task 4: Add Preflight Gate And Dependency Profile Documentation

**Files:**
- Modify: `Justfile`
- Modify: `docs/ci.md`
- Modify: `docs/ownership.md`
- Modify: `README.md`

- [ ] **Step 1: Add local gate recipes**

In `Justfile`, add:

```just
preflight: lint typecheck test docs release-consistency
```

Update `release-check` to include `shellcheck` after Task 2 exists:

```just
release-check: test lint typecheck shellcheck docs audit audit-full release-consistency smoke-installed
```

Keep `preflight` lighter than `release-check`; it should not build/install artifacts.

- [ ] **Step 2: Add documentation for local gates**

In `docs/ci.md`, replace the "Local Gates" section with:

```markdown
## Local Gates

Use `preflight` for normal development:

```bash
just preflight
```

It runs linting, type checking, the default test suite, docs, and release-note
consistency without building/installing artifacts.

Use `release-check` for a release candidate:

```bash
just release-check
```

It includes `preflight`-level checks plus ShellCheck, dependency audits, full
optional dependency audit, and installed-wheel smoke testing.
```

- [ ] **Step 3: Document dependency profile interactions**

In `docs/ci.md`, add after "Optional Profiles":

```markdown
## Dependency Profiles

The project uses separate optional dependency profiles so day-to-day development
does not install every heavy package.

| Command | Installs | Use when |
| --- | --- | --- |
| `just sync-dev` | default workspace plus dev tools | normal CLI and unit-test work |
| `just sync-web` | web UI dependencies | touching FastAPI/web routes or browser smoke tests |
| `just sync-content` | PDF/content generation dependencies | touching content ingestion or generation |
| `just sync-semantic` | embedding and semantic-search dependencies | touching semantic search |
| `just sync-full` | all optional extras | release candidate or dependency audit investigation |

`uv sync --extra ...` reconciles the active `.venv` to the requested profile.
That can remove packages from another optional profile. This is expected; run
the matching `just sync-*` command before the profile-specific tests you need.
```

- [ ] **Step 4: Update README maintainer commands**

In `README.md`, change the maintainer task command block to:

```bash
just preflight
just release-check
```

Add one sentence below it:

```markdown
Use `just sync-web`, `just sync-content`, or `just sync-semantic` before optional profile tests when the active `.venv` does not include that dependency set.
```

- [ ] **Step 5: Update ownership map operations row**

In `docs/ownership.md`, update the Operations table verification entries to mention:

```markdown
| CI | `.github/workflows/ci.yml`, `Justfile` | `just preflight`, CI contract tests |
| Installation | `scripts/install.sh`, `scripts/smoke-installed-cli.sh`, `scripts/smoke-uv-tool-install.sh` | Install contract tests, `just smoke-installed`, uv tool smoke |
```

- [ ] **Step 6: Verify docs and Justfile**

Run:

```bash
just --list
uv run --extra docs mkdocs build --strict
rg -n "just preflight|Dependency Profiles|sync-semantic|release-check" docs README.md
```

Expected:

```text
preflight appears in just --list
Documentation built
rg prints the new documentation lines
```

- [ ] **Step 7: Commit**

```bash
git add Justfile docs/ci.md docs/ownership.md README.md
git commit -m "docs: document local gates and dependency profiles"
```

---

## Task 5: Add Database Migration Backward-Compatibility Smoke Tests

**Files:**
- Modify: `packages/agent-session-tools/tests/test_migrations.py`
- Create: `packages/agent-session-tools/tests/fixtures/legacy_sessions_v0.sql` if preferred for readability

- [ ] **Step 1: Add a legacy schema fixture helper**

Append near the top of `packages/agent-session-tools/tests/test_migrations.py`:

```python
def legacy_v0_connection(tmp_path: Path) -> sqlite3.Connection:
    db_path = tmp_path / "legacy-v0.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            project_path TEXT,
            git_branch TEXT,
            created_at TEXT,
            updated_at TEXT,
            metadata JSON
        );

        CREATE TABLE messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id),
            parent_id TEXT,
            role TEXT NOT NULL,
            content TEXT,
            model TEXT,
            timestamp TEXT,
            metadata JSON
        );

        CREATE INDEX idx_messages_session ON messages(session_id);
        CREATE INDEX idx_messages_timestamp ON messages(timestamp);
        CREATE INDEX idx_sessions_source ON sessions(source);
        CREATE INDEX idx_sessions_project ON sessions(project_path);

        CREATE VIRTUAL TABLE messages_fts USING fts5(
            content,
            session_id UNINDEXED,
            role UNINDEXED,
            tokenize='porter unicode61'
        );

        CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages
        WHEN NEW.content IS NOT NULL
        BEGIN
            INSERT INTO messages_fts(rowid, content, session_id, role)
            VALUES (NEW.rowid, NEW.content, NEW.session_id, NEW.role);
        END;

        INSERT INTO sessions (
            id, source, project_path, git_branch, created_at, updated_at, metadata
        ) VALUES (
            'legacy-session', 'claude_code', '/tmp/studyloop', 'main',
            '2026-01-01T00:00:00Z', '2026-01-01T00:01:00Z', '{}'
        );

        INSERT INTO messages (
            id, session_id, parent_id, role, content, model, timestamp, metadata
        ) VALUES (
            'legacy-message', 'legacy-session', NULL, 'user',
            'legacy migration smoke content', NULL,
            '2026-01-01T00:00:30Z', '{}'
        );
        """
    )
    conn.commit()
    return conn
```

- [ ] **Step 2: Add backward-compatibility tests**

Append to the `TestMigrate` class:

```python
    def test_legacy_v0_database_migrates_to_current_version(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            applied = migrate(conn)

            assert applied
            assert get_user_version(conn) == CURRENT_VERSION
            row = conn.execute(
                "SELECT content FROM messages WHERE id = 'legacy-message'"
            ).fetchone()
            assert row == ("legacy migration smoke content",)
        finally:
            conn.close()

    def test_legacy_v0_database_keeps_fts_readable_after_migration(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)

            rows = conn.execute(
                "SELECT content FROM messages_fts WHERE messages_fts MATCH 'legacy'"
            ).fetchall()
            assert rows == [("legacy migration smoke content",)]
        finally:
            conn.close()

    def test_legacy_v0_database_migration_is_idempotent(self, tmp_path):
        conn = legacy_v0_connection(tmp_path)
        try:
            migrate(conn)
            second = migrate(conn)

            assert second == []
            assert get_user_version(conn) == CURRENT_VERSION
        finally:
            conn.close()
```

- [ ] **Step 3: Run the new tests**

Run:

```bash
uv run --group dev pytest \
  packages/agent-session-tools/tests/test_migrations.py::TestMigrate::test_legacy_v0_database_migrates_to_current_version \
  packages/agent-session-tools/tests/test_migrations.py::TestMigrate::test_legacy_v0_database_keeps_fts_readable_after_migration \
  packages/agent-session-tools/tests/test_migrations.py::TestMigrate::test_legacy_v0_database_migration_is_idempotent \
  -q
```

Expected:

```text
3 passed
```

If a test fails, inspect the failing migration and fix only the migration guard required to preserve legacy data. Keep the test as the compatibility contract.

- [ ] **Step 4: Run the full migration tests**

Run:

```bash
uv run --group dev pytest packages/agent-session-tools/tests/test_migrations.py -q
```

Expected:

```text
passed
```

- [ ] **Step 5: Commit**

```bash
git add packages/agent-session-tools/tests/test_migrations.py packages/agent-session-tools/tests/fixtures/legacy_sessions_v0.sql
git commit -m "test(db): add migration compatibility smoke coverage"
```

If no fixture file is created, omit it from `git add`.

---

## Final Integration Verification

Run after all tasks are committed:

```bash
just --list
just lint
just typecheck
just shellcheck
just preflight
just docs
just release-consistency
uv run --group dev pytest packages/studyloop/tests/test_ci_workflow_contract.py -q
uv run --group dev pytest packages/studyloop/tests/test_install_script_contract.py packages/studyloop/tests/test_smoke_installed_cli_contract.py packages/studyloop/tests/test_smoke_installed_cli_integration.py -q
uv run --group dev pytest packages/studyloop/tests/test_prepare_release_script.py -q
uv run --group dev pytest packages/agent-session-tools/tests/test_migrations.py -q
just smoke-installed
./scripts/smoke-uv-tool-install.sh
just audit
just audit-full
git status --short
```

Expected:

```text
all tests pass
release consistency passed
No known vulnerabilities found
No known vulnerabilities found, 1 ignored
git status --short prints nothing
```

If `just shellcheck` fails on SC1091 for sourced files, prefer a precise directive above the relevant source line:

```bash
# shellcheck source=/dev/null
```

Do not disable broad ShellCheck categories without a file-specific reason.

## Plan Self-Review

Spec coverage:
- Suggestion 1: Task 1 pins `setup-just`.
- Suggestion 2: Task 2 adds ShellCheck.
- Suggestion 3: Task 1 adds CI contract tests.
- Suggestion 4: Task 2 adds executable mocked smoke tests.
- Suggestion 5: Task 1 adds permissions and timeouts.
- Suggestion 6: Task 4 adds `just preflight`.
- Suggestion 7: Task 3 adds release preparation automation.
- Suggestion 8: Task 2 adds isolated `uv tool install` smoke coverage.
- Suggestion 9: Task 4 documents dependency profiles.
- Suggestion 10: Task 5 adds migration compatibility smoke tests.

Ownership check:
- Worker A and Worker E have disjoint files.
- Worker B and Worker D both edit `Justfile`; commit with path hunks if both are run before integration.
- Worker C and Worker D both edit `Justfile`; stage recipes carefully.
- No task rewrites user data or global uv tool state; the uv tool smoke uses an isolated `HOME`.
