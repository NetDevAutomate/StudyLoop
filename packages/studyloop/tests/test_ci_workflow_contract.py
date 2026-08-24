"""Contract tests for GitHub Actions workflow hardening."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from collections.abc import Mapping

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
JUSTFILE = REPO_ROOT / "Justfile"
CI_GUIDE = REPO_ROOT / "docs" / "ci.md"
E2E_GUIDE = REPO_ROOT / "docs" / "e2e-test-harness.md"
PINNED_ACTION = re.compile(r"^[^@]+@[0-9a-f]{40}$")


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _docs_workflow() -> dict[str, Any]:
    return yaml.safe_load(DOCS_WORKFLOW.read_text(encoding="utf-8"))


def _triggers(data: Mapping[Any, Any]) -> dict[str, Any]:
    triggers = data.get("on") or data.get(True)
    assert isinstance(triggers, dict)
    return triggers


def test_ci_has_read_only_default_permissions() -> None:
    data = _workflow()
    assert data["permissions"] == {"contents": "read"}


def test_all_jobs_have_timeout_minutes() -> None:
    jobs = _workflow()["jobs"]
    missing = [name for name, job in jobs.items() if "timeout-minutes" not in job]
    assert missing == []


def test_setup_just_is_pinned_to_commit_sha() -> None:
    jobs = _workflow()["jobs"]
    for job_name in [
        "frontend-unit",
        "web-profile",
        "browser-smoke",
        "content-profile",
        "semantic-profile",
    ]:
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
    assert all("--skip-wheel" not in str(command) for command in commands)


def test_ci_uv_sync_commands_are_lockfile_enforced() -> None:
    jobs = _workflow()["jobs"]
    sync_commands = [
        step["run"]
        for job in jobs.values()
        for step in job["steps"]
        if isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and step["run"].startswith("uv sync")
    ]
    assert sync_commands
    assert all("--locked" in command for command in sync_commands)


def test_all_workflow_uv_sync_commands_are_lockfile_enforced() -> None:
    sync_commands: list[tuple[str, str]] = []
    for workflow in WORKFLOW_DIR.glob("*.yml"):
        data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
        for job in data.get("jobs", {}).values():
            for step in job.get("steps", []):
                if (
                    isinstance(step, dict)
                    and isinstance(step.get("run"), str)
                    and step["run"].startswith("uv sync")
                ):
                    sync_commands.append((workflow.name, step["run"]))

    assert sync_commands
    unlocked = [(name, command) for name, command in sync_commands if "--locked" not in command]
    assert unlocked == []


def test_ci_typecheck_matches_just_typecheck() -> None:
    commands = [
        step.get("run")
        for step in _workflow()["jobs"]["typecheck"]["steps"]
        if isinstance(step, dict)
    ]
    assert "just typecheck" in commands


def test_frontend_unit_tests_are_local_and_ci_release_gates() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    assert "test-js:" in justfile
    assert "node --test 'packages/studyloop/tests/js/**/*.test.js'" in justfile
    assert re.search(r"^test:\s+test-js$", justfile, re.MULTILINE)

    jobs = _workflow()["jobs"]
    assert "frontend-unit" in jobs
    commands = [
        step.get("run") for step in jobs["frontend-unit"]["steps"] if isinstance(step, dict)
    ]
    assert "just test-js" in commands


def test_public_test_guides_do_not_promise_a_fixed_e2e_duration() -> None:
    approximate_duration = re.compile(r"\b(?:roughly|about|approximately)\s+\d+(?:-|\s+)minutes?\b")

    for path in (CI_GUIDE, E2E_GUIDE):
        guide = path.read_text(encoding="utf-8")
        assert not approximate_duration.search(guide), path
        assert "duration depends on the host" in guide, path


def test_docs_workflow_builds_on_pull_request_without_write_permission() -> None:
    data = _docs_workflow()

    assert "pull_request" in _triggers(data)
    assert data["permissions"] == {"contents": "read"}
    assert "build" in data["jobs"]
    build_commands = [
        step.get("run") for step in data["jobs"]["build"]["steps"] if isinstance(step, dict)
    ]
    assert "uv sync --locked --extra docs" in build_commands
    assert "uv run --extra docs mkdocs build --strict" in build_commands


def test_docs_deploy_job_is_push_only() -> None:
    data = _docs_workflow()

    deploy = data["jobs"]["deploy"]
    assert deploy["if"] == "github.event_name == 'push'"
    assert deploy["permissions"] == {"contents": "write"}
