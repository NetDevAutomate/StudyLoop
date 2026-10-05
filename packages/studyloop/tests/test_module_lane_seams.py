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
import shutil
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


# --- C -> R (W3): the manifest's prerequisites reach the runner's PATH resolution ------------
#
# `_drill.run_drill_phase` carried a TODO: `prerequisites = ()` until lane C's manifest was on
# main. Lane W wires `Manifest.prerequisites[].id` from the located module's `module.yaml`
# into it (W2 brief, owned block #1). The fixture declares none, so a copy declaring `kind`
# (in core's enum, MC005) is installed through the real store; a fake `kind` sits on a scratch
# PATH, which is where `runner.resolve_prerequisites` is told to look.


@pytest.fixture
def installed_with_kind(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> store.LockEntry:
    source = tmp_path / "echo-drills-kind"
    shutil.copytree(FIXTURE_MODULE, source)
    manifest = source / "module.yaml"
    text = manifest.read_text(encoding="utf-8")
    assert "prerequisites: []" in text
    manifest.write_text(
        text.replace("prerequisites: []", "prerequisites:\n  - id: kind\n"), encoding="utf-8"
    )
    root = tmp_path / "modules"
    monkeypatch.setattr(store, "default_store_root", lambda: root)
    monkeypatch.setattr(_drill, "attempts_root", lambda: tmp_path / "module-attempts")
    return store.ModuleStore(root).add(source)


def test_module_prerequisites_are_read_from_the_installed_manifest(
    installed_with_kind: store.LockEntry,
) -> None:
    found = _drill.locate_installed_module(installed_with_kind.id)

    assert _drill.module_prerequisites(found.snapshot_dir) == ("kind",)
    assert _drill.module_prerequisites(store.snapshot_dir(installed_with_kind)) == ("kind",)


def test_manifest_prerequisites_reach_runner_resolve_prerequisites(
    installed_with_kind: store.LockEntry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`studyloop drill check` resolves the declared tool before anyone is asked to consent;
    with the fake `kind` on a scratch PATH the phase reaches the consent prompt, and
    declining runs nothing."""
    from click.testing import CliRunner

    from studyloop.modules import runner

    scratch_bin = tmp_path / "bin"
    scratch_bin.mkdir()
    fake_kind = scratch_bin / "kind"
    fake_kind.write_text("#!/bin/sh\necho fake kind\n", encoding="utf-8")
    fake_kind.chmod(0o755)
    monkeypatch.setenv("PATH", f"{scratch_bin}:/usr/bin:/bin")

    seen: list[tuple[str, ...]] = []
    real_resolve = runner.resolve_prerequisites

    def recording(prerequisites, *, learner_path=None):  # type: ignore[no-untyped-def]
        seen.append(tuple(prerequisites))
        return real_resolve(prerequisites, learner_path=learner_path)

    monkeypatch.setattr(runner, "resolve_prerequisites", recording)

    result = CliRunner().invoke(
        _drill.drill_group,
        ["check", f"{installed_with_kind.id}/echo-basics/echo-01"],
        input="n\n",
    )

    assert seen == [("kind",)], f"the manifest's prerequisites never reached the runner: {seen}"
    assert result.exit_code == 2, result.output
    assert "Not confirmed -- nothing executed." in result.output
    assert str(fake_kind) not in result.output, (
        "the resolved path is the runner's, not the learner's"
    )


def test_a_declared_tool_missing_from_path_refuses_before_consent(
    installed_with_kind: store.LockEntry, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from click.testing import CliRunner

    monkeypatch.setenv("PATH", f"{tmp_path / 'empty-bin'}:/usr/bin:/bin")

    result = CliRunner().invoke(
        _drill.drill_group, ["check", f"{installed_with_kind.id}/echo-basics/echo-01"], input="y\n"
    )

    assert result.exit_code == 1, result.output
    assert "kind" in result.output and "nothing was executed" in result.output
    assert "Run this phase now?" not in result.output, "refused before the consent prompt"


# --- W3: the registered root CLI reaches R's drill group -----------------------------------

RUNNER_OFFLINE = Path(__file__).parent / "fixtures" / "modules" / "runner-offline"


def test_root_cli_resolves_drill_setup_and_refuses_without_consent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`studyloop drill setup <module>/<deck>/<task>` resolves through the LazyGroup map to
    lane R's group; declining the consent prompt exits 2 and runs nothing."""
    from click.testing import CliRunner

    from studyloop.cli import cli as root_cli

    root = tmp_path / "modules"
    monkeypatch.setattr(store, "default_store_root", lambda: root)
    monkeypatch.setattr(_drill, "attempts_root", lambda: tmp_path / "module-attempts")
    entry = store.ModuleStore(root).add(RUNNER_OFFLINE)

    result = CliRunner().invoke(
        root_cli, ["drill", "setup", f"{entry.id}/offline/echo-check"], input="n\n"
    )

    assert result.exit_code == 2, result.output
    assert "Drill phase: setup" in result.output
    assert "Not confirmed -- nothing executed." in result.output
    assert not list((tmp_path / "module-attempts").rglob("hello.txt")), "setup never ran"
