"""Contract tests for GitHub Actions workflow hardening."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
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


# --- Secret scanning in CI (F-XCUT-05@luna) ----------------------------------
#
# The commit-time secret hooks (.pre-commit-config.yaml) only run on a machine
# where a contributor installed and kept the hook. A pull request from anyone
# else reaches main with no secret scan at all. CI must run the same hooks, from
# the same pinned config, so the gate holds server-side too.

SECRET_HOOK_IDS = ("detect-private-key", "detect-aws-credentials", "detect-secrets")


def _steps_running(needle: str) -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """Every (job name, job, step) in ci.yml whose ``run`` contains ``needle``."""
    return [
        (name, job, step)
        for name, job in _workflow()["jobs"].items()
        for step in job["steps"]
        if isinstance(step, dict) and needle in str(step.get("run", ""))
    ]


def _assert_blocking(hits: list[tuple[str, dict[str, Any], dict[str, Any]]], what: str) -> None:
    assert hits, f"no ci.yml step runs {what}"
    for name, job, step in hits:
        assert not job.get("continue-on-error"), f"job {name!r} may not soften {what}"
        assert not step.get("continue-on-error"), f"the {what} step in {name!r} must block"


def test_ci_runs_a_secret_scanner() -> None:
    """detect-secrets runs over the whole checkout against the committed
    baseline, through pre-commit so the hook's pinned rev and its ``exclude``
    list are the ones in force -- the same check a local commit gets."""
    hits = _steps_running("pre-commit run detect-secrets --all-files")
    _assert_blocking(hits, "detect-secrets")
    for _name, _job, step in hits:
        assert step["run"].startswith("uv run --group dev pre-commit run "), (
            "run pre-commit from the locked dev group, not an unpinned uvx/pip copy"
        )


def test_ci_runs_every_commit_gate_secret_hook() -> None:
    for hook_id in SECRET_HOOK_IDS:
        _assert_blocking(_steps_running(f"pre-commit run {hook_id} --all-files"), hook_id)

    configured = {
        hook["id"]
        for repo in yaml.safe_load(
            (REPO_ROOT / ".pre-commit-config.yaml").read_text(encoding="utf-8")
        )["repos"]
        for hook in repo.get("hooks", [])
    }
    assert set(SECRET_HOOK_IDS) <= configured, "CI must run hooks the commit gate defines"


# --- trufflehog over a pull request's own commits (ARBITRATION-pass3 D6) ----
#
# The commit gate's trufflehog layer (provider-specific detectors, with live
# verification) runs only where a contributor kept the hook. The secrets job
# runs the official action over the pull request's commits, base..head, pinned
# by commit, and refuses to scan a range it cannot resolve.

SCRIPT = REPO_ROOT / "scripts" / "security" / "trufflehog_redacted.py"
TRUFFLEHOG_ACTION = re.compile(r"^trufflesecurity/trufflehog@([0-9a-f]{40})$")
PINNED_SCANNER_IMAGE = re.compile(r"^(\d+\.\d+\.\d+)@sha256:[0-9a-f]{64}$")
PR_ONLY = "github.event_name == 'pull_request'"
PR_BASE = "${{ github.event.pull_request.base.sha }}"
PR_HEAD = "${{ github.event.pull_request.head.sha }}"
GUARD = "scripts/security/trufflehog_redacted.py --check-range"


def _secrets_job() -> dict[str, Any]:
    return _workflow()["jobs"]["secrets"]


def _secrets_steps() -> list[dict[str, Any]]:
    return [step for step in _secrets_job()["steps"] if isinstance(step, dict)]


def _trufflehog_step() -> dict[str, Any]:
    steps = [
        step
        for step in _secrets_steps()
        if str(step.get("uses", "")).startswith("trufflesecurity/trufflehog@")
    ]
    assert len(steps) == 1, "the secrets job must run the official trufflehog action once"
    return steps[0]


def _guard_step() -> dict[str, Any]:
    steps = [step for step in _secrets_steps() if GUARD in str(step.get("run", ""))]
    assert len(steps) == 1, "the secrets job must resolve the PR range before scanning it"
    return steps[0]


def test_secrets_job_scans_the_pull_request_range_with_trufflehog() -> None:
    step = _trufflehog_step()
    assert step.get("if") == PR_ONLY, "PR-scoped: base..head only exists on a pull request"
    assert step["with"]["base"] == PR_BASE
    assert step["with"]["head"] == PR_HEAD
    assert not step.get("continue-on-error"), "a finding must fail the job"
    assert not _secrets_job().get("continue-on-error")


def test_trufflehog_action_and_its_scanner_image_are_both_pinned() -> None:
    """The action is pinned by commit; its ``version`` input defaults to
    ``latest`` (action.yml), so without a pinned image the SHA-pinned action
    would still run whatever scanner was published last. The image is pinned by
    digest to the same release the action's commit is tagged with."""
    step = _trufflehog_step()
    match = TRUFFLEHOG_ACTION.match(step["uses"])
    assert match, f"pin the action by its full 40-hex commit, not a tag: {step['uses']!r}"

    lines = [
        line for line in WORKFLOW.read_text(encoding="utf-8").splitlines() if step["uses"] in line
    ]
    assert len(lines) == 1
    tag = re.search(r"#\s*v(\d+\.\d+\.\d+)\s*$", lines[0])
    assert tag, "record the release tag beside the pinned commit"

    image = PINNED_SCANNER_IMAGE.match(str(step["with"].get("version", "")))
    assert image, "pin the scanner image as <version>@sha256:<digest>, never `latest`"
    assert image.group(1) == tag.group(1), "the image and the action must be the same release"


def test_trufflehog_keeps_unknown_results_and_is_not_narrowed_to_verified() -> None:
    """``--results=verified,unknown`` fails on live credentials and on ones the
    scanner could not verify. ``--only-verified`` must NOT be added beside it:
    trufflehog's main.go replaces ``--results`` with ``verified`` whenever
    ``--only-verified`` is set, so the pair silently drops every unknown result
    (probed against the pinned image: the pair exited 0 on a planted token the
    lone ``--results`` flag failed with 183)."""
    args = str(_trufflehog_step()["with"].get("extra_args", "")).split()
    assert "--results=verified,unknown" in args
    assert "--only-verified" not in args
    assert not any(arg.startswith("--since-commit") for arg in args), (
        "the range comes from base/head; a second --since-commit would override it"
    )


def test_secrets_job_is_read_only_and_checks_out_full_history() -> None:
    job = _secrets_job()
    assert job.get("permissions") == {"contents": "read"}
    checkouts = [
        step
        for step in _secrets_steps()
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]
    assert len(checkouts) == 1
    assert PINNED_ACTION.match(checkouts[0]["uses"])
    options = checkouts[0].get("with") or {}
    assert options.get("fetch-depth") == 0, "a shallow clone has no base commit to scan from"
    assert options.get("persist-credentials") is False, (
        "the scanner container mounts the workspace; keep the job token out of .git/config"
    )


def test_no_ci_secret_scan_is_scoped_to_since_head() -> None:
    """``--since-commit=HEAD`` is the local hook's scope. In CI, HEAD is the
    commit under test, so HEAD..HEAD would scan nothing and still pass."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--since-commit=HEAD" not in text
    assert not re.search(r"--since-commit\s+HEAD\b", text)


def test_pr_range_guard_runs_first_from_the_event_shas_and_blocks() -> None:
    steps = _secrets_steps()
    guard = _guard_step()
    assert steps.index(guard) < steps.index(_trufflehog_step()), "resolve the range before the scan"
    assert guard.get("if") == PR_ONLY
    assert not guard.get("continue-on-error")
    assert guard["env"] == {"PR_BASE": PR_BASE, "PR_HEAD": PR_HEAD}, (
        "pass the event SHAs through env, never interpolated into the script"
    )
    assert guard["run"] == (
        "uv run --group dev python scripts/security/trufflehog_redacted.py"
        ' --check-range --base "$PR_BASE" --head "$PR_HEAD"'
    )


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=ci-contract",
            "-c",
            "user.email=ci-contract@example.invalid",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def test_pr_range_guard_as_written_fails_closed_on_a_missing_base(tmp_path: Path) -> None:
    """Run the guard step's own command (with this interpreter in place of
    ``uv run``) in a two-commit repository: a real range passes, and an empty or
    unknown base fails the step instead of degrading to a whole-history or
    HEAD..HEAD scan."""
    _git(tmp_path, "init", "-q")
    for name in ("one", "two"):
        (tmp_path / name).write_text(name, encoding="utf-8")
        _git(tmp_path, "add", name)
        _git(tmp_path, "commit", "-q", "-m", name)
    base = _git(tmp_path, "rev-parse", "HEAD~1")
    head = _git(tmp_path, "rev-parse", "HEAD")

    prefix = "uv run --group dev python scripts/security/trufflehog_redacted.py"
    run = _guard_step()["run"]
    assert run.startswith(prefix)
    command = f"{shlex.quote(sys.executable)} {shlex.quote(str(SCRIPT))}{run[len(prefix) :]}"

    def guard(pr_base: str, pr_head: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "-c", command],
            cwd=tmp_path,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(tmp_path),
                "PR_BASE": pr_base,
                "PR_HEAD": pr_head,
            },
            capture_output=True,
            text=True,
            check=False,
        )

    assert guard(base, head).returncode == 0
    for missing in ("", "0" * 40, "ab" * 20):
        proc = guard(missing, head)
        assert proc.returncode == 2, (missing, proc.stdout, proc.stderr)
        assert "base" in proc.stderr


# --- Removed orphans stay removed (ledger 13, F-OPS-13/14@sol) ---------------


def _tracked_mentions(needle: str) -> list[str]:
    """Tracked files that mention ``needle``, excluding this contract file."""
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(REPO_ROOT),
            "grep",
            "-I",
            "-l",
            "-F",
            "-e",
            needle,
            "--",
            ".",
            f":!{Path(__file__).resolve().relative_to(REPO_ROOT)}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode in (0, 1), proc.stderr  # 1 = no match; anything else is git failing
    return proc.stdout.split()


def test_removed_orphan_workflow_script_stays_removed() -> None:
    """``scripts/gen_quality_workflow.js`` was referenced by nothing (no recipe,
    workflow, doc or script) and carried a shell-injection heredoc and fixed
    shared ``/tmp`` paths. Deleted, it must not drift back."""
    assert not (REPO_ROOT / "scripts" / "gen_quality_workflow.js").exists()
    assert _tracked_mentions("gen_quality_workflow") == []


def test_no_tracked_file_documents_overwriting_the_changelog() -> None:
    """CHANGELOG.md is written by hand (docs/contributor-changelog.md, section 5);
    no recipe or workflow generates it. A config whose usage line is
    ``git cliff --output CHANGELOG.md`` tells the reader to replace that curated
    history with commit subjects (``chore`` commits skipped). F-OPS-21@claude."""
    assert _tracked_mentions("--output CHANGELOG.md") == []
