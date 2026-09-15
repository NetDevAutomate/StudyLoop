"""Unit tests for tests/acceptance/evidence.py's minimal bundle writer.

Deliberately OUTSIDE tests/acceptance/ and carrying no `acceptance` marker
-- same rationale as test_acceptance_isolation.py and
test_acceptance_turn_script.py: this tests the writer itself, not a live
product session, so it must run under the default `just test` gate.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_tests_dir = Path(__file__).parent
if str(_tests_dir) not in sys.path:
    sys.path.insert(0, str(_tests_dir))

from acceptance.evidence import UnsafeRunIdError, write_evidence_bundle  # noqa: E402


class TestWriteEvidenceBundle:
    def test_writes_manifest_and_turns(self, tmp_path: Path) -> None:
        bundle = write_evidence_bundle(
            tmp_path,
            run_id="codex-run-001",
            harness="codex",
            actor="scripted",
            outcome="completed",
            turns=[{"prompt": "what is a decorator?", "pane_output": "reply: ..."}],
        )

        assert bundle.run_dir == tmp_path / "codex-run-001"
        manifest = json.loads(bundle.manifest_path.read_text())
        assert manifest == {
            "run_id": "codex-run-001",
            "harness": "codex",
            "actor": "scripted",
            "outcome": "completed",
            "turn_count": 1,
            "platform": None,
            "auth_mode": None,
            "harness_version": None,
        }
        turns = json.loads(bundle.turns_path.read_text())
        assert turns == [{"prompt": "what is a decorator?", "pane_output": "reply: ..."}]

    def test_records_platform_auth_mode_and_harness_version_when_provided(
        self, tmp_path: Path
    ) -> None:
        """D-21(7): a recorded live run's bundle must carry the harness
        version, platform, and auth mode alongside the pane transcript --
        not just the narrower run_id/harness/actor/outcome shape this
        writer started with."""
        bundle = write_evidence_bundle(
            tmp_path,
            run_id="claude-run-001",
            harness="claude",
            actor="scripted",
            outcome="completed",
            turns=[],
            platform="macOS-15.0-arm64",
            auth_mode="presence-only",
            harness_version="1.2.3",
        )

        manifest = json.loads(bundle.manifest_path.read_text())
        assert manifest["platform"] == "macOS-15.0-arm64"
        assert manifest["auth_mode"] == "presence-only"
        assert manifest["harness_version"] == "1.2.3"

    def test_rejects_empty_run_id(self, tmp_path: Path) -> None:
        with pytest.raises(UnsafeRunIdError):
            write_evidence_bundle(
                tmp_path,
                run_id="",
                harness="codex",
                actor="scripted",
                outcome="completed",
                turns=[],
            )

    @pytest.mark.parametrize("bad_run_id", ["../escape", "a/b", "/etc/passwd", ".hidden"])
    def test_rejects_run_ids_that_could_escape_the_evidence_root(
        self, tmp_path: Path, bad_run_id: str
    ) -> None:
        with pytest.raises(UnsafeRunIdError):
            write_evidence_bundle(
                tmp_path,
                run_id=bad_run_id,
                harness="codex",
                actor="scripted",
                outcome="completed",
                turns=[],
            )
        # Nothing must have been created outside tmp_path's own children.
        assert list(tmp_path.iterdir()) == []

    def test_reusing_a_run_id_under_the_same_root_fails_loudly(self, tmp_path: Path) -> None:
        write_evidence_bundle(
            tmp_path, run_id="dup", harness="codex", actor="scripted", outcome="completed", turns=[]
        )
        with pytest.raises(FileExistsError):
            write_evidence_bundle(
                tmp_path,
                run_id="dup",
                harness="codex",
                actor="scripted",
                outcome="completed",
                turns=[],
            )

    def test_manifest_field_names_are_a_subset_of_b4s_described_schema(
        self, tmp_path: Path
    ) -> None:
        """Structural note, not a copy of B4's schema: the field NAMES this
        minimal writer uses (run_id/harness/actor/outcome) must already
        match what B4's full writer describes, so migrating callers to
        B4's real writer later is a rename, not a rewrite."""
        bundle = write_evidence_bundle(
            tmp_path,
            run_id="shape",
            harness="claude",
            actor="scripted",
            outcome="completed",
            turns=[],
        )
        manifest_fields = set(json.loads(bundle.manifest_path.read_text()))
        assert manifest_fields >= {"run_id", "harness", "actor", "outcome"}
