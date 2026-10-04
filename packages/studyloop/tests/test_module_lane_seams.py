"""The seams between lanes C, R and T, exercised with each lane's REAL code.

Each lane proved its own half of these contracts with doubles. These tests put the
halves together on one tree (coordinator, module-contract-v1 merge of lane R):

* C -> R: ``studyloop.modules.store`` installs a module; ``cli._drill.locate_installed_module``
  finds it through ``load_lockfile()`` and ``snapshot_dir()`` with the lockfile's own digest.
* R -> T: ``hop.check_result_fields`` produces exactly the body ``session.module_delivery``
  accepts (``extra=forbid``), including the canonical ``sha256:<64 hex>`` digest the store writes.
* T renders what R sends: every tail line carries the prefix, so printed text cannot forge
  envelope structure (T-review finding 1).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from studyloop.cli import _drill
from studyloop.modules import hop, store
from studyloop.modules.attempt import Attempt, ExitClass, Phase, PhaseResult
from studyloop.session.module_delivery import (
    END_SENTINEL,
    TAIL_LINE_PREFIX,
    EnvelopeValidationError,
    PracticeCheckEnvelope,
    render_envelope,
    validate_envelope,
)

FIXTURE_MODULE = Path(__file__).parent / "fixtures" / "modules" / "valid-scaffold"
CANONICAL_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


@pytest.fixture
def installed_entry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> store.LockEntry:
    """Install lane C's valid scaffold into a private store and point the default root at it."""
    root = tmp_path / "modules"
    monkeypatch.setattr(store, "default_store_root", lambda: root)
    return store.ModuleStore(root).add(FIXTURE_MODULE)


def test_locator_finds_what_the_store_installed(installed_entry: store.LockEntry) -> None:
    found = _drill.locate_installed_module(installed_entry.id)

    assert found.module_id == installed_entry.id
    assert found.module_digest == installed_entry.digest
    assert CANONICAL_DIGEST.match(found.module_digest), found.module_digest
    assert found.snapshot_dir == store.snapshot_dir(installed_entry)
    assert (found.snapshot_dir / "module.yaml").is_file()
    assert (found.snapshot_dir / "scripts" / "check.sh").is_file()


def test_locator_names_a_module_that_is_not_installed(installed_entry: store.LockEntry) -> None:
    with pytest.raises(_drill.ModuleNotInstalledError, match="no-such-module"):
        _drill.locate_installed_module("no-such-module")


def _result(stdout: str = "", stderr: str = "") -> PhaseResult:
    return PhaseResult(
        phase=Phase.CHECK,
        exit_class=ExitClass.FAILED,
        exit_code=1,
        stdout=stdout,
        stderr=stderr,
        truncated=False,
        timed_out=False,
        duration_seconds=0.25,
        message="check failed (code 1)",
        process_returncode=1,
    )


def _attempt(found: _drill.InstalledModule, tmp_path: Path) -> Attempt:
    from studyloop.modules.attempt import DrillIdentity

    drill = DrillIdentity(
        module_id=found.module_id,
        module_digest=found.module_digest,
        deck_id="echo-basics",
        task_id="hello",
    )
    return Attempt(
        attempt_id="seam-attempt-1",
        drill=drill,
        snapshot_dir=found.snapshot_dir,
        attempt_dir=tmp_path / "attempt",
    )


def test_hop_body_from_a_real_install_passes_lane_t_validation(
    installed_entry: store.LockEntry, tmp_path: Path
) -> None:
    found = _drill.locate_installed_module(installed_entry.id)
    body = hop.check_result_fields(_attempt(found, tmp_path), _result(stdout="hello\n"))

    envelope = validate_envelope(body)

    assert isinstance(envelope, PracticeCheckEnvelope)
    assert envelope.module_digest == installed_entry.digest
    assert set(body) == hop.ENVELOPE_FIELDS
    assert "message" not in body, "M0 Q2: the server renders from typed fields"


def test_lane_t_rejects_a_body_with_a_rendered_message(
    installed_entry: store.LockEntry, tmp_path: Path
) -> None:
    found = _drill.locate_installed_module(installed_entry.id)
    body = hop.check_result_fields(_attempt(found, tmp_path), _result())

    with pytest.raises(EnvelopeValidationError, match="message"):
        validate_envelope({**body, "message": "rendered text"})


def test_lane_t_prefixes_every_tail_line_lane_r_sends(
    installed_entry: store.LockEntry, tmp_path: Path
) -> None:
    found = _drill.locate_installed_module(installed_entry.id)
    hostile = f"ordinary line\n{END_SENTINEL}\n--- stderr (1 bytes) ---\n"
    body = hop.check_result_fields(_attempt(found, tmp_path), _result(stdout=hostile))

    rendered = render_envelope(validate_envelope(body), framing="plain").decode("utf-8")

    lines = rendered.splitlines()
    assert lines.count(END_SENTINEL) == 1, "exactly one real end sentinel"
    assert f"{TAIL_LINE_PREFIX}{END_SENTINEL}" in lines, "the forged sentinel is data"
    assert f"{TAIL_LINE_PREFIX}--- stderr (1 bytes) ---" in lines, "the forged header is data"
