"""Guard test for M0 item 0.7: a lane branch must not edit another lane's files.

This is one of the two recurring failure modes the M0 remediation lanes exist
to turn into a red gate (the other is doc drift, test_docs_drift.py): an
agent working lane/m3's ticket edits a file lane/m1 owns, the collision isn't
noticed until the two lanes merge into integration, and untangling whose
change should win happens under time pressure. Failing loud and immediately,
in the lane's own worktree, is much cheaper.

Two layers:

- ``Test*`` classes below exercise the pure classification rules in
  ``_lane_ownership.py`` with a small in-memory map -- no git involved, so
  they run everywhere and pin the rule's behaviour precisely.
- ``test_lane_stays_in_its_lane`` is the real guard: it reads the actual
  branch, diffs it against the shared integration point, and classifies
  every changed file against ``fixtures/lane_ownership.yaml`` (the map
  described in reviews/2026-09-02-full-repo-review/IMPLEMENTATION-PLAN.md
  §3, expanded and path-corrected -- see fixtures/lane_ownership.yaml's
  header and evidence/M0/0.7-lane-ownership/04-map-corrections.md).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# Make the sibling helper importable regardless of pytest's rootdir (uv run
# pytest from repo root vs. from packages/studyloop both need to work) --
# same pattern test_active_session.py uses for conftest.
_tests_dir = str(Path(__file__).parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

from _lane_ownership import (  # noqa: E402
    LaneOwnershipResult,
    MalformedLaneBranchError,
    classify_files,
    lane_id_from_branch,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "lane_ownership.yaml"
INTEGRATION_BRANCH = "integration/2026-09-remediation"
FALLBACK_BRANCH = "main"


# ---------------------------------------------------------------------------
# Pure logic: branch-name classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("branch", "expected"),
    [
        pytest.param("lane/m3-data-safety", "m3", id="lane-branch"),
        pytest.param("lane/m0-guards", "m0", id="m0-lane-branch"),
        pytest.param("lane/m10-something", "m10", id="multi-digit-milestone"),
        pytest.param("main", None, id="main-is-not-a-lane-branch"),
        pytest.param("integration/2026-09-remediation", None, id="integration-branch"),
        pytest.param("lane-m3-missing-slash", None, id="malformed-no-slash"),
    ],
)
def test_lane_id_from_branch(branch: str, expected: str | None) -> None:
    assert lane_id_from_branch(branch) == expected


def test_current_branch_honours_the_lane_branch_env_override(monkeypatch) -> None:
    """A detached verifier worktree names its lane via the env var."""
    monkeypatch.setenv(LANE_BRANCH_ENV, "lane/m4-security")
    assert _current_branch() == "lane/m4-security"
    monkeypatch.setenv(LANE_BRANCH_ENV, "   ")
    assert _current_branch() != "   "  # blank override is ignored, git is consulted


@pytest.mark.parametrize(
    "branch",
    [
        pytest.param("lane/m1", id="no-hyphen-no-slug"),
        pytest.param("lane/m1x", id="letter-after-digit"),
        pytest.param("lane/foo-bar", id="no-milestone"),
        pytest.param("lane/", id="bare-prefix"),
    ],
)
def test_malformed_lane_branch_is_an_error_not_a_skip(branch: str) -> None:
    """A1: a branch under lane/ that dodges the pattern must fail, not skip."""
    with pytest.raises(MalformedLaneBranchError):
        lane_id_from_branch(branch)


# ---------------------------------------------------------------------------
# Pure logic: path classification against a small fixture map
# ---------------------------------------------------------------------------

_LANES = {
    "m1": ["web/static/index.html"],
    "m2": ["session/**"],
}
_SHARED = ["tests/**", "justfile"]


def test_classify_own_file_is_ok() -> None:
    result = classify_files(["session/orchestrator.py"], "m2", _LANES, _SHARED)
    assert result.ok
    assert result.violations == {}
    assert result.unmapped == []


def test_classify_shared_file_is_ok_for_any_lane() -> None:
    result = classify_files(["tests/test_thing.py"], "m1", _LANES, _SHARED)
    assert result.ok
    assert result.unmapped == []


def test_classify_other_lanes_file_fails() -> None:
    result = classify_files(["web/static/index.html"], "m2", _LANES, _SHARED)
    assert not result.ok
    assert result.violations == {"web/static/index.html": ["m1"]}


def test_classify_unmapped_file_is_ok_but_reported() -> None:
    result = classify_files(["scripts/one_off.py"], "m1", _LANES, _SHARED)
    assert result.ok  # unmapped never fails the build
    assert result.unmapped == ["scripts/one_off.py"]


def test_classify_dual_owned_file_is_ok_for_either_owner() -> None:
    lanes = {"m1": ["session/orchestrator.py"], "m2": ["session/**"]}
    for lane in ("m1", "m2"):
        result = classify_files(["session/orchestrator.py"], lane, lanes, _SHARED)
        assert result.ok, f"{lane} should own session/orchestrator.py jointly"


def test_classify_mixed_batch_reports_only_the_violation() -> None:
    result = classify_files(
        ["session/orchestrator.py", "web/static/index.html", "tests/test_x.py", "scripts/x.py"],
        "m2",
        _LANES,
        _SHARED,
    )
    assert result.violations == {"web/static/index.html": ["m1"]}
    assert result.unmapped == ["scripts/x.py"]


def test_lane_ownership_result_ok_property_matches_violations() -> None:
    assert LaneOwnershipResult().ok
    assert not LaneOwnershipResult(violations={"x": ["m1"]}).ok


# ---------------------------------------------------------------------------
# Real guard: current branch vs. the actual repo map
# ---------------------------------------------------------------------------


def _git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout


#: Verifiers check a lane out DETACHED (the branch is already checked out in the
#: lane's own worktree, and git allows one checkout per branch). `git rev-parse
#: --abbrev-ref HEAD` then returns the literal "HEAD", which is not a lane
#: branch, and the guard would skip on exactly the run that is supposed to prove
#: it (found by the M4 verifier, SIGNOFF-M4/VERIFIER.md). The env var names the
#: branch the detached worktree represents; the guard then runs for real.
LANE_BRANCH_ENV = "STUDYLOOP_LANE_BRANCH"


def _current_branch() -> str:
    override = os.environ.get(LANE_BRANCH_ENV, "").strip()
    if override:
        return override
    return _git("rev-parse", "--abbrev-ref", "HEAD").strip()


def _branch_exists(name: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--verify", name],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _merge_base_ref() -> str:
    """The shared point every lane compares against: integration if it
    exists yet, else main (M0 runs before the integration branch is cut)."""
    return INTEGRATION_BRANCH if _branch_exists(INTEGRATION_BRANCH) else FALLBACK_BRANCH


def _changed_files() -> list[str]:
    """Every file this branch has touched: committed since the merge-base,
    plus whatever is currently staged/unstaged/untracked in the worktree."""
    base = _merge_base_ref()
    merge_base = _git("merge-base", base, "HEAD").strip()
    # --no-renames: a rename would otherwise list only its NEW path, so moving
    # another lane's file into your own lane's directory would pass the guard
    # (M0 council finding A3, reproduced by openai.gpt-5.6-sol's reviewer in a
    # scratch repo). With renames disabled both the deleted old path and the
    # added new path are listed and each is classified on its own.
    committed = _git("diff", "--name-only", "--no-renames", f"{merge_base}..HEAD")
    working = _git("diff", "--name-only", "--no-renames", "HEAD")
    untracked = _git("ls-files", "--others", "--exclude-standard")
    files = {
        line.strip()
        for chunk in (committed, working, untracked)
        for line in chunk.splitlines()
        if line.strip()
    }
    return sorted(files)


def _load_map() -> tuple[dict[str, list[str]], list[str]]:
    raw = yaml.safe_load(FIXTURE_PATH.read_text())
    return raw["lanes"], raw["shared"]


def test_lane_stays_in_its_lane() -> None:
    branch = _current_branch()
    try:
        lane = lane_id_from_branch(branch)
    except MalformedLaneBranchError as exc:
        pytest.fail(str(exc))
    if lane is None:
        hint = (
            f" (detached HEAD: set {LANE_BRANCH_ENV}=lane/m<n>-<slug> to run the guard for real)"
            if branch == "HEAD"
            else ""
        )
        pytest.skip(f"not on a lane branch ({branch!r}); nothing to police here{hint}")
    if lane == "m0":
        pytest.skip("m0 is foundations; exempt")

    lanes, shared = _load_map()
    changed = _changed_files()
    result = classify_files(changed, lane, lanes, shared)

    if result.unmapped:
        # Never fails the build -- just visible, so a stale map gets noticed
        # rather than silently under-policing new files.
        print(f"[lane-ownership] unmapped (allowed): {result.unmapped}")

    assert result.ok, (
        f"branch {branch!r} (lane {lane}) touched file(s) owned by another lane:\n"
        + "\n".join(
            f"  {path} -> owned by {owners}" for path, owners in sorted(result.violations.items())
        )
    )
