"""Tests for pi and omp harness wiring in installers.py.

Covers:
- _AGENT_CHOICES includes pi and omp
- _HARNESS_EXPORT has entries for pi and omp with the correct flags
- install_session_db_mandate writes a file with the correct flag and sentinel
- detect_available_agent_tools detects pi when ~/.pi exists, omp when ~/.omp exists
- doctor check_harness_export emits results for pi/omp when detected
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import studyloop.installers as installers
from studyloop.installers import _HarnessExport

# ---------------------------------------------------------------------------
# Static registry assertions (no I/O)
# ---------------------------------------------------------------------------


def test_agent_choices_includes_pi_and_omp() -> None:
    assert "pi" in installers._AGENT_CHOICES
    assert "omp" in installers._AGENT_CHOICES


def test_harness_export_has_pi_with_correct_flag() -> None:
    assert "pi" in installers._HARNESS_EXPORT
    assert installers._HARNESS_EXPORT["pi"].export_flag == "pi-only"


def test_harness_export_has_omp_with_correct_flag() -> None:
    assert "omp" in installers._HARNESS_EXPORT
    assert installers._HARNESS_EXPORT["omp"].export_flag == "omp-only"


def test_harness_export_pi_steering_path_ends_correctly() -> None:
    path = installers._HARNESS_EXPORT["pi"].steering_path
    assert path.parts[-1] == "session-db.md"
    assert ".pi" in path.parts
    assert "agent" in path.parts


def test_harness_export_omp_steering_path_ends_correctly() -> None:
    path = installers._HARNESS_EXPORT["omp"].steering_path
    assert path.parts[-1] == "session-db.md"
    assert ".omp" in path.parts
    assert "agent" in path.parts


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents/shared/session-db-mandate.md").exists():
        root = root.parent
    assert (root / "agents/shared/session-db-mandate.md").exists(), "template not found"
    return root


@pytest.fixture
def home_pi_omp(tmp_path: Path):
    """Patch installer HOME + harness map to a sandbox with pi and omp entries."""
    pi_steer = tmp_path / ".pi/agent/session-db.md"
    omp_steer = tmp_path / ".omp/agent/session-db.md"
    harness_map = {
        "pi": _HarnessExport(pi_steer, "pi-only"),
        "omp": _HarnessExport(omp_steer, "omp-only"),
    }
    with (
        patch.object(installers, "_HOME", tmp_path),
        patch.object(installers, "_HARNESS_EXPORT", harness_map),
    ):
        yield tmp_path


# ---------------------------------------------------------------------------
# install_session_db_mandate for pi and omp
# ---------------------------------------------------------------------------


class TestMandatePiOmp:
    def test_writes_pi_mandate_with_flag_and_sentinel(
        self, repo_root: Path, home_pi_omp: Path
    ) -> None:
        result = installers.install_session_db_mandate(repo_root, tools=["pi"])
        assert result == {"pi": 1}
        text = (home_pi_omp / ".pi/agent/session-db.md").read_text()
        assert "session-export --pi-only" in text
        assert installers._MANDATE_SENTINEL in text

    def test_writes_omp_mandate_with_flag_and_sentinel(
        self, repo_root: Path, home_pi_omp: Path
    ) -> None:
        result = installers.install_session_db_mandate(repo_root, tools=["omp"])
        assert result == {"omp": 1}
        text = (home_pi_omp / ".omp/agent/session-db.md").read_text()
        assert "session-export --omp-only" in text
        assert installers._MANDATE_SENTINEL in text

    def test_idempotent_pi(self, repo_root: Path, home_pi_omp: Path) -> None:
        installers.install_session_db_mandate(repo_root, tools=["pi"])
        again = installers.install_session_db_mandate(repo_root, tools=["pi"])
        assert again == {"pi": 0}

    def test_idempotent_omp(self, repo_root: Path, home_pi_omp: Path) -> None:
        installers.install_session_db_mandate(repo_root, tools=["omp"])
        again = installers.install_session_db_mandate(repo_root, tools=["omp"])
        assert again == {"omp": 0}

    def test_writes_both_pi_and_omp(self, repo_root: Path, home_pi_omp: Path) -> None:
        result = installers.install_session_db_mandate(repo_root, tools=["pi", "omp"])
        assert result == {"pi": 1, "omp": 1}


# ---------------------------------------------------------------------------
# detect_available_agent_tools — pi / omp detection
# ---------------------------------------------------------------------------


class TestDetectPiOmp:
    def test_pi_detected_when_dot_pi_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".pi").mkdir()
        with patch.object(installers, "_HOME", tmp_path):
            detected = installers.detect_available_agent_tools()
        assert "pi" in detected

    def test_omp_detected_when_dot_omp_exists(self, tmp_path: Path) -> None:
        (tmp_path / ".omp").mkdir()
        with patch.object(installers, "_HOME", tmp_path):
            detected = installers.detect_available_agent_tools()
        assert "omp" in detected

    def test_pi_absent_when_dot_pi_missing(self, tmp_path: Path) -> None:
        with patch.object(installers, "_HOME", tmp_path):
            detected = installers.detect_available_agent_tools()
        assert "pi" not in detected

    def test_omp_absent_when_dot_omp_missing(self, tmp_path: Path) -> None:
        with patch.object(installers, "_HOME", tmp_path):
            detected = installers.detect_available_agent_tools()
        assert "omp" not in detected

    def test_both_detected_together(self, tmp_path: Path) -> None:
        (tmp_path / ".pi").mkdir()
        (tmp_path / ".omp").mkdir()
        with patch.object(installers, "_HOME", tmp_path):
            detected = installers.detect_available_agent_tools()
        assert "pi" in detected
        assert "omp" in detected


# ---------------------------------------------------------------------------
# Doctor check_harness_export — pi / omp coverage
# ---------------------------------------------------------------------------


class TestDoctorPiOmp:
    def test_warns_before_fix_then_passes_after_fix(
        self, repo_root: Path, home_pi_omp: Path
    ) -> None:
        from studyloop.doctor.harness import check_harness_export

        with patch.object(installers, "detect_available_agent_tools", return_value=["pi", "omp"]):
            before = {r.name: r.status for r in check_harness_export()}

        assert before["export_mandate_pi"] == "warn"
        assert before["export_mandate_omp"] == "warn"

        installers.install_session_db_mandate(repo_root, tools=["pi", "omp"])

        with patch.object(installers, "detect_available_agent_tools", return_value=["pi", "omp"]):
            after = {r.name: r.status for r in check_harness_export()}

        assert after["export_mandate_pi"] == "pass"
        assert after["export_mandate_omp"] == "pass"

    def test_pi_check_is_auto_fixable_warn(self, home_pi_omp: Path) -> None:
        from studyloop.doctor.harness import check_harness_export

        with patch.object(installers, "detect_available_agent_tools", return_value=["pi"]):
            results = check_harness_export()

        assert results
        warn = [r for r in results if r.status == "warn"]
        assert warn
        assert all(r.fix_auto for r in warn)
        assert all(r.category == "harness" for r in results)

    def test_omp_check_is_auto_fixable_warn(self, home_pi_omp: Path) -> None:
        from studyloop.doctor.harness import check_harness_export

        with patch.object(installers, "detect_available_agent_tools", return_value=["omp"]):
            results = check_harness_export()

        assert results
        warn = [r for r in results if r.status == "warn"]
        assert warn
        assert all(r.fix_auto for r in warn)
        assert all(r.category == "harness" for r in results)
