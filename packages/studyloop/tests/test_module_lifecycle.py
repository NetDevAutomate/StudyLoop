"""Lifecycle tests for optional modules: ``module new`` (C3) and the store (C4).

Module-contract v1, lane C. The scaffold must pass every conformance rule and carry one
offline, ``echo``-based drill; the store must refuse an unconforming module without touching
``modules.lock.json``. Red evidence lives under ``openspec/changes/module-contract-v1/evidence/C/``.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import TYPE_CHECKING

import pytest
import yaml

from studyloop.modules.check import check_module
from studyloop.modules.scaffold import ScaffoldError, scaffold_module

if TYPE_CHECKING:
    from pathlib import Path

_NETWORK_OR_CLUSTER = ("curl", "wget", "docker", "kind", "kubectl", "http://", "https://")


# ---------------------------------------------------------------------------
# C3 -- scaffold
# ---------------------------------------------------------------------------


def test_scaffold_passes_every_rule(tmp_path: Path) -> None:
    """Spec scenario: the output of ``module new <id>`` passes ``module check`` with no findings."""
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    report = check_module(module)
    assert report.findings == []
    assert report.ok is True


def test_scaffold_carries_one_offline_echo_drill(tmp_path: Path) -> None:
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    decks = sorted((module / "decks").glob("*.json"))
    assert len(decks) == 1
    deck = json.loads(decks[0].read_text(encoding="utf-8"))
    [task] = deck["tasks"]
    assert task["verification"]["command"] == "scripts/check.sh"
    script = module / "scripts" / "check.sh"
    text = script.read_text(encoding="utf-8")
    assert "echo" in text
    assert not any(token in text for token in _NETWORK_OR_CLUSTER)
    assert os.access(script, os.X_OK)
    # It really is offline and really exits 0: run it with a bare PATH and no inherited env.
    run = subprocess.run(
        ["/bin/sh", str(script)],
        env={"PATH": "/usr/bin:/bin"},
        cwd=module,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert (run.returncode, run.stdout.strip()) == (0, "ready")


def test_scaffold_manifest_declares_only_what_the_drill_uses(tmp_path: Path) -> None:
    module = scaffold_module(tmp_path / "my-drills", "my-drills", topic="kubernetes")
    manifest = yaml.safe_load((module / "module.yaml").read_text(encoding="utf-8"))
    assert manifest["id"] == "my-drills"
    assert manifest["contract"] == 1
    assert manifest["topic"] == "kubernetes"
    assert manifest["capabilities"] == ["check"]
    assert manifest["prerequisites"] == []
    assert manifest["target"] == {"kind": "workdir"}


def test_scaffold_ships_its_own_offline_shell_test_not_python(tmp_path: Path) -> None:
    """§5.1 asks for ``tests/``; MC012 forbids ``*.py``, so the module's test is a shell script."""
    module = scaffold_module(tmp_path / "my-drills", "my-drills")
    tests = sorted(p.name for p in (module / "tests").iterdir())
    assert tests == ["check.sh"]
    assert not list(module.rglob("*.py"))
    run = subprocess.run(
        ["/bin/sh", str(module / "tests" / "check.sh")],
        env={"PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert run.returncode == 0, run.stderr


def test_scaffold_refuses_an_invalid_id(tmp_path: Path) -> None:
    with pytest.raises(ScaffoldError, match="not a module id"):
        scaffold_module(tmp_path / "x", "My Drills")
    assert not (tmp_path / "x").exists()


def test_scaffold_refuses_a_non_empty_destination(tmp_path: Path) -> None:
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(ScaffoldError, match="not empty"):
        scaffold_module(occupied, "occupied")
    assert sorted(p.name for p in occupied.iterdir()) == ["notes.txt"]
