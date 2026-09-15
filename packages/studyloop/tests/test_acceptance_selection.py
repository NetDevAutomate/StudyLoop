"""HARNESS/ACTOR selection parsing + the "unknown value fails loudly" rule.

Council D-13: an unknown ``STUDYLOOP_ACC_HARNESS``/``STUDYLOOP_ACC_ACTOR``
value must FAIL the run, never silently skip or silently no-op. The parse
helpers (pure) are unit-tested directly; the fail-loudly behaviour is proven
through an EXPLICITLY-SELECTING subprocess (same rationale as
test_acceptance_gate.py::TestGateSkipReason -- deselected tests report
nothing).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

_tests_dir = Path(__file__).resolve().parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.conftest import selected_actor, selected_harnesses  # noqa: E402

if TYPE_CHECKING:
    import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
STUDYLOOP_PKG_DIR = REPO_ROOT / "packages" / "studyloop"
ACCEPTANCE_DIR = _tests_dir / "acceptance"


class TestSelectionParsing:
    def test_harness_default_is_all_six(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STUDYLOOP_ACC_HARNESS", raising=False)
        assert set(selected_harnesses()) == {"kiro", "codex", "claude", "opencode", "pi", "grok"}

    def test_harness_comma_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("STUDYLOOP_ACC_HARNESS", "kiro, codex")
        assert selected_harnesses() == ("kiro", "codex")

    def test_actor_default_is_scripted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("STUDYLOOP_ACC_ACTOR", raising=False)
        assert selected_actor() == "scripted"


class TestUnknownValuesFailLoudly:
    def _run(self, env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
        env = {**os.environ, "STUDYLOOP_ACC": "1", **env_overrides}
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "acceptance",
                "-k",
                "named_skip",  # avoid ever touching the live Kiro lane test
                "--no-header",
                str(ACCEPTANCE_DIR),
            ],
            cwd=STUDYLOOP_PKG_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_unknown_harness_fails_not_skips(self) -> None:
        result = self._run({"STUDYLOOP_ACC_HARNESS": "not-a-real-harness"})
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined[-4000:]
        assert "unknown" in combined.lower(), combined[-4000:]
        assert "not-a-real-harness" in combined, combined[-4000:]

    def test_unknown_actor_fails_not_skips(self) -> None:
        result = self._run({"STUDYLOOP_ACC_ACTOR": "not-a-real-actor"})
        combined = result.stdout + result.stderr
        assert result.returncode != 0, combined[-4000:]
        assert "unknown" in combined.lower(), combined[-4000:]
        assert "not-a-real-actor" in combined, combined[-4000:]


class TestHarnessSelectionGatesTheKiroLane:
    """(finding 4) STUDYLOOP_ACC_HARNESS must actually SELECT, not just parse
    and validate -- otherwise `just testacc codex` still starts a real,
    billed Kiro session it was never asked to select."""

    def test_kiro_lane_named_skips_when_harness_not_selected(self) -> None:
        env = {
            **os.environ,
            "STUDYLOOP_ACC": "1",
            "STUDYLOOP_ACC_HARNESS": "codex",
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "acceptance",
                "-k",
                "test_scripted_learner_completes_a_full_lifecycle",
                "-rs",
                "--no-header",
                str(ACCEPTANCE_DIR),
            ],
            cwd=STUDYLOOP_PKG_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        combined = result.stdout + result.stderr
        assert result.returncode == 0, combined[-4000:]
        assert "1 skipped" in combined, combined[-4000:]
        assert "kiro not selected" in combined.lower(), combined[-4000:]
