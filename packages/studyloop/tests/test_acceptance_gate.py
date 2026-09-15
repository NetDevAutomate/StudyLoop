"""Structural + subprocess tests for the `acceptance` marker and testacc gate.

D-13 (council ruling): pytest silently DESELECTS tests under a marker excluded
by addopts, so verifying the skip reason requires an EXPLICITLY-SELECTING
subprocess run (``-m acceptance``) rather than the default in-process run
these tests otherwise share. These tests therefore live at the top level of
``tests/``, not under ``tests/acceptance/`` -- if they lived under the gated
tree they would themselves be skipped by the very fixture they verify.

See docs/acceptance-testing.md for the tiers table and every env var.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ROOT_PYPROJECT = REPO_ROOT / "pyproject.toml"
STUDYLOOP_PYPROJECT = REPO_ROOT / "packages" / "studyloop" / "pyproject.toml"
STUDYLOOP_PKG_DIR = REPO_ROOT / "packages" / "studyloop"
ACCEPTANCE_DIR = Path(__file__).resolve().parent / "acceptance"


def _pytest_ini_options(pyproject: Path) -> dict:
    data = tomllib.loads(pyproject.read_text())
    return data["tool"]["pytest"]["ini_options"]


# ---------------------------------------------------------------------------
# (c) marker registration -- structural set test, both pyprojects (E-B1 rule)
# ---------------------------------------------------------------------------


class TestMarkerRegistration:
    @pytest.mark.parametrize("pyproject", [ROOT_PYPROJECT, STUDYLOOP_PYPROJECT])
    def test_marker_registered(self, pyproject: Path) -> None:
        opts = _pytest_ini_options(pyproject)
        names = {m.split(":", 1)[0].strip() for m in opts["markers"]}
        assert "acceptance" in names, f"{pyproject} does not register the acceptance marker"

    @pytest.mark.parametrize("pyproject", [ROOT_PYPROJECT, STUDYLOOP_PYPROJECT])
    def test_marker_deselected_by_default(self, pyproject: Path) -> None:
        opts = _pytest_ini_options(pyproject)
        assert "not acceptance" in opts["addopts"], (
            f"{pyproject} addopts does not deselect -m acceptance by default"
        )


# ---------------------------------------------------------------------------
# (a) without STUDYLOOP_ACC every acceptance test reports the skip reason
# ---------------------------------------------------------------------------


class TestGateSkipReason:
    def test_unset_env_skips_with_reason(self) -> None:
        env = {**os.environ}
        env.pop("STUDYLOOP_ACC", None)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "acceptance",
                "-rs",
                "--no-header",
                str(ACCEPTANCE_DIR),
            ],
            cwd=STUDYLOOP_PKG_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        combined = result.stdout + result.stderr
        assert "STUDYLOOP_ACC=1" in combined, combined[-4000:]
        assert "skipped" in combined.lower(), combined[-4000:]


# ---------------------------------------------------------------------------
# (g) structural: nightly workflows never opt in to STUDYLOOP_ACC/UAT (D-24)
# ---------------------------------------------------------------------------


class TestNightlyWorkflowNeverOptsIn:
    @pytest.mark.parametrize(
        "workflow",
        sorted((REPO_ROOT / ".github" / "workflows").glob("nightly-*.yml")),
        ids=lambda p: p.name,
    )
    def test_no_acceptance_or_uat_opt_in(self, workflow: Path) -> None:
        text = workflow.read_text()
        assert "STUDYLOOP_ACC" not in text, f"{workflow} sets/references STUDYLOOP_ACC"
        assert "STUDYLOOP_UAT" not in text, f"{workflow} sets/references STUDYLOOP_UAT"


# ---------------------------------------------------------------------------
# (h) `just` recipe args are POSITIONAL -- not make-style KEY=value (grok F11)
# ---------------------------------------------------------------------------


class TestJustRecipeArgumentSyntax:
    def test_positional_args_substitute(self) -> None:
        result = subprocess.run(
            ["just", "--dry-run", "testacc", "kiro", "scripted", "tests/acceptance/test_x.py"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        # `just --dry-run` prints the substituted recipe body to STDERR.
        assert result.returncode == 0, result.stderr
        assert 'STUDYLOOP_ACC_HARNESS="kiro"' in result.stderr
        assert 'STUDYLOOP_ACC_ACTOR="scripted"' in result.stderr
        assert "tests/acceptance/test_x.py" in result.stderr

    def test_make_style_assignment_is_not_supported(self) -> None:
        """Documents the footgun: `just testacc HARNESS=kiro` does not set HARNESS.

        ``just`` recipe parameters are positional. Passing ``HARNESS=kiro``
        binds it as the LITERAL first positional value -- it does not become
        a keyword the way a make variable assignment would. This is exactly
        the "assuming make-style assignments" trap the contract (grok F11)
        warns against; docs/acceptance-testing.md must tell users to invoke
        positionally, and this test is the receipt that the footgun is real.
        """
        result = subprocess.run(
            ["just", "--dry-run", "testacc", "HARNESS=kiro"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        assert 'STUDYLOOP_ACC_HARNESS="HARNESS=kiro"' in result.stderr
