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


def test_docs_workflow_has_no_pages_deploy() -> None:
    """GitHub Pages was retired on 2026-09-10 in favour of www.studyloop.dev.

    The docs workflow is now a build check only. This pins the retirement:
    no deploy job, no Pages/OIDC scopes anywhere in the file, no Pages
    actions, and the strict build still runs so broken docs still fail CI.
    A future contributor re-adding `mkdocs gh-deploy` or `deploy-pages`
    would re-create a publishing surface the owner explicitly removed.
    """
    data = _docs_workflow()

    assert set(data["jobs"]) == {"build"}, f"unexpected docs jobs: {sorted(data['jobs'])}"
    assert data.get("permissions") == {"contents": "read"}

    text = DOCS_WORKFLOW.read_text(encoding="utf-8")
    for forbidden in (
        "deploy-pages",
        "upload-pages-artifact",
        "gh-deploy",
        "github-pages",
        "pages: write",
        "id-token",
    ):
        assert forbidden not in text, (
            f"Pages publishing surface re-appeared in docs.yml: {forbidden!r}"
        )

    build_commands = [step.get("run", "") for step in data["jobs"]["build"]["steps"]]
    assert "uv run --extra docs mkdocs build --strict" in build_commands


def _bandit_skip_list_from_run(run_command: str) -> list[str]:
    match = re.search(r"--skip\s+(\S+)", run_command)
    assert match, f"no --skip found in: {run_command!r}"
    return match.group(1).split(",")


def test_sast_job_bandit_skip_excludes_b602() -> None:
    """B6b: owner decision B6 ("keep the skip list; a specific nosec at the
    one real site") is only honoured if B602 is NOT ALSO in the global
    skip list -- otherwise the nosec at practice.py's shell=True line is
    redundant and the skip-list comment's claim ("B602 has its one real hit
    suppressed with a specific nosec rather than skipped here") is false."""
    data = _workflow()
    sast_run = data["jobs"]["sast"]["steps"][-1]["run"]
    skipped = _bandit_skip_list_from_run(sast_run)
    assert "B602" not in skipped, (
        "ci.yml's sast job still skips B602 globally -- the practice.py "
        "nosec is then redundant and the comment claiming otherwise is false"
    )


def test_pre_commit_bandit_skip_excludes_b602() -> None:
    data = yaml.safe_load((REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8"))
    bandit_hooks = [
        hook
        for repo in data["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == "bandit"
    ]
    assert len(bandit_hooks) == 1
    args = bandit_hooks[0]["args"]
    skip_index = args.index("--skip") + 1
    skipped = args[skip_index].split(",")
    assert "B602" not in skipped, (
        ".pre-commit-config.yaml's bandit hook still skips B602 globally -- "
        "the practice.py nosec is then redundant and the comment claiming "
        "otherwise is false"
    )


def test_sast_and_pre_commit_bandit_skip_lists_agree() -> None:
    """W26: the bandit --skip list must be the SAME list in three places --
    ci.yml, .pre-commit-config.yaml, and .ci-standards.yaml (the local CI
    mirror) -- or a local `ci-standards check` pass is not evidence CI would
    also pass. .ci-standards.yaml previously carried an extra B602, more
    lenient than the real gates, which is a false-green local check."""
    data = _workflow()
    sast_skipped = set(_bandit_skip_list_from_run(data["jobs"]["sast"]["steps"][-1]["run"]))

    precommit_data = yaml.safe_load(
        (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
    )
    bandit_hook = next(
        hook
        for repo in precommit_data["repos"]
        for hook in repo.get("hooks", [])
        if hook.get("id") == "bandit"
    )
    args = bandit_hook["args"]
    precommit_skipped = set(args[args.index("--skip") + 1].split(","))

    ci_standards_data = yaml.safe_load(
        (REPO_ROOT / ".ci-standards.yaml").read_text(encoding="utf-8")
    )
    ci_standards_skipped = set(
        _bandit_skip_list_from_run(ci_standards_data["checks"]["sast"]["command"])
    )

    assert sast_skipped == precommit_skipped == ci_standards_skipped


NIGHTLY_WORKFLOW = WORKFLOW_DIR / "nightly-install.yml"


def _nightly_workflow() -> dict[str, Any]:
    return yaml.safe_load(NIGHTLY_WORKFLOW.read_text(encoding="utf-8"))


def test_nightly_installer_job_plants_a_harness_before_running_install_sh() -> None:
    """The nightly `installer` job (A4, added 2026-09-14) isolates HOME so
    `studyloop install agents` writes into scratch -- and had never passed:
    an empty HOME has no harness, `detect_available_agent_tools()` finds
    nothing, and `install.sh` exits 1 at "Installing agent definitions"
    exactly as the README says it should when no supported AI tool exists.
    The job died five nights running before its verify step ever ran.

    The fixture must supply the precondition the script documents: at least
    one harness marker directory that the detector reads without a binary
    (`~/.kiro`, `~/.claude`, `~/.pi`, `~/.grok`), created in the isolated
    HOME by the same step that runs the script. And the job must then check
    what `install agents` wrote, or the isolation buys nothing.
    """
    data = _nightly_workflow()
    installer = data["jobs"]["installer"]
    steps = installer["steps"]
    run_step = next(step for step in steps if step.get("name") == "Run scripts/install.sh")

    assert run_step["env"]["HOME"] == "${{ runner.temp }}/home", (
        "HOME isolation is the point of the job; it must stay"
    )
    run = run_step["run"]
    assert "./scripts/install.sh --non-interactive --no-smoke" in run

    planted = [
        marker
        for marker in ("$HOME/.kiro", "$HOME/.claude", "$HOME/.pi", "$HOME/.grok")
        if marker in run
    ]
    assert planted, (
        "the installer job runs install.sh in an empty HOME; plant at least one "
        "directory-detected harness marker first or `install agents` exits 1"
    )
    plant_at = min(run.index(marker) for marker in planted)
    assert plant_at < run.index("./scripts/install.sh"), "plant the marker BEFORE the script runs"

    verify = next(
        (step for step in steps if step.get("name") == "Verify installed agent definitions"),
        None,
    )
    assert verify is not None, "the job must verify what `install agents` wrote into HOME"
    assert verify["env"]["HOME"] == "${{ runner.temp }}/home"
    for planted_marker in planted:
        assert planted_marker in verify["run"], f"verify step does not look inside {planted_marker}"


def test_nightly_installer_job_proves_the_studyloop_tool_env_carries_the_semantic_runtime() -> None:
    """`install.sh` gave the studyloop tool venv no semantic runtime, and the
    job's only checks were `--version` and `--help`, which pass without it --
    so every install's `studyloop web` failed its encoder warm at import and
    nothing in CI could see it. The job must import what the warm imports, in
    the venv that serves `studyloop web`, after the script has run.
    """
    steps = _nightly_workflow()["jobs"]["installer"]["steps"]
    names = [step.get("name") for step in steps]
    wanted = "Verify the studyloop tool env carries the semantic runtime"
    assert wanted in names, "the installer job must check the studyloop venv's semantic runtime"
    assert names.index(wanted) > names.index("Run scripts/install.sh")

    verify = steps[names.index(wanted)]
    assert verify["env"]["UV_TOOL_DIR"] == "${{ runner.temp }}/tools"
    assert (
        '"$UV_TOOL_DIR/studyloop/bin/python" -c '
        '"import huggingface_hub, numpy, onnxruntime, sqlite_vec, tokenizers"'
    ) in verify["run"]
