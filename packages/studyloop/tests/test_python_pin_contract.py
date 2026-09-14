"""Contract tests for deterministic, visible interpreter selection in the
source install (ARBITRATION A1-A4, A24, A25).

Scope, per council ruling A20: doc-contract tests compare sets derived from
code symbols against what a parser extracts from the doc; forbidden-token
greps only for known-stale strings; no line numbers, no copied prose
sentences.
"""

from __future__ import annotations

import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_VERSION_FILE = REPO_ROOT / ".python-version"
STUDYLOOP_PYPROJECT = REPO_ROOT / "packages" / "studyloop" / "pyproject.toml"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
NIGHTLY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "nightly-install.yml"
INSTALL_SCRIPT = REPO_ROOT / "scripts" / "install.sh"
SETUP_GUIDE = REPO_ROOT / "docs" / "setup-guide.md"
TROUBLESHOOTING = REPO_ROOT / "docs" / "troubleshooting.md"
INSTALL_MENTOR = REPO_ROOT / "agents" / "shared" / "install-mentor.md"

_PIN_RE = re.compile(r"^3\.\d+\n?$")

# W27 (unpublished package): the forbidden token is the bare PyPI-resolving
# form; a workspace-relative install (e.g. `--package agent-session-tools`)
# is fine and must not trip this.
_FORBIDDEN_PIP_INSTALL = "uv pip install agent-session-tools"


def _in_scope_docs() -> list[Path]:
    docs = sorted((REPO_ROOT / "docs").glob("*.md"))
    docs.append(REPO_ROOT / "README.md")
    docs.extend(sorted((REPO_ROOT / "packages").glob("*/README.md")))
    return docs


def _python_version_pin() -> str:
    text = PYTHON_VERSION_FILE.read_text()
    assert _PIN_RE.match(text), f".python-version has an unexpected shape: {text!r}"
    return text.strip()


def test_python_version_file_pins_a_single_minor_version() -> None:
    _python_version_pin()


def test_python_version_pin_is_a_pyproject_classifier() -> None:
    pin = _python_version_pin()
    data = tomllib.loads(STUDYLOOP_PYPROJECT.read_text())
    classifiers = set(data["project"]["classifiers"])
    assert f"Programming Language :: Python :: {pin}" in classifiers


def test_python_version_pin_is_in_ci_test_matrix() -> None:
    pin = _python_version_pin()
    data = yaml.safe_load(CI_WORKFLOW.read_text())
    matrix = set(data["jobs"]["test"]["strategy"]["matrix"]["python-version"])
    assert pin in matrix


def test_python_version_pin_is_in_nightly_matrix() -> None:
    pin = _python_version_pin()
    data = yaml.safe_load(NIGHTLY_WORKFLOW.read_text())
    matrix = set(data["jobs"]["fresh-install"]["strategy"]["matrix"]["python-version"])
    assert pin in matrix


def test_ci_test_job_fails_loud_on_interpreter_mismatch() -> None:
    """A2/A24: setup-uv's python-version input overrides .python-version and
    sets UV_PYTHON, but a step right after `uv sync` proves it actually took,
    rather than trusting the override silently."""
    data = yaml.safe_load(CI_WORKFLOW.read_text())
    steps = data["jobs"]["test"]["steps"]
    sync_index = next(
        i
        for i, s in enumerate(steps)
        if isinstance(s, dict) and s.get("run", "").startswith("uv sync")
    )
    following = steps[sync_index + 1]
    assert isinstance(following, dict)
    assert "sys.version_info" in following.get("run", "")


def test_ci_gate_matrix_does_not_include_314() -> None:
    """A4: 3.14 is nightly-only; it must not widen the PR gate."""
    data = yaml.safe_load(CI_WORKFLOW.read_text())
    matrix = set(data["jobs"]["test"]["strategy"]["matrix"]["python-version"])
    assert "3.14" not in matrix


def test_nightly_matrix_includes_314() -> None:
    data = yaml.safe_load(NIGHTLY_WORKFLOW.read_text())
    matrix = set(data["jobs"]["fresh-install"]["strategy"]["matrix"]["python-version"])
    assert "3.14" in matrix


def test_nightly_has_an_installer_job_that_runs_install_sh() -> None:
    """A4: the real `uv tool install` path exercised via scripts/install.sh."""
    data = yaml.safe_load(NIGHTLY_WORKFLOW.read_text())
    jobs = data["jobs"]
    runs_install_sh = [
        step.get("run", "")
        for job in jobs.values()
        for step in job.get("steps", [])
        if isinstance(step, dict)
    ]
    assert any("scripts/install.sh" in run for run in runs_install_sh)


def test_install_script_uses_uv_python_find_not_a_hardcoded_version_gate() -> None:
    text = INSTALL_SCRIPT.read_text()
    assert "uv python find" in text
    assert "UV_PYTHON" in text
    assert 'PY_MINOR" -lt 12' not in text


def test_install_script_help_still_lists_the_four_flags() -> None:
    result = subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )
    for flag in ("--tools-only", "--agents-only", "--non-interactive", "--no-smoke"):
        assert flag in result.stdout


def test_install_script_supported_pythons_list() -> None:
    text = INSTALL_SCRIPT.read_text()
    match = re.search(r"SUPPORTED_PYTHONS=\(([^)]*)\)", text)
    assert match, "no SUPPORTED_PYTHONS=(...) assignment found in scripts/install.sh"
    values = {token.strip('"') for token in match.group(1).split()}
    assert values == {"3.12", "3.13", "3.14"}


def test_setup_guide_and_troubleshooting_mention_uv_python_escape_hatch() -> None:
    for doc in (SETUP_GUIDE, TROUBLESHOOTING):
        assert "UV_PYTHON" in doc.read_text(), f"{doc} does not mention UV_PYTHON"


def test_no_in_scope_doc_tells_readers_to_pip_install_the_unpublished_package() -> None:
    offenders = [
        str(doc.relative_to(REPO_ROOT))
        for doc in _in_scope_docs()
        if _FORBIDDEN_PIP_INSTALL in doc.read_text()
    ]
    assert offenders == []


def test_install_mentor_prompt_has_no_stale_310() -> None:
    assert "3.10" not in INSTALL_MENTOR.read_text()


@pytest.mark.integration
def test_uv_python_find_honours_uv_python_when_passed_explicitly() -> None:
    """A2/A25, verified against uv 0.12.5: plain `uv python find` reads
    .python-version directly during project discovery and does NOT treat a
    bare `UV_PYTHON` env var as an override once that file exists -- only
    `uv sync`/`uv run` treat UV_PYTHON as an "explicit request" that beats
    .python-version. scripts/install.sh therefore passes UV_PYTHON as an
    explicit `uv python find` argument when set, which does take priority
    and agrees with what `uv sync` will actually do; this pins that
    mechanism rather than the (incorrect) assumption that the bare env var
    alone is enough."""
    env = dict(os.environ)
    env["UV_PYTHON"] = "3.13"
    py_path = subprocess.run(
        ["uv", "python", "find", "3.13"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    version = subprocess.run(
        [py_path, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert version == "3.13"


@pytest.mark.integration
def test_uv_python_find_defaults_to_the_python_version_pin() -> None:
    env = {k: v for k, v in os.environ.items() if k != "UV_PYTHON"}
    py_path = subprocess.run(
        ["uv", "python", "find"],
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    version = subprocess.run(
        [py_path, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert version == _python_version_pin()


def test_install_script_installs_the_pinned_python_when_absent() -> None:
    """Acceptance run 2026-09-14 (fresh HOME, Homebrew 3.14 only): `uv python find`
    only *finds*, so on a machine without a 3.12 the pre-check failed with "No
    interpreter found for Python 3.12" before `uv sync` -- which downloads
    automatically -- ever ran. The script must fall back to `uv python install`
    for the requested version, exactly what `uv sync` would have done, but
    visibly and before the heavy dependency download."""
    text = INSTALL_SCRIPT.read_text()
    assert "uv python install" in text, "install.sh never installs a missing pinned interpreter"
    find_at = text.index("uv python find")
    install_at = text.index("uv python install")
    assert find_at < install_at, "the install fallback must follow the find attempt"


def test_install_script_reports_the_tool_venv_interpreters() -> None:
    """Astra Q1.1 (A26): the script prints the interpreter uv resolved BEFORE the
    install; it must also report the interpreter each tool venv actually got,
    so a workspace/tool mismatch is visible in the install log rather than
    inferred. `uv tool dir` locates the tool venvs."""
    text = INSTALL_SCRIPT.read_text()
    assert "uv tool dir" in text
    assert text.index("CLI tools installed") < text.index("uv tool dir")


def test_nightly_installer_job_isolates_home() -> None:
    """Astra Q1.4 (A27): `studyloop install agents` writes into HOME (~/.kiro,
    ~/.claude, ~/.codex, ~/.config/opencode); the nightly installer job must
    point HOME at the runner's temp dir, not just the uv tool dirs."""
    jobs = yaml.safe_load((REPO_ROOT / ".github/workflows/nightly-install.yml").read_text())["jobs"]
    installer = jobs["installer"]
    install_steps = [s for s in installer["steps"] if "scripts/install.sh" in str(s.get("run", ""))]
    assert install_steps, "no step runs scripts/install.sh"
    env = install_steps[0].get("env", {})
    assert "HOME" in env and "runner.temp" in str(env["HOME"]), env
