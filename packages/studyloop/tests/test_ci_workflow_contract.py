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

    # Publishing moved from `mkdocs gh-deploy --force`, which pushed rendered
    # HTML to a gh-pages branch, to an upload-pages-artifact + deploy-pages
    # pair. So the permissions inverted: the job no longer writes to the
    # repository at all, and instead needs the Pages scope plus an OIDC token
    # for deploy-pages to authenticate with.
    assert deploy["permissions"] == {"pages": "write", "id-token": "write"}

    # Asserted as an absence, not just a set equality, because the equality
    # above could be relaxed later without anyone noticing this mattered:
    # contents: write is what let the old mechanism rewrite a branch, and a
    # deploy that publishes an artifact has no business holding it.
    assert "contents" not in deploy["permissions"], (
        "the artifact deploy must not be able to write to the repository"
    )

    # Bound to the Pages environment, which is what makes the deployment show
    # up as one and gives the job its URL output.
    assert deploy["environment"]["name"] == "github-pages"

    steps = [step.get("uses", "") for step in deploy["steps"]]
    assert any("actions/upload-pages-artifact" in s for s in steps)
    assert any("actions/deploy-pages" in s for s in steps)
