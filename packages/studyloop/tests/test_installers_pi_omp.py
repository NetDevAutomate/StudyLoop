"""Installer and doctor coverage for the pi release harness."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

import studyloop.installers as installers
from studyloop.installers import _HarnessExport


def test_agent_choices_match_release_harnesses() -> None:
    from studyloop.harnesses import RELEASE_HARNESSES

    assert installers._AGENT_CHOICES == RELEASE_HARNESSES


def test_harness_export_has_pi_with_native_flag() -> None:
    spec = installers._HARNESS_EXPORT["pi"]
    assert spec.export_flag == "pi-only"
    assert spec.steering_path.parts[-3:] == (".pi", "agent", "session-db.md")


@pytest.fixture
def repo_root() -> Path:
    root = Path(__file__).resolve()
    while root != root.parent and not (root / "agents/shared/session-db-mandate.md").exists():
        root = root.parent
    assert (root / "agents/shared/session-db-mandate.md").exists()
    return root


@pytest.fixture
def pi_home(tmp_path: Path):
    steering = tmp_path / ".pi/agent/session-db.md"
    with (
        patch.object(installers, "_HOME", tmp_path),
        patch.object(
            installers,
            "_HARNESS_EXPORT",
            {"pi": _HarnessExport(steering, "pi-only")},
        ),
    ):
        yield tmp_path


def test_pi_mandate_is_native_and_idempotent(repo_root: Path, pi_home: Path) -> None:
    assert installers.install_session_db_mandate(repo_root, tools=["pi"]) == {"pi": 1}
    text = (pi_home / ".pi/agent/session-db.md").read_text(encoding="utf-8")
    assert "session-export --pi-only" in text
    assert installers._MANDATE_SENTINEL in text
    assert installers.install_session_db_mandate(repo_root, tools=["pi"]) == {"pi": 0}


def test_pi_detection_accepts_binary_or_home(tmp_path: Path) -> None:
    with (
        patch.object(installers, "_HOME", tmp_path),
        patch.object(
            installers.shutil,
            "which",
            side_effect=lambda binary: "/usr/bin/pi" if binary == "pi" else None,
        ),
    ):
        assert "pi" in installers.detect_available_agent_tools()

    with (
        patch.object(installers, "_HOME", tmp_path),
        patch.object(installers.shutil, "which", return_value=None),
    ):
        assert "pi" not in installers.detect_available_agent_tools()

    (tmp_path / ".pi").mkdir()
    with (
        patch.object(installers, "_HOME", tmp_path),
        patch.object(installers.shutil, "which", return_value=None),
    ):
        assert "pi" in installers.detect_available_agent_tools()


def test_pi_doctor_warns_then_passes(repo_root: Path, pi_home: Path) -> None:
    from studyloop.doctor.harness import check_harness_export

    with patch.object(installers, "detect_available_agent_tools", return_value=["pi"]):
        before = {result.name: result for result in check_harness_export()}
    assert before["export_mandate_pi"].status == "warn"
    assert before["export_mandate_pi"].fix_auto is True

    installers.install_session_db_mandate(repo_root, tools=["pi"])
    with patch.object(installers, "detect_available_agent_tools", return_value=["pi"]):
        after = {result.name: result for result in check_harness_export()}
    assert after["export_mandate_pi"].status == "pass"
