"""Persona A and Persona B scripted acceptance journeys (module-contract v1, design.md §6; lane U1).

Two representative users drive the REAL product -- a subprocess ``studyloop web`` with the
deterministic harness agent, the real CLI in subprocesses, a real headless browser -- at the
acceptance tier (``STUDYLOOP_ACC=1``; ``just testacc TESTS=<this file>``). Each persona is one
class: ordered phases sharing one world (lane W's pattern in ``e2e/test_module_labs_journey.py``,
re-expressed here with the §6 additions), a ``WallClockBudget`` the last phase asserts, and a
failure bundle written on ANY phase failure (``personas/bundle.py``: server log, CLI transcript,
``modules.lock.json`` diff, attempt envelope, screenshot, HTML, console -- redacted, verified).

Persona A -- AuDHD learner on a tablet over ``--lan`` (viewport 820x1180, budget 6 min)
  a1 load: no Labs entry, no prerequisite text anywhere
  a2 `module add <valid-scaffold>` via the CLI; reload; exactly one Labs entry, ids + prompts only
  a3 start one drill: inside the single claimed session, no `module-attempts` appears
  a4a focus lands in the terminal                       -- xfail(strict): gap, see the test
  a4b Tab / Shift-Tab traverse the Labs controls, focus visible (Escape is a5's cancel key)
  a5 Escape cancels: the recovery copy quoted in the test, the session where it was
  a6 reload re-attaches: same study_session_id, still one console
  a7 the missing-`kind` module: `add` accepts a conforming module (proposal §7), `doctor` names
     `kind` concisely, `drill` refuses before consent; nothing created; one Labs entry still
  a8 `module remove`; reload; Labs gone
  a9 the wall clock: under 6 minutes, measured
  Throughout: no overdue counter, no hint, no solution, no mentor notes in the rendered text.

Persona B -- new contributor on a clean machine (viewport 1440x900, budget 8 min)
  b1 the documented `uv` setup commands (docs/contributor-environment.md) that need no network
  b2 `module new` scaffolds   b3 `module check` passes it
  b4-b7 the Persona-A lifecycle on the contributor's own module:
        add -> Labs -> start -> cancel -> remove
  b8 break one fixture (remove `cleanupCommand` from a kubeconfig-context copy -> MC017), read the
     `--json` failure (rule id, file, line), repair it, re-check green
  b9 the docs' commands and the observed output agree (module-contract.md, cli-reference.md)
  b10 the wall clock: under 8 minutes, measured

Red-first (briefs/U1-persona-journeys.md): every phase is red "before the fixture flips it".
``STUDYLOOP_ACC_FORCE_FAIL=<phase id>`` flips THAT phase's precondition -- the CLI call it
depends on is skipped, or the opposite state is set up -- so its first assertion fails on its
own merit and the failure bundle is written. The transcripts live under
``openspec/changes/module-contract-v1/evidence/U1/``; the forced-failure bundle proof is
``evidence/U1/forced-failure-bundle/`` (``STUDYLOOP_ACC_FORCE_FAIL=a5``).

Run:  just testacc "" scripted packages/studyloop/tests/acceptance/test_module_personas.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from .evidence import write_evidence_bundle
from .personas.bundle import (
    EXPECTED_MEMBERS,
    VIOLATIONS_NAME,
    CliRecord,
    write_persona_failure_bundle,
)
from .uat.redaction import contains_forbidden_content

_tests_dir = str(Path(__file__).resolve().parent.parent)
if _tests_dir not in sys.path:
    sys.path.insert(0, _tests_dir)

# Lane W's PUBLIC constants only; its helpers are private and copied into personas/world.py.
from e2e.test_module_labs_journey import DRILL_REF  # noqa: E402

pytestmark = [
    pytest.mark.acceptance,
    pytest.mark.timeout(600),
    # Markers run before ANY fixture: without this the session-scoped Playwright `browser`
    # would launch Chromium before the tier's function-scoped gate could skip (the lesson
    # `conftest.not_selected_marker` records). The autouse `_acceptance_gate` still runs.
    pytest.mark.skipif(
        os.environ.get("STUDYLOOP_ACC") != "1",
        reason="acceptance tests require STUDYLOOP_ACC=1 (see docs/acceptance-testing.md)",
    ),
]

# NOTE (commit 2 of lane U1): the persona classes land in the next two commits, each with its
# red/green transcripts; this commit carries the bundle-writer mechanics they stand on.

# ---------------------------------------------------------------------------
# The failure bundle -- mechanics, without a browser (the forced-failure proof is a run, see
# evidence/U1/forced-failure-bundle/)
# ---------------------------------------------------------------------------


class TestBundleWriter:
    def test_positive_control_the_detector_flags_dirty_input(self) -> None:
        """Prove the UAT detector flags what the bundle must not carry BEFORE trusting it to
        certify a bundle clean (acceptance/uat/redaction.py's own instruction)."""
        dirty = "wrote /Users/someone/.config/studyloop/modules.lock.json with sk-abcdefghijklmnop"
        violations = contains_forbidden_content(dirty)
        assert any("home path" in v for v in violations), violations
        assert any("key-like" in v for v in violations), violations

    def test_failure_bundle_carries_the_seven_artefacts_redacted(self, tmp_path: Path) -> None:
        home = tmp_path / "home"
        lan_credential = "lan-" + "x" * 20  # a stand-in for the run's --lan credential
        bundle, violations = write_persona_failure_bundle(
            tmp_path / "evidence",
            run_id="unit-bundle",
            persona="A",
            outcome="forced",
            phases=[{"phase": "a1", "status": "passed", "elapsed_s": 0.1}],
            server_log=f"LAN password: {lan_credential}\nvault {home}/study-materials\n"
            f"digest sha256:{'ab' * 32}\n",
            cli_records=[
                CliRecord(("module", "add", str(home / "mod")), "", 0, "installed\n", "", 0.2)
            ],
            lockfile_before=None,
            lockfile_after=json.dumps({"modules": [{"id": "echo-drills", "digest": "ab" * 32}]}),
            attempt_envelope={"labs_drill": {"ref": DRILL_REF}, "path": str(home)},
            screenshot_png=b"\x89PNG\r\n\x1a\n",
            page_html=f"<html><body>{home}</body></html>",
            console={"errors": [f"console.error: {home}/x.js"], "api_calls": []},
            homes=[home],
            secrets={"lan_password": lan_credential},
        )
        names = {p.name for p in bundle.run_dir.iterdir()}
        assert set(EXPECTED_MEMBERS) <= names, sorted(names)
        assert VIOLATIONS_NAME not in names, (bundle.run_dir / VIOLATIONS_NAME).read_text()
        assert violations == []
        manifest = json.loads(bundle.manifest_path.read_text())
        assert manifest["artifacts"] == {
            "server_log": "server.log",
            "cli_transcript": "cli-transcript.txt",
            "lockfile_diff": "modules.lock.diff",
            "attempt_envelope": "attempt-envelope.json",
        }
        server_log = (bundle.run_dir / "server.log").read_text()
        assert "<REDACTED:lan_password>" in server_log and lan_credential not in server_log
        assert "<HOME>/study-materials" in server_log
        assert "sha256:abababababab…" in server_log, server_log
        diff = (bundle.run_dir / "modules.lock.diff").read_text()
        assert diff.startswith("--- modules.lock.json (before)") and "+{" in diff, diff
        transcript = (bundle.run_dir / "cli-transcript.txt").read_text()
        assert "$ studyloop module add <HOME>/mod" in transcript and "[exit 0" in transcript
        envelope = json.loads((bundle.run_dir / "attempt-envelope.json").read_text())
        assert envelope == {
            "persona": "A",
            "envelope": {"labs_drill": {"ref": DRILL_REF}, "path": "<HOME>"},
        }

    def test_write_evidence_bundle_without_members_keeps_the_pre_u1_manifest(
        self, tmp_path: Path
    ) -> None:
        """Existing callers must not change: no member passed -> the eight keys, no `artifacts`."""
        bundle = write_evidence_bundle(
            tmp_path,
            run_id="plain",
            harness="codex",
            actor="scripted",
            outcome="completed",
            turns=[],
        )
        manifest = json.loads(bundle.manifest_path.read_text())
        assert set(manifest) == {
            "run_id",
            "harness",
            "actor",
            "outcome",
            "turn_count",
            "platform",
            "auth_mode",
            "harness_version",
        }
        assert bundle.server_log_path is None and bundle.attempt_envelope_path is None
        assert {p.name for p in bundle.run_dir.iterdir()} == {"manifest.json", "turns.json"}
