"""Fixture modules the personas install (module-contract v1, lane U1).

``build_missing_kind_module`` is the brief's "missing kind" module: ``valid-scaffold`` copied
and re-identified, declaring ``prerequisites: [kind]`` on a ``workdir`` target. It conforms to
MC001-MC017 (``kind`` is in core's enum, MC005), so ``module add`` accepts it -- the point of the
persona step is what happens AFTER install on a machine with no ``kind`` on the PATH: the
prerequisite report (``studyloop doctor``) and the refusal before consent (``studyloop drill``),
with nothing created. The fixture is built at run time into the persona's world rather than
committed, so nothing under ``tests/fixtures/modules/`` (lane C's) changes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

#: Lane C's fixture modules (``tests/fixtures/modules``), resolved from this file.
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "modules"
VALID_SCAFFOLD = FIXTURES / "valid-scaffold"
K8S_OFFLINE = FIXTURES / "k8s-offline"

MISSING_KIND_ID = "missing-kind"
MISSING_KIND_DRILL = f"{MISSING_KIND_ID}/echo-basics/echo-01"


def build_missing_kind_module(destination: Path) -> Path:
    """Copy ``valid-scaffold`` to ``destination`` as ``missing-kind`` with ``kind`` declared."""
    shutil.copytree(VALID_SCAFFOLD, destination, symlinks=False)
    manifest = destination / "module.yaml"
    text = manifest.read_text(encoding="utf-8")
    assert "id: echo-drills\n" in text and "prerequisites: []\n" in text, text
    text = text.replace("id: echo-drills\n", f"id: {MISSING_KIND_ID}\n", 1)
    text = text.replace(
        "title: Echo drills (offline fixture)\n", "title: Echo drills (cluster tool required)\n", 1
    )
    text = text.replace("prerequisites: []\n", "prerequisites:\n  - id: kind\n", 1)
    manifest.write_text(text, encoding="utf-8")
    readme = destination / "README.md"
    readme.write_text(
        readme.read_text(encoding="utf-8").replace(
            "## Prerequisites\n", "## Prerequisites\n\n`kind` on your PATH.\n", 1
        ),
        encoding="utf-8",
    )
    return destination


def copy_module(source: Path, destination: Path) -> Path:
    """A writable copy of a fixture module (the one the contributor breaks and repairs)."""
    shutil.copytree(source, destination, symlinks=False)
    return destination


__all__ = [
    "FIXTURES",
    "K8S_OFFLINE",
    "MISSING_KIND_DRILL",
    "MISSING_KIND_ID",
    "VALID_SCAFFOLD",
    "build_missing_kind_module",
    "copy_module",
]
